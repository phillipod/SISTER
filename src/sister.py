from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional
import numpy as np

# --- Import your existing modules (adjust names as needed) ---
from src.locator import LabelLocator
from src.classifier import Classifier
#from region import RegionDetector
#from iconslot import IconSlotDetector


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
        self,
        ctx: PipelineContext,
        report: Callable[[str, float], None]
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

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> PipelineContext:
        report(self.name, 0.0)
        ctx.labels = self.locator.locate(ctx.screenshot)    
        report(self.name, 1.0)
        return StageResult(ctx, ctx.labels)


class ClassifierStage(Stage):
    name = "classifier"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.classifier = Classifier(**opts)

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> PipelineContext:
        report(self.name, 0.0)
        ctx.classification = self.classifier.classify(ctx.labels)
        report(self.name, 1.0)
        return StageResult(ctx, ctx.classification)

# class RegionDetectionStage(Stage):
#     name = "region_detection"
#     interactive = True  # allow UI confirmation

#     def __init__(self, opts: Dict[str, Any]):
#         self.opts = opts
#         self.detector = RegionDetector(**opts)

#     def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> PipelineContext:
#         report(self.name, 0.0)
#         ctx.regions = self.detector.detect_regions(ctx.screenshot)
#         report(self.name, 1.0)
#         return ctx

# class IconSlotDetectionStage(Stage):
#     name = "iconslot_detection"

#     def __init__(self, opts: Dict[str, Any]):
#         self.opts = opts
#         self.slot_detector = IconSlotDetector(**opts)

#     def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> PipelineContext:
#         report(self.name, 0.0)
#         slots_by_region: Dict[str, List[Slot]] = {}
#         regions = ctx.regions
#         for i, (label, bbox) in enumerate(regions.items()):
#             # allow override of threshold via context config
#             threshold = self.opts.get("threshold", ctx.config.get("iconslot", {}).get("threshold"))
#             raw_slots = self.slot_detector.detect_slots(ctx.screenshot, bbox, threshold=threshold)  # type: ignore
#             slots_by_region[label] = [Slot(label, idx, s) for idx, s in enumerate(raw_slots)]
#             report(self.name, (i + 1) / max(len(regions), 1))
#         ctx.slots = slots_by_region
#         report(self.name, 1.0)
#         return ctx



# --- The Pipeline Orchestrator ---
class SISTER:
    def __init__(
        self,
        stages: List[Stage],
        on_progress: Callable[[str, float, PipelineContext], None],
        on_interactive: Callable[[str, PipelineContext], PipelineContext],
        config: Dict[str, Any],
        on_stage_complete: Optional[Callable[[str, PipelineContext, Any], None]] = None,  # Callable[[str, PipelineContext, Any], None],
        on_pipeline_complete: Optional[Callable[[PipelineContext, Dict[str, Any]], None] ] = None  # Callable[[PipelineContext, Dict[str, Any]], None]
    ):
        self.stages = stages
        self.on_progress = on_progress
        self.on_interactive = on_interactive
        self.on_stage_complete = on_stage_complete
        self.on_pipeline_complete = on_pipeline_complete

        self.config = config

    def run(self, screenshot: np.ndarray) -> PipelineContext:
        ctx = PipelineContext(screenshot=screenshot, config=self.config)
        results: Dict[str, Any] = {}

        for stage in self.stages:
            # notify start
            self.on_progress(stage.name, 0.0, ctx)

            # execute stage
            stage_result = stage.run(
                ctx,
                lambda pct, name=stage.name: self.on_progress(name, pct, ctx)
            )
            # update context and results
            ctx = stage_result.context
            results[stage.name] = stage_result.output

            # notify completion
            self.on_progress(stage.name, 1.0, ctx)

            # on_stage_complete hook
            if self.on_stage_complete:
                self.on_stage_complete(stage.name, ctx, stage_result.output)

            # interactive hook
            if stage.interactive:
                ctx = self.on_interactive(stage.name, ctx)

        # on_pipeline_complete hook    
        if self.on_pipeline_complete:
            self.on_pipeline_complete(ctx, results)

        return ctx, results
    
def build_default_pipeline(
    on_progress: Callable[[str, float, PipelineContext], None],
    on_interactive: Callable[[str, PipelineContext], PipelineContext],
    on_stage_complete: Optional[Callable[[str, PipelineContext, Any], None]] = None,
    on_pipeline_complete: Optional[Callable[[PipelineContext, Dict[str, Any]], None] ] = None,
    config: Dict[str, Any] = {}
) -> SISTER:
    stages: List[Stage] = [
        LabelLocatorStage(config.get("locator", {})),
        ClassifierStage(config.get("classifier", {})),
        # RegionDetectionStage(config.get("region", {})),
        # IconSlotDetectionStage(config.get("iconslot", {})),
        # IconMatchingQualityDetectionStage(config.get("quality", {})),
        # IconMatchingPrefilterStage(config.get("prefilter", {})),
        # IconMatchingStage(
        #     workers=config.get("matching_workers", 8),
        #     opts=config.get("matching", {})
        # ),
    ]
    return SISTER(stages, on_progress, on_interactive, config=config, on_stage_complete=on_stage_complete, on_pipeline_complete=on_pipeline_complete)
