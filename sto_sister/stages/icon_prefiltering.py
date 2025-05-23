from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState

# from ..prefilter import IconPrefilter

from ..components.prefilter_phash import PHashEngine

STRATEGY_CLASSES = {
    "phash": PHashEngine,
    # "dhash": DHashEngine,
}


class IconPrefilteringStage(PipelineStage):
    name = "icon_prefiltering"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        hash_index = self.app_config.get("hash_index")
        method = self.opts["method"].lower()

        print(f"[Prefilter] Using method: {method}")

        try:
            self.strategy = STRATEGY_CLASSES[method](hash_index=hash_index)

            self.method = method
        except KeyError as e:
            raise ValueError(f"Unknown prefilter method: '{method}'") from e

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        icon_sets = ctx.app_config.get("icon_sets", {})
        icon_set = icon_sets[ctx.classification["icon_set"]]

        (
            ctx.predicted_icons,
            ctx.found_icons,
            ctx.filtered_icons,
        ) = self.strategy.icon_predictions(ctx.slots, icon_set)

        report(self.name, 1.0)
        return StageOutput(ctx, ctx.predicted_icons)
