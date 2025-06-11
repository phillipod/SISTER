from typing import Any, Callable, Dict, List, Tuple, Optional
import logging

from ..pipeline.core import PipelineStage, StageOutput, PipelineState

logger = logging.getLogger(__name__)

class OutputTransformationStage(PipelineStage):
    name = "output_transformation"
    dependencies = ["detect_icons"]

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.transformations_enabled_list = opts.get(
            "transformations_enabled_list", []
        )

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, "Running", 0.0)

        # Initialize output structure with default empty values
        ctx.output = {
            "matches": ctx.matches if hasattr(ctx, 'matches') else {},
            "prefiltered_icons": ctx.prefiltered_icons if hasattr(ctx, 'prefiltered_icons') else {},
            "detected_overlays": ctx.detected_overlays if hasattr(ctx, 'detected_overlays') else {},
            "build_type": ctx.classification.get("build_type") if hasattr(ctx, 'classification') and ctx.classification else None,
            "transformations_applied": [],
        }

        # Ensure matches exists and is a dictionary
        if not isinstance(ctx.output["matches"], dict):
            ctx.output["matches"] = {}
        
        if "BACKFILL_MATCHES_WITH_PREFILTERED" in self.transformations_enabled_list:
            # we're going to merge any prefiltered icons into ctx.matches if they don't already exist
            # this catches cases where we have prefiltered icons but no matches, so we at least provide some output that is hopefully useful
            matches = ctx.output["matches"]  # Use the output structure's matches
            prefiltered = ctx.output["prefiltered_icons"]
            detected_overlays = ctx.output["detected_overlays"]

            for icon_group_name, group_data in prefiltered.items():
                for slot_name, slot_data in group_data.items():
                    # check current output for this icon group/slot
                    existing = matches.get(icon_group_name, {}).get(slot_name, [])

                    # if prefiltering found candidates but ssim found no matches, copy over the prefiltered list
                    if slot_data and len(existing) == 0:
                        # ensure the dicts exist
                        matches.setdefault(icon_group_name, {})[slot_name] = slot_data.copy()

                        # copy over the detected overlay if we have it
                        if detected_overlays.get(icon_group_name):
                            overlay_data = detected_overlays[icon_group_name].get(slot_name)
                            if overlay_data:
                                for idx, item in enumerate(matches[icon_group_name][slot_name]):
                                    matches[icon_group_name][slot_name][idx]["detected_overlay"] = overlay_data

            ctx.output["transformations_applied"].append("BACKFILL_MATCHES_WITH_PREFILTERED")

        report(self.name, "Completed", 100.0)
        return StageOutput(ctx, ctx.output)
