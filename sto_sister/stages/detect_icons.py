from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter
from ..utils.image import apply_mask, load_overlays, show_image
from ..components.icon_detector import IconDetector


class DetectIconsStage(PipelineStage):
    name = "detect_icons"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        # specify scaling window (0.10 = 10%, 0.90 = 90%)
        self._window_start = opts.get("progress_start", 0.10)
        self._window_end   = opts.get("progress_end",   0.90)

        self.detector = IconDetector(
            debug=opts.get("debug", False),
            executor_pool=app_config["executor_pool"]
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
        
        self.detector.on_progress = progress_cb

        report(self.name, "Starting", 0.0)

        icon_sets = ctx.app_config.get("icon_sets", {})
        ctx.overlays = load_overlays(ctx.config.get("overlay_dir", ""))
        # print(f"[Matching] ctx.filtered_icons: {ctx.filtered_icons}")
        ctx.matches = self.detector.detect(
            ctx.slots,
            icon_sets,
            ctx.overlays,
            ctx.detected_overlays,
            ctx.filtered_icons,
            ctx.found_icons,
            threshold=self.opts.get("threshold", 0.7),
        )
        report(self.name, f"Completed - Matched {sum(1 for icon_group_dict in ctx.matches.values() for slot_items in icon_group_dict.values() for item in slot_items)} icons", 100.0)
        return StageOutput(ctx, ctx.matches)

    def _make_detector_progress(self):
        # capture stage name & window
        def detector_progress(substage: str, pct: float):
            # pct is 0–100 from IconDetector
            frac = pct / 100.0
            # linear interpolate into [start...end]
            window_frac = self._window_start + (self._window_end - self._window_start) * frac
            # back to 0–100 scale
            scaled_pct = window_frac * 100.0
            # re-emit with full signature
            return report(self.name, substage, scaled_pct)
        return detector_progress