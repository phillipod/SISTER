from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import Stage, StageResult, PipelineContext

class OutputTransformationStage(Stage):
    name = "output_transformation"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        # start with whatever matches we already have
        ctx.output = {
            "matches": ctx.matches,
            "predicted_icons": ctx.predicted_icons,
            "predicted_qualities": ctx.predicted_qualities,
        }

        # we're going to merge any predicted icons into ctx.matches if they don't already exist
        # this catches cases where we have predicted icons but no matches, so we at least provide some output that is hopefully useful
        matches = ctx.matches
        for region in ctx.predicted_icons:
            region_name = region
            for slot in ctx.predicted_icons[region]:
                slot_name = slot

                # find any predicted icons for this region/slot
                predicted = ctx.predicted_icons.get(region_name, {}).get(slot_name, [])

                # check current output for this region/slot
                # print(f"region_name: {region_name}, slot_name: {slot_name} existing: {matches.get(region_name, {}).get(slot_name, [])}")
                existing = matches.get(region_name, {}).get(slot_name, [])

                # if there's a prediction and no existing match, copy it over
                if predicted and len(existing) == 0:
                    # ensure the dicts exist
                    matches.setdefault(region_name, {})[slot_name] = predicted.copy()

                    # copy over the predicted quality if we have it
                    if ctx.predicted_qualities[region_name]:
                        for idx, item in enumerate(matches[region_name][slot_name]):
                            matches[region_name][slot_name][idx][
                                "predicted_quality"
                            ] = ctx.predicted_qualities[region_name][slot_name]

        report(self.name, 1.0)
        return StageResult(ctx, ctx.output)