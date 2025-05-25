from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter
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
        method     = self.opts["method"].lower()
        try:
            self.strategy = STRATEGY_CLASSES[method](hash_index=hash_index)
            self.method   = method
        except KeyError as e:
            raise ValueError(f"Unknown prefilter method: '{method}'") from e

    def process(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> StageOutput:
        screenshots_count = len(ctx.slots_list)
        pre_list   = []
        found_list = []
        filt_list  = []

        for i, (slots, cls) in enumerate(zip(ctx.slots_list, ctx.classifications)):
            # carve out [i/screenshots_count ... (i+1)/screenshots_count] of the 0–100% range
            start_frac = i / screenshots_count
            end_frac   = (i + 1) / screenshots_count

            sub = f"Screenshot {i+1}/{screenshots_count}"

            reporter = StageProgressReporter(
                stage_name   = self.name,
                sub_prefix   = sub,
                report_fn    = report,
                window_start = start_frac,
                window_end   = end_frac,
            )

            reporter("Running", 0.0)

            pre, found, filt = self.strategy.prefilter(
                slots,
                cls,
                ctx.app_config.get("icon_sets", {}),
                on_progress=reporter
            )

            reporter("Completed", 100.0)

            pre_list.append(pre)
            found_list.append(found)
            filt_list.append(filt)

        # 3) Merge results across all screenshots
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

        # 4) Final stage completion
        report(
            self.name,
            f"Completed – Found {sum(len(slots) for icon_group in merged_pref.values() for slots in icon_group.values())} potential matches",
            100.0
        )
        return StageOutput(ctx, merged_pref)
