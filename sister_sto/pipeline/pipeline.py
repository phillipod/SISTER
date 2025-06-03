from contextlib import contextmanager

# from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional
import weakref

import time
import numpy as np

from pathlib import Path
import logging

# --- Import modules ---
from .core import *
from ..exceptions import *

from ..utils.hashindex import HashIndex
from ..utils.persistent_executor import PersistentProcessPoolExecutor

from .progress_reporter import PipelineProgressReporter
from ..tasks import (
    AppInitTask,
    StartExecutorPoolTask,
    StopExecutorPoolTask,
    DownloadAllIconsTask,
    BuildHashCacheTask,
)

from ..stages import (
    LocateLabelsStage,
    ClassifyLayoutStage,
    LocateIconGroupsStage,
    LocateIconSlotsStage,
    PrefilterIconsStage,
    LoadIconsStage,
    DetectIconOverlaysStage,
    DetectIconsStage,
    OutputTransformationStage,
)

logger = logging.getLogger(__name__)

# --- The Pipeline Orchestrator ---
class SISTER:
    def __init__(
        self,
        on_progress: Callable[[str, str, float, PipelineState], None],
        on_interactive: Callable[[str, PipelineState], PipelineState],
        on_error: Callable[[PipelineError], None],
        config: Dict[str, Any],
        on_metrics_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
        on_stage_start: Optional[Callable[[str, PipelineState], None]] = None,
        on_stage_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
        on_task_start: Optional[Callable[[str, PipelineState], None]] = None,
        on_task_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
        on_pipeline_complete: Optional[
            Callable[[PipelineState, Dict[str, Any], Dict[str, Any]], None]
        ] = None,
    ):
        self.metrics: Dict[str, Dict[str, float]] = {}
        self.app_config: Dict[str, Any] = {}
        self.stage_statuses: Dict[str, StageStatus] = {}

        self.config = config

        self.on_progress = on_progress
        self.on_interactive = on_interactive
        self.on_error = on_error

        self.on_metrics_complete = on_metrics_complete

        self.on_stage_start = on_stage_start
        self.on_stage_complete = on_stage_complete
        self.on_task_start = on_task_start
        self.on_task_complete = on_task_complete

        self.on_pipeline_complete = on_pipeline_complete

        self._started = False

        self.init_tasks: List[PipelineTask] = [
            AppInitTask(config, self.app_config),
        ]

        self.init()

        self.startup_tasks: List[PipelineTask] = [
            StartExecutorPoolTask(config.get("executor", {}), self.app_config),
        ]
        
        self.shutdown_tasks: List[PipelineTask] = [
            StopExecutorPoolTask(config.get("executor", {}), self.app_config),
        ]
        
        self.run_tasks: List[PipelineTask] = []

        self.callable_tasks: Dict[str, PipelineTask] = {
            "download_all_icons": DownloadAllIconsTask(config.get("download", {}), self.app_config),
            "build_hash_cache": BuildHashCacheTask(config.get("hash_cache", {}), self.app_config),
        }

        # Define stage dependencies
        self.stages: List[PipelineStage] = [
            LocateLabelsStage(config.get("locate_labels", {"debug": True}), self.app_config),
            ClassifyLayoutStage(config.get("classify_layout", {}), self.app_config),
            LocateIconGroupsStage(config.get("icon_group", {}), self.app_config),
            LocateIconSlotsStage(config.get("icon_slot", {}), self.app_config),
            PrefilterIconsStage(
                config.get("prefilter_icons", {"debug": True}), self.app_config
            ),
            LoadIconsStage(config.get("load_icons", {}), self.app_config),
            DetectIconOverlaysStage(
                config.get("icon_overlay", {}), self.app_config
            ),
            DetectIconsStage(config.get("detect_icons", {}), self.app_config),
            OutputTransformationStage(config.get("output_transformation", {}), self.app_config),
        ]

        # Initialize stage statuses
        for stage in self.stages:
            self.stage_statuses[stage.name] = stage.status
            
        # Add special statuses for pipeline operations
        self.stage_statuses["pipeline_complete"] = StageStatus("pipeline_complete")
        self.stage_statuses["metrics_complete"] = StageStatus("metrics_complete")

    def start_metric(self, name: str) -> None:
        self.metrics[name] = {
            "start": time.time(),
        }

    def end_metric(self, name: str) -> None:
        self.metrics[name]["end"] = time.time()

    def get_metrics(self) -> List[Dict[str, float]]:
        return [
            {"name": name, "duration": metric["end"] - metric["start"]}
            for name, metric in self.metrics.items()
        ]

    def _run_task(self, task: PipelineTask, ctx: Optional[PipelineState]):
        if self.on_task_start:
            self.on_task_start(task.name, ctx)

        reporter = PipelineProgressReporter(self.on_progress, task.name, ctx)

        result = task.execute(ctx, reporter)

        if self.on_task_complete:
            self.on_task_complete(task.name, ctx, result)

        return result

    def execute_task(self, task: str):
        # If task is in self.callable_tasks, run it. Callable tasks get the _init_ctx

        if task in self.callable_tasks:
            return self._run_task(self.callable_tasks[task], self._init_ctx)

    def init(self):
        self.start_metric("pipeline_init_tasks")
        
        if not getattr(self, "_init_ctx", False):
            ctx = PipelineState(
                screenshots=None, config=self.config, app_config=self.app_config
            )

            for task in self.init_tasks:
                self._run_task(task, ctx)

            self._init_ctx = ctx
        
        self.end_metric("pipeline_init_tasks")

    def startup(self):
        if not self._started:
            self.start_metric("pipeline_startup_tasks")
            
            if self._init_ctx:
                for task in self.startup_tasks:
                    self._run_task(task, self._init_ctx)

                self._started = True
                weakref.finalize(self, self.shutdown)
            
            self.end_metric("pipeline_startup_tasks")

    def shutdown(self):
        if self._init_ctx and self._started:
            for task in self.shutdown_tasks:
                self._run_task(task, self._init_ctx)
        
        self._init_ctx = None

    @contextmanager
    def _handle_errors(self, stage_name: str, ctx: PipelineState):
        """
        Context manager for handling stage errors and updating stage status.
        """
        try:
            yield
            self.stage_statuses[stage_name].completed = True
            self.stage_statuses[stage_name].success = True
        except Exception as e:
            self.stage_statuses[stage_name].completed = True
            self.stage_statuses[stage_name].success = False
            self.stage_statuses[stage_name].error = e
            if isinstance(e, StageError):
                # Re-raise stage errors directly
                raise
            else:
                # Wrap other exceptions in PipelineError
                raise PipelineError(stage_name, e, ctx) from e

    def run(self, screenshots: List[np.ndarray]) -> PipelineState:
        ctx = self._init_ctx.copy()
        ctx.set_screenshots(screenshots)

        results: Dict[str, Any] = {}

        self.start_metric("pipeline")

        if len(self.run_tasks) > 0: 
            self.start_metric("run_tasks")

            for task in self.run_tasks:
                self._run_task(task, ctx)   

            self.end_metric("run_tasks")

        for stage in self.stages:
            # Check dependencies before running stage
            if not stage.check_dependencies(self.stage_statuses):
                error_msg = f"Dependencies not met for stage {stage.name}"
                self.stage_statuses[stage.name].completed = True
                self.stage_statuses[stage.name].success = False
                self.stage_statuses[stage.name].error = StageError(error_msg)
                if self.on_error:
                    self.on_error(PipelineError(stage.name, StageError(error_msg), ctx))
                continue

            # start metric and notify start
            with self._handle_errors(stage.name, ctx):
                self.start_metric(stage.name)

                if self.on_stage_start:
                    self.on_stage_start(stage.name, ctx)

            # run stage
            try:
                with self._handle_errors(stage.name, ctx):
                    prog_cb = PipelineProgressReporter(
                        self.on_progress,
                        stage.name,
                        ctx
                    )
                    stage_result = stage.process(ctx, prog_cb)

                    # Update context and results only if stage succeeded
                    if stage_result.success:
                        ctx = stage_result.context
                        results[stage.name] = stage_result.output
                    else:
                        error_msg = f"Stage {stage.name} failed"
                        if self.on_error:
                            self.on_error(PipelineError(stage.name, StageError(error_msg), ctx))
                        continue

            except Exception as e:
                # Handle any unhandled exceptions
                if self.on_error:
                    self.on_error(PipelineError(stage.name, e, ctx))
                continue

            # end metric
            self.end_metric(stage.name)

            # on_stage_complete hook
            if self.on_stage_complete:
                self.start_metric(stage.name + "_stage_complete")
                with self._handle_errors(stage.name, ctx):
                    self.on_stage_complete(stage.name, ctx, stage_result.output)
                self.end_metric(stage.name + "_stage_complete")

            # interactive hook
            if stage.interactive:
                self.start_metric(stage.name + "_interactive")
                with self._handle_errors(stage.name, ctx):
                    ctx = self.on_interactive(stage.name, ctx)
                self.end_metric(stage.name + "_interactive")

        # end pipeline metric
        self.end_metric("pipeline")

        # Call pipeline complete callback if all stages succeeded
        if self.on_pipeline_complete:
            self.start_metric("pipeline_complete")
            with self._handle_errors("pipeline_complete", ctx):
                # Only check regular stage statuses, not the special ones
                regular_stages = {name: status for name, status in self.stage_statuses.items() 
                                if name not in ["pipeline_complete", "metrics_complete"]}
                if all(status.success for status in regular_stages.values()):
                    self.on_pipeline_complete(
                        ctx, ctx.output if ctx.output else {}, results
                    )
            self.end_metric("pipeline_complete")

        # Call metrics complete callback after pipeline complete
        if self.on_metrics_complete:
            with self._handle_errors("metrics_complete", ctx):
                self.on_metrics_complete(self.get_metrics())

        return ctx, results

def build_default_pipeline(
    on_progress: Callable[[str, float, PipelineState], None],
    on_interactive: Callable[[str, PipelineState], PipelineState],
    on_error: Callable[[PipelineError], None],
    on_metrics_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
    on_stage_start: Optional[Callable[[str, PipelineState, Any], None]] = None,
    on_stage_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
    on_task_start: Optional[Callable[[str, PipelineState, Any], None]] = None,
    on_task_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
    on_pipeline_complete: Optional[
        Callable[[PipelineState, Dict[str, Any]], None]
    ] = None,
    config: Dict[str, Any] = {},
) -> SISTER:
    return SISTER(
        on_progress,
        on_interactive,
        on_error,
        config=config,
        on_metrics_complete=on_metrics_complete,
        on_stage_start=on_stage_start,
        on_stage_complete=on_stage_complete,
        on_task_start=on_task_start,
        on_task_complete=on_task_complete,
        on_pipeline_complete=on_pipeline_complete,
    )
