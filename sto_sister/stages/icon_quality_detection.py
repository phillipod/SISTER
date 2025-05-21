from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import Stage, StageResult, PipelineContext
from ..components.icon_matcher import IconMatcher

class IconMatchingQualityDetectionStage(Stage):
    name = "icon_quality_detection"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.matcher = IconMatcher(
            hash_index=app_config.get("hash_index"),
            debug=opts.get("debug", False),
            engine_type=opts.get("engine_type", "ssim"),
        )

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        overlays = self.matcher.load_quality_overlays(ctx.config.get("overlay_dir", ""))

        ctx.predicted_qualities = self.matcher.quality_predictions(
            ctx.slots,
            overlays,
            threshold=self.opts.get("threshold", 0.8),
        )
        report(self.name, 1.0)
        return StageResult(ctx, ctx.predicted_qualities)