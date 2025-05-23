from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..utils.image import apply_mask, load_overlays, show_image
from ..components.icon_matcher import IconMatcher


class IconMatchingStage(PipelineStage):
    name = "icon_matching"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.matcher = IconMatcher(
            debug=opts.get("debug", False),
        )

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        icon_sets = ctx.app_config.get("icon_sets", {})
        ctx.overlays = load_overlays(ctx.config.get("overlay_dir", ""))
        # print(f"[Matching] ctx.filtered_icons: {ctx.filtered_icons}")
        ctx.matches = self.matcher.match_all(
            ctx.slots,
            icon_sets,
            ctx.overlays,
            ctx.detected_overlays,
            ctx.filtered_icons,
            ctx.found_icons,
            threshold=self.opts.get("threshold", 0.7),
        )
        report(self.name, 1.0)
        return StageOutput(ctx, ctx.matches)
