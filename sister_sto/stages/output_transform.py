from typing import Any, Callable, Dict, List, Tuple, Optional
import logging

from ..pipeline import PipelineStage, StageOutput, PipelineState

logger = logging.getLogger(__name__)

class OutputTransformationStage(PipelineStage):
    name = "output_transformation"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.transformations_enabled_list = opts.get(
            "transformations_enabled_list", []
        )

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, "Running", 0.0)

        ctx.output = {
            "matches": ctx.matches,
            "prefiltered_icons": ctx.prefiltered_icons,
            "detected_overlays": ctx.detected_overlays,
            "transformations_applied": [],
        }

        
        if "BACKFILL_MATCHES_WITH_PREFILTERED" in self.transformations_enabled_list:
            # we're going to merge any prefiltered icons into ctx.matches if they don't already exist
            # this catches cases where we have prefiltered icons but no matches, so we at least provide some output that is hopefully useful
            matches = ctx.matches
            for icon_group_name in ctx.prefiltered_icons:
                #icon_group_name = icon_group
                for slot in ctx.prefiltered_icons[icon_group_name]:
                    slot_name = slot

                    # find any prefiltered icons for this icon group/slot
                    prefiltered = ctx.prefiltered_icons.get(icon_group_name, {}).get(
                        slot_name, []
                    )

                    # check current output for this icon group/slot
                    # print(f"icon_group_name: {icon_group_name}, slot_name: {slot_name} existing: {matches.get(icon_group_name, {}).get(slot_name, [])}")
                    existing = matches.get(icon_group_name, {}).get(slot_name, [])

                    # if prefiltering did fine candidates but ssim found no matches, copy over the prefiltered list so the user can see them as potentional matches
                    if prefiltered and len(existing) == 0:
                        # ensure the dicts exist
                        matches.setdefault(icon_group_name, {})[
                            slot_name
                        ] = prefiltered.copy()

                        # copy over the detected overlay if we have it
                        if ctx.detected_overlays[icon_group_name]:
                            for idx, item in enumerate(matches[icon_group_name][slot_name]):
                                matches[icon_group_name][slot_name][idx][
                                    "detected_overlay"
                                ] = ctx.detected_overlays[icon_group_name][slot_name]

        report(self.name, "Completed", 100.0)
        return StageOutput(ctx, ctx.output)
