from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional


import time
import numpy as np

# --- Import modules ---
from src.exceptions import *

from src.locator import LabelLocator
from src.classifier import Classifier
from src.region import RegionDetector
from src.iconslot import IconSlotDetector
from src.iconmatch import IconMatcher
from src.prefilter import IconPrefilter
from src.hashindex import HashIndex


# --- Core value objects ---
@dataclass(frozen=True)
class Slot:
    region_label: str
    index: int
    bbox: Tuple[int, int, int, int]


@dataclass
class PipelineContext:
    screenshot: np.ndarray
    config: Dict[str, Any] = field(default_factory=dict)
    labels: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)
    regions: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)
    slots: Dict[str, List[Slot]] = field(default_factory=dict)
    classification: Dict[Slot, Any] = field(default_factory=dict)
    predicted_qualities: Any = None
    predicted_icons: Any = None
    found_icons: Any = None
    filtered_icons: Any = None


@dataclass
class StageResult:
    """
    Holds the context after a stage and any stage-specific output.
    """

    context: PipelineContext
    output: Any


# --- Abstract Stage ---
class Stage:
    name: str = ""
    interactive: bool = False

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        """
        Execute the stage, updating ctx in place or returning a new one.
        Use report(stage_name, percent_complete) to emit progress.
        """
        raise NotImplementedError


# --- Concrete Stages ---
class LabelLocatorStage(Stage):
    name = "label_locator"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.locator = LabelLocator(**opts)

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)
        ctx.labels = self.locator.locate(ctx.screenshot)
        report(self.name, 1.0)
        return StageResult(ctx, ctx.labels)


class ClassifierStage(Stage):
    name = "classifier"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.classifier = Classifier(**opts)

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)
        ctx.classification = self.classifier.classify(ctx.labels)

        if (
            ctx.classification["build_type"] == "PC Ship Build"
            or ctx.classification["build_type"] == "Console Ship Build"
        ):
            ctx.classification["icon_set"] = "ship"

        elif ctx.classification["build_type"] == "PC Ground Build":
            ctx.classification["icon_set"] = "pc_ground"

        elif ctx.classification["build_type"] == "Console Ground Build":
            ctx.classification["icon_set"] = "console_ground"

        report(self.name, 1.0)
        return StageResult(ctx, ctx.classification)


class RegionDetectionStage(Stage):
    name = "region_detection"
    interactive = True  # allow UI confirmation

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.detector = RegionDetector(**opts)

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        ctx.regions = self.detector.detect_regions(
            ctx.screenshot, ctx.labels, ctx.classification
        )

        report(self.name, 1.0)
        return StageResult(ctx, ctx.regions)


class IconSlotDetectionStage(Stage):
    name = "iconslot_detection"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.slot_detector = IconSlotDetector(**opts)

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        ctx.slots = self.slot_detector.detect_slots(ctx.screenshot, ctx.regions)

        report(self.name, 1.0)
        return StageResult(ctx, ctx.slots)


class IconMatchingQualityDetectionStage(Stage):
    name = "icon_quality_detection"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.matcher = IconMatcher(
            hash_index=opts.get("hash_index"),
            debug=opts.get("debug", False),
            engine_type=opts.get("engine_type", "ssim"),
        )

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)
        icon_dir_map = ctx.config.get("icon_dirs", {})
        overlays = self.matcher.load_quality_overlays(ctx.config.get("overlay_dir", ""))
        ctx.predicted_qualities = self.matcher.quality_predictions(
            ctx.slots,
            overlays,
            threshold=self.opts.get("threshold", 0.8),
        )
        report(self.name, 1.0)
        return StageResult(ctx, ctx.predicted_qualities)


class IconPrefilterStage(Stage):
    name = "icon_prefilter"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts

        hash_index = HashIndex(
            opts.get("hash_index_dir"),
            "phash",
            match_size=opts.get("hash_max_size", (16, 16)),
            output_file=opts.get("hash_index_file", "hash_index.json"),
        )

        self.prefilterer = IconPrefilter(
            hash_index=hash_index,
            icon_root=opts.get("icon_root"),
            debug=opts.get("debug", False),
            engine_type=opts.get("engine_type", "phash"),
        )

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        icon_sets = ctx.config.get("icon_sets", {})
        icon_set = icon_sets[ctx.classification["icon_set"]]

        ctx.predicted_icons = self.prefilterer.icon_predictions(
            ctx.slots, icon_set
        )
        ctx.found_icons = self.prefilterer.found_icons
        ctx.filtered_icons = self.prefilterer.filtered_icons

        report(self.name, 1.0)
        return StageResult(ctx, ctx.predicted_icons)


class IconMatchingStage(Stage):
    name = "icon_matching"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.matcher = IconMatcher(
            hash_index=opts.get("hash_index"),
            debug=opts.get("debug", False),
            engine_type=opts.get("engine_type", "ssim"),
        )

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)
        icon_sets = ctx.config.get("icon_sets", {})
        ctx.overlays = self.matcher.load_quality_overlays(
            ctx.config.get("overlay_dir", "")
        )
        # print(f"[Matching] ctx.filtered_icons: {ctx.filtered_icons}")
        ctx.matches = self.matcher.match_all(
            ctx.slots,
            icon_sets,
            ctx.overlays,
            ctx.predicted_qualities,
            ctx.filtered_icons,
            ctx.found_icons,
            threshold=self.opts.get("threshold", 0.7),
        )
        report(self.name, 1.0)
        return StageResult(ctx, ctx.matches)


class OutputTransformationStage(Stage):
    name = "output_transformation"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        # start with whatever matches we already have
        ctx.output = {
            "matches": ctx.matches,
            "predicted_icons": ctx.predicted_icons,
            "predicted_qualities": ctx.predicted_qualities,
        }

        # we're going to merge any predicted icons into ctx.matches if they don't already exist
        # this catches cases where we have predicted icons but no matches, so we at least provide some output that is hopefully useful
        matches = ctx.matches
        for region in ctx.predicted_icons:
            region_name = region
            for slot in ctx.predicted_icons[region]:
                slot_name = slot

                # find any predicted icons for this region/slot
                predicted = ctx.predicted_icons.get(region_name, {}).get(slot_name, [])

                # check current output for this region/slot
                existing = matches.get(region_name, {}).get(slot_name, [])

                # if there's a prediction and no existing match, copy it over
                if predicted and not existing:
                    # ensure the dicts exist
                    matches.setdefault(region_name, {})[slot_name] = predicted.copy()

                    # copy over the predicted quality if we have it
                    if ctx.predicted_qualities[region_name]:
                        for idx, item in enumerate(matches[region_name][slot_name]):
                            matches[region_name][slot_name][idx][
                                "predicted_quality"
                            ] = ctx.predicted_qualities[region_name][slot_name]

        report(self.name, 1.0)
        return StageResult(ctx, ctx.output)


# --- The Pipeline Orchestrator ---
class SISTER:
    def __init__(
        self,
        stages: List[Stage],
        on_progress: Callable[[str, float, PipelineContext], None],
        on_interactive: Callable[[str, PipelineContext], PipelineContext],
        on_error: Callable[[PipelineError], None],
        config: Dict[str, Any],
        on_metrics_complete: Optional[
            Callable[[str, PipelineContext, Any], None]
        ] = None,
        on_stage_start: Optional[Callable[[str, PipelineContext], None]] = None,
        on_stage_complete: Optional[Callable[[str, PipelineContext, Any], None]] = None,
        on_pipeline_complete: Optional[
            Callable[[PipelineContext, Dict[str, Any], Dict[str, Any]], None]
        ] = None,
    ):
        self.metrics: Dict[str, Dict[str, float]] = {}

        self.stages = stages

        self.on_progress = on_progress
        self.on_interactive = on_interactive
        self.on_error = on_error

        self.on_metrics_complete = on_metrics_complete

        self.on_stage_start = on_stage_start
        self.on_stage_complete = on_stage_complete
        self.on_pipeline_complete = on_pipeline_complete

        self.config = config

    def start_metric(self, name: str) -> None:
        self.metrics[name] = {
            "start": time.time(),
        }

    def end_metric(self, name: str) -> None:
        self.metrics[name]["end"] = time.time()

    def get_metrics(self) -> List[Dict[str, float]]:
        return [{"name": name, "duration": metric["end"] - metric["start"]} for name, metric in self.metrics.items()]

    def run(self, screenshot: np.ndarray) -> PipelineContext:
        self.start_metric("pipeline")
        
        ctx = PipelineContext(screenshot=screenshot, config=self.config)
        results: Dict[str, Any] = {}

        for stage in self.stages:
            # notify start
            with self._handle_errors(stage.name, ctx):
                self.start_metric(stage.name)
                self.on_progress(stage.name, 0.0, ctx)

                if self.on_stage_start:
                    self.on_stage_start(stage.name, ctx)

            # run stage
            with self._handle_errors(stage.name, ctx):
                stage_result = stage.run(
                    ctx, lambda pct, name=stage.name: self.on_progress(name, pct, ctx)
                )
                # update context and results
                ctx = stage_result.context
                results[stage.name] = stage_result.output

            # notify completion
            with self._handle_errors(stage.name, ctx):
                self.on_progress(stage.name, 1.0, ctx)
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
    def _handle_errors(self, stage_name: str, ctx: PipelineContext):
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
    on_progress: Callable[[str, float, PipelineContext], None],
    on_interactive: Callable[[str, PipelineContext], PipelineContext],
    on_error: Callable[[PipelineError], None],
    on_metrics_complete: Optional[Callable[[str, PipelineContext, Any], None]] = None,
    on_stage_start: Optional[Callable[[str, PipelineContext, Any], None]] = None,
    on_stage_complete: Optional[Callable[[str, PipelineContext, Any], None]] = None,
    on_pipeline_complete: Optional[
        Callable[[PipelineContext, Dict[str, Any]], None]
    ] = None,
    config: Dict[str, Any] = {},
) -> SISTER:
    stages: List[Stage] = [
        LabelLocatorStage(config.get("locator", {"debug": True})),
        ClassifierStage(config.get("classifier", {})),
        RegionDetectionStage(config.get("region", {})),
        IconSlotDetectionStage(config.get("iconslot", {})),
        IconPrefilterStage(config.get("prefilter", {"debug": True})),
        IconMatchingQualityDetectionStage(config.get("quality", {})),
        IconMatchingStage(config.get("matching", {})),
        OutputTransformationStage(config.get("transform", {})),
    ]
    return SISTER(
        stages,
        on_progress,
        on_interactive,
        on_error,
        config=config,
        on_metrics_complete=on_metrics_complete,
        on_stage_start=on_stage_start,
        on_stage_complete=on_stage_complete,
        on_pipeline_complete=on_pipeline_complete,
    )
