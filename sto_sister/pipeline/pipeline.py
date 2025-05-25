from contextlib import contextmanager

# from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional

import time
import numpy as np

from pathlib import Path
import logging

# --- Import modules ---
from .core import *
from ..exceptions import *

from ..utils.hashindex import HashIndex

from .progress_reporter import PipelineProgressCallback
from ..stages import (
    LocateLabelsStage,
    ClassifyLayoutStage,
    LocateIconGroupsStage,
    LocateIconSlotsStage,
    PrefilterIconsStage,
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
        on_pipeline_complete: Optional[
            Callable[[PipelineState, Dict[str, Any], Dict[str, Any]], None]
        ] = None,
    ):
        self.metrics: Dict[str, Dict[str, float]] = {}
        self.app_config: Dict[str, Any] = {}

        self.config = config
        self.app_init()

        self.stages: List[PipelineStage] = [
            LocateLabelsStage(config.get("locate_labels", {"debug": True}), self.app_config),
            ClassifyLayoutStage(config.get("classify_layout", {}), self.app_config),
            LocateIconGroupsStage(config.get("icon_group", {}), self.app_config),
            LocateIconSlotsStage(config.get("icon_slot", {}), self.app_config),
            PrefilterIconsStage(
                config.get("prefilter_icons", {"debug": True}), self.app_config
            ),
            DetectIconOverlaysStage(
                config.get("icon_overlay", {}), self.app_config
            ),
            DetectIconsStage(config.get("detect_icons", {}), self.app_config),
            OutputTransformationStage(config.get("output_transformation", {}), self.app_config),
        ]

        self.on_progress = on_progress
        self.on_interactive = on_interactive
        self.on_error = on_error

        self.on_metrics_complete = on_metrics_complete

        self.on_stage_start = on_stage_start
        self.on_stage_complete = on_stage_complete
        self.on_pipeline_complete = on_pipeline_complete

    def app_init(self) -> None:
        logger.info(f"Initializing SISTER with config: {self.config}")
        self.app_config["hash_index"] = HashIndex(
            self.config.get("hash_index_dir"),
            self.config.get("engine", "phash"),
            match_size=self.config.get("hash_max_size", (16, 16)),
            output_file=self.config.get("hash_index_file", "hash_index.json"),
        )

        self.app_config["log_level"] = self.config.get("log_level", "INFO")

        icon_root = Path(self.config.get("icon_dir"))

        self.app_config["icon_sets"] = {
            "ship": {
                "Fore Weapon": [
                    icon_root / "space/weapons/fore",
                    icon_root / "space/weapons/unrestricted",
                ],
                "Aft Weapon": [
                    icon_root / "space/weapons/aft",
                    icon_root / "space/weapons/unrestricted",
                ],
                "Experimental Weapon": [icon_root / "space/weapons/experimental"],
                "Shield": [icon_root / "space/shield"],
                "Secondary Deflector": [icon_root / "space/secondary_deflector"],
                "Deflector": [
                    icon_root / "space/deflector",
                    icon_root / "space/secondary_deflector",
                ],  # Console doesn't have a specific label for Secondary Deflector, it's located under the Deflector label.
                "Impulse": [icon_root / "space/impulse"],
                "Warp": [icon_root / "space/warp"],
                "Singularity": [icon_root / "space/singularity"],
                "Hangar": [icon_root / "space/hangar"],
                "Devices": [icon_root / "space/device"],
                "Universal Console": [
                    icon_root / "space/consoles/universal",
                    icon_root / "space/consoles/engineering",
                    icon_root / "space/consoles/tactical",
                    icon_root / "space/consoles/science",
                ],
                "Engineering Console": [
                    icon_root / "space/consoles/engineering",
                    icon_root / "space/consoles/universal",
                ],
                "Tactical Console": [
                    icon_root / "space/consoles/tactical",
                    icon_root / "space/consoles/universal",
                ],
                "Science Console": [
                    icon_root / "space/consoles/science",
                    icon_root / "space/consoles/universal",
                ],
            },
            "pc_ground": {
                "Body": [icon_root / "ground/armor"],
                "Shield": [icon_root / "ground/shield"],
                "EV Suit": [icon_root / "ground/ev_suit"],
                "Kit Modules": [icon_root / "ground/kit_module"],
                "Kit": [icon_root / "ground/kit"],
                "Devices": [icon_root / "ground/device"],
                "Weapon": [icon_root / "ground/weapon"],
            },
            "console_ground": {
                "Body": [icon_root / "ground/armor"],
                "Shield": [icon_root / "ground/shield"],
                "EV Suit": [icon_root / "ground/ev_suit"],
                "Kit": [
                    icon_root / "ground/kit_module"
                ],  # Console swaps "Kit Modules" to "Kit"
                "Kit Frame": [
                    icon_root / "ground/kit"
                ],  # And "Kit" becomes "Kit Frame"
                "Devices": [icon_root / "ground/device"],
                "Weapon": [icon_root / "ground/weapon"],
            },

            "traits": {
                "Personal Space Traits": [ icon_root / "space/traits/personal" ],
                "Space Reputation": [ icon_root / "space/traits/reputation" ],
                "Active Space Reputation": [ icon_root / "space/traits/active_reputation" ],

                "Personal Ground Traits": [ icon_root / "ground/traits/personal" ],
                "Ground Reputation": [ icon_root / "ground/traits/reputation" ],
                "Active Ground Reputation": [ icon_root / "ground/traits/active_reputation" ],

                "Starship Traits": [ icon_root / "space/traits/starship" ],
            }
        }

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

    def run(self, screenshots: List[np.ndarray]) -> PipelineState:
        self.start_metric("pipeline")

        ctx = PipelineState(
            screenshots=screenshots, config=self.config, app_config=self.app_config
        )
        results: Dict[str, Any] = {}

        for stage in self.stages:
            # notify start
            with self._handle_errors(stage.name, ctx):
                self.start_metric(stage.name)
                #self.on_progress(stage.name, "Stage startup", 0.0, ctx)

                if self.on_stage_start:
                    self.on_stage_start(stage.name, ctx)

            # run stage
            with self._handle_errors(stage.name, ctx):
                prog_cb = PipelineProgressCallback(
                    self.on_progress,
                    stage.name,
                    ctx
                )
                stage_result = stage.process(ctx, prog_cb)
                # stage_result = stage.process(
                #     ctx, lambda pct, substage=None, name=stage.name: self.on_progress(name, substage, pct, ctx)
                # )
                # update context and results
                ctx = stage_result.context
                results[stage.name] = stage_result.output

            # notify completion
            with self._handle_errors(stage.name, ctx):
                #self.on_progress(stage.name, "Stage completion", 1.0, ctx)
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

        # on_pipeline_complete hook
        if self.on_pipeline_complete:
            self.start_metric("pipeline_complete")
            with self._handle_errors("pipeline_complete", ctx):
                self.on_pipeline_complete(
                    ctx, ctx.output if ctx.output else {}, results
                )
            self.end_metric("pipeline_complete")

        # on_metrics_complete hook
        if self.on_metrics_complete:
            with self._handle_errors("metrics_complete", ctx):
                self.on_metrics_complete(self.get_metrics())

        return ctx, results

    @contextmanager
    def _handle_errors(self, stage_name: str, ctx: PipelineState):
        try:
            yield
        except Exception as e:
            err = PipelineError(stage_name, e, ctx)
            if self.on_error:
                try:
                    self.on_error(err)
                except Exception as hook_exc:
                    logging.error(f"on_error hook failed: {hook_exc}")
            else:
                # no on_error -> re-raise so non-pipeline callers still see it
                raise


def build_default_pipeline(
    on_progress: Callable[[str, float, PipelineState], None],
    on_interactive: Callable[[str, PipelineState], PipelineState],
    on_error: Callable[[PipelineError], None],
    on_metrics_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
    on_stage_start: Optional[Callable[[str, PipelineState, Any], None]] = None,
    on_stage_complete: Optional[Callable[[str, PipelineState, Any], None]] = None,
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
        on_pipeline_complete=on_pipeline_complete,
    )
