from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.icon_overlay_detector import IconOverlayDetector

from ..utils.image import apply_mask, load_overlays, show_image


class IconOverlayDetectorStage(PipelineStage):
    name = "icon_overlay_detector"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.strategy = IconOverlayDetector(
            hash_index=app_config.get("hash_index"),
            debug=opts.get("debug", False),
        )

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        overlays = load_overlays(ctx.config.get("overlay_dir", ""))

        ctx.detected_overlays = self.strategy.quality_predictions(
            ctx.slots,
            overlays,
            threshold=self.opts.get("threshold", 0.8),
        )
        report(self.name, 1.0)
        return StageOutput(ctx, ctx.detected_overlays)
