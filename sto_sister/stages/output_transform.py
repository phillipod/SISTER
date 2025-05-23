from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState


class OutputTransformationStage(PipelineStage):
    name = "output_transformation"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        # start with whatever matches we already have
        ctx.output = {
            "matches": ctx.matches,
            "predicted_icons": ctx.predicted_icons,
            "detected_overlays": ctx.detected_overlays,
        }

        # we're going to merge any predicted icons into ctx.matches if they don't already exist
        # this catches cases where we have predicted icons but no matches, so we at least provide some output that is hopefully useful
        matches = ctx.matches
        for icon_group_name in ctx.predicted_icons:
            #icon_group_name = icon_group
            for slot in ctx.predicted_icons[icon_group_name]:
                slot_name = slot

                # find any predicted icons for this icon group/slot
                predicted = ctx.predicted_icons.get(icon_group_name, {}).get(
                    slot_name, []
                )

                # check current output for this icon group/slot
                # print(f"icon_group_name: {icon_group_name}, slot_name: {slot_name} existing: {matches.get(icon_group_name, {}).get(slot_name, [])}")
                existing = matches.get(icon_group_name, {}).get(slot_name, [])

                # if there's a prediction and no existing match, copy it over
                if predicted and len(existing) == 0:
                    # ensure the dicts exist
                    matches.setdefault(icon_group_name, {})[
                        slot_name
                    ] = predicted.copy()

                    # copy over the predicted quality if we have it
                    if ctx.detected_overlays[icon_group_name]:
                        for idx, item in enumerate(matches[icon_group_name][slot_name]):
                            matches[icon_group_name][slot_name][idx][
                                "detected_overlay"
                            ] = ctx.detected_overlays[icon_group_name][slot_name]

        report(self.name, 1.0)
        return StageOutput(ctx, ctx.output)
