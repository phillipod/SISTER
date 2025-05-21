from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import Stage, StageResult, PipelineContext
from ..prefilter import IconPrefilter

class IconPrefilterStage(Stage):
    name = "icon_prefilter"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.opts["hash_index"] = self.app_config.get("hash_index")

        self.prefilterer = IconPrefilter(**self.opts)

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        icon_sets = ctx.app_config.get("icon_sets", {})
        icon_set = icon_sets[ctx.classification["icon_set"]]

        ctx.predicted_icons = self.prefilterer.icon_predictions(ctx.slots, icon_set)
        ctx.found_icons = self.prefilterer.found_icons
        ctx.filtered_icons = self.prefilterer.filtered_icons

        report(self.name, 1.0)
        return StageResult(ctx, ctx.predicted_icons)

