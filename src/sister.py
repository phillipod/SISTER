from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional
import numpy as np

# --- Import your existing modules (adjust names as needed) ---
from src.locator import LabelLocator
from src.classifier import Classifier
from src.region import RegionDetector
from src.iconslot import IconSlotDetector
from src.iconmatch import IconMatcher
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

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> StageResult:
        report(self.name, 0.0)
        ctx.labels = self.locator.locate(ctx.screenshot)
        report(self.name, 1.0)
        return StageResult(ctx, ctx.labels)


class ClassifierStage(Stage):
    name = "classifier"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.classifier = Classifier(**opts)

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> StageResult:
        report(self.name, 0.0)
        ctx.classification = self.classifier.classify(ctx.labels)

        if ctx.classification['build_type'] == 'PC Ship Build' or ctx.classification['build_type'] == 'Console Ship Build':
            ctx.classification['icon_set'] = 'ship'
        
        elif ctx.classification['build_type'] == 'PC Ground Build':
            ctx.classification['icon_set'] = 'pc_ground'

        elif ctx.classification['build_type'] == 'Console Ground Build':
            ctx.classification['icon_set'] = 'console_ground'


        report(self.name, 1.0)
        return StageResult(ctx, ctx.classification)


class RegionDetectionStage(Stage):
    name = "region_detection"
    interactive = True  # allow UI confirmation

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.detector = RegionDetector(**opts)

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> StageResult:
        report(self.name, 0.0)
        ctx.regions = self.detector.detect_regions(ctx.screenshot, ctx.labels, ctx.classification)
        report(self.name, 1.0)
        return StageResult(ctx, ctx.regions)


class IconSlotDetectionStage(Stage):
    name = "iconslot_detection"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.slot_detector = IconSlotDetector(**opts)

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> StageResult:
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
            engine_type=opts.get("engine_type", "ssim")
        )

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> StageResult:
        report(self.name, 0.0)
        icon_dir_map = ctx.config.get("icon_dirs", {})
        overlays = self.matcher.load_quality_overlays(ctx.config.get("overlay_dir", ""))
        ctx.predicted_qualities = self.matcher.quality_predictions(
            ctx.screenshot,
            ctx.classification,
            ctx.slots,
            icon_dir_map,
            overlays,
            threshold=self.opts.get("threshold", 0.8)
        )
        report(self.name, 1.0)
        return StageResult(ctx, ctx.predicted_qualities)


class IconMatchingPrefilterStage(Stage):
    name = "icon_prefilter"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts

        hash_index = HashIndex(opts.get("hash_index_dir"), "phash", output_file=opts.get("hash_index_file", "hash_index.json"))
        
        self.matcher = IconMatcher(
            hash_index=hash_index,
            debug=opts.get("debug", False),
            engine_type=opts.get("engine_type", "ssim")
        )

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> StageResult:
        report(self.name, 0.0)
        icon_sets = ctx.config.get("icon_sets", {})
        overlays = self.matcher.load_quality_overlays(ctx.config.get("overlay_folder", ""))
        #print(f"[Prefilter] Icon sets: {icon_sets}")
        #print(f"[Prefilter] Overlays: {overlays}")
        
        ctx.predicted_icons = self.matcher.icon_predictions(
            ctx.screenshot,
            ctx.classification,
            ctx.slots,
            icon_sets,
            overlays,
            threshold=self.opts.get("threshold", 0.8)
        )
        ctx.found_icons = self.matcher.found_icons
        ctx.filtered_icons = self.matcher.filtered_icons

        #print(f"[Prefilter] Found icons: {ctx.found_icons}")
        #print(f"[Prefilter] Filtered icons: {ctx.filtered_icons}")
        report(self.name, 1.0)
        return StageResult(ctx, ctx.predicted_icons)


class IconMatchingStage(Stage):
    name = "icon_matching"

    def __init__(self, opts: Dict[str, Any]):
        self.opts = opts
        self.matcher = IconMatcher(
            hash_index=opts.get("hash_index"),
            debug=opts.get("debug", False),
            engine_type=opts.get("engine_type", "ssim")
        )

    def run(self, ctx: PipelineContext, report: Callable[[str, float], None]) -> StageResult:
        report(self.name, 0.0)
        icon_dir_map = ctx.config.get("icon_dirs", {})
        overlays = self.matcher.load_quality_overlays(ctx.config.get("overlay_folder", ""))
        matches = self.matcher.match_all(
            ctx.screenshot,
            ctx.classification,
            ctx.slots,
            icon_dir_map,
            overlays,
            threshold=self.opts.get("threshold", 0.8)
        )
        report(self.name, 1.0)
        return StageResult(ctx, matches)


# --- The Pipeline Orchestrator ---
class SISTER:
    def __init__(
        self,
        stages: List[Stage],
        on_progress: Callable[[str, float, PipelineContext], None],
        on_interactive: Callable[[str, PipelineContext], PipelineContext],
        config: Dict[str, Any],
        on_stage_complete: Optional[Callable[[str, PipelineContext, Any], None]] = None,
        on_pipeline_complete: Optional[Callable[[PipelineContext, Dict[str, Any]], None]] = None
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
    on_pipeline_complete: Optional[Callable[[PipelineContext, Dict[str, Any]], None]] = None,
    config: Dict[str, Any] = {}
) -> SISTER:
    stages: List[Stage] = [
        LabelLocatorStage(config.get("locator", {"debug": True})),
        ClassifierStage(config.get("classifier", {})),
        RegionDetectionStage(config.get("region", {})),
        IconSlotDetectionStage(config.get("iconslot", {})),
        IconMatchingPrefilterStage(config.get("prefilter", { "debug": True})),
        #IconMatchingQualityDetectionStage(config.get("quality", {})),
        #IconMatchingStage(config.get("matching", {})),
    ]
    return SISTER(
        stages,
        on_progress,
        on_interactive,
        config=config,
        on_stage_complete=on_stage_complete,
        on_pipeline_complete=on_pipeline_complete
    )
