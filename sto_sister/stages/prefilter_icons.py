from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState

# from ..prefilter import IconPrefilter

from ..components.prefilter_phash import PHashEngine

STRATEGY_CLASSES = {
    "phash": PHashEngine,
    # "dhash": DHashEngine,
}


class PrefilterIconsStage(PipelineStage):
    name = "prefilter_icons"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        hash_index = self.app_config.get("hash_index")
        method = self.opts["method"].lower()

        #print(f"[Prefilter] Using method: {method}")

        try:
            self.strategy = STRATEGY_CLASSES[method](hash_index=hash_index)

            self.method = method
        except KeyError as e:
            raise ValueError(f"Unknown prefilter method: '{method}'") from e

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:

        report(self.name, "Running", 0.0)

        icon_sets = ctx.app_config.get("icon_sets", {})

        # Batch prefilter calls
        triples = [
            self.strategy.prefilter(
                slots,
                cls,
                icon_sets
            )
            for slots, cls in zip(ctx.slots_list, ctx.classifications)
        ]

        # Unzip into three lists of dicts
        pre_list, found_list, filt_list = zip(*triples)

        # Merge 
        merged_pref = {}
        for d in pre_list:
            merged_pref.update(d)
        merged_found = {}
        for d in found_list:
            merged_found.update(d)
        merged_filt = {}
        for d in filt_list:
            merged_filt.update(d)

        ctx.prefiltered_icons = merged_pref
        ctx.found_icons       = merged_found
        ctx.filtered_icons    = merged_filt

        report(self.name, "Completed", 100.0)
        return StageOutput(ctx, ctx.prefiltered_icons)