from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import Stage, StageResult, PipelineContext
from ..components.icon_matcher import IconMatcher

class IconMatchingStage(Stage):
    name = "icon_matching"

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
        icon_sets = ctx.app_config.get("icon_sets", {})
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