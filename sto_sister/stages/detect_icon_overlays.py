from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter
from ..components.icon_overlay_detector import IconOverlayDetector

from ..utils.image import apply_mask, load_overlays, show_image


class DetectIconOverlaysStage(PipelineStage):
    name = "detect_icon_overlays"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self._window_start = opts.get("progress_start", 0.10)
        self._window_end   = opts.get("progress_end",   0.90)

        self.strategy = IconOverlayDetector(
            hash_index=app_config.get("hash_index"),
            debug=opts.get("debug", False),
        )

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        progress_cb = StageProgressReporter(
            self.name,
            report,
            window_start = self._window_start,
            window_end   = self._window_end,
        )
        
        self.strategy.on_progress = progress_cb

        report(self.name, "Running", 0.0)

        overlays = load_overlays(ctx.config.get("overlay_dir", ""))

        ctx.detected_overlays = self.strategy.detect(
            ctx.slots,
            overlays,
            threshold=self.opts.get("threshold", 0.8),
        )
        report(self.name, "Completed", 100.0)
        return StageOutput(ctx, ctx.detected_overlays)
