from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import Stage, StageResult, PipelineContext
from ..region import RegionDetector

class RegionDetectionStage(Stage):
    name = "region_detection"
    interactive = True  # allow UI confirmation

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
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