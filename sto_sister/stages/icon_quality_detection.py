from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.overlay_detector import OverlayDetector

from ..utils.image import apply_mask, load_quality_overlays, show_image


class IconMatchingQualityDetectionStage(PipelineStage):
    name = "icon_quality_detection"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.strategy = OverlayDetector(
            hash_index=app_config.get("hash_index"),
            debug=opts.get("debug", False),
        )

    def run(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        overlays = load_quality_overlays(ctx.config.get("overlay_dir", ""))

        ctx.predicted_qualities = self.strategy.quality_predictions(
            ctx.slots,
            overlays,
            threshold=self.opts.get("threshold", 0.8),
        )
        report(self.name, 1.0)
        return StageOutput(ctx, ctx.predicted_qualities)