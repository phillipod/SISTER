from typing import Any, Callable, Dict, List, Tuple, Optional
import logging

from ..pipeline.core import PipelineStage, StageOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter

from ..components.icon_slot_locator import IconSlotLocator

logger = logging.getLogger(__name__)

class LocateIconSlotsStage(PipelineStage):
    name = "locate_icon_slots"
    dependencies = ["locate_icon_groups", "classify_layout"]

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.opts["hash_index"] = self.app_config.get("hash_index")

        self.slot_locator = IconSlotLocator(**self.opts)

    def process(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> StageOutput:
        screenshots      = ctx.screenshots
        icon_groups_list = ctx.icon_groups_list
        screenshots_count            = len(screenshots)
        slots_list       = []

        for i, (img, ig) in enumerate(zip(screenshots, icon_groups_list)):
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

            reporter(sub, 0.0)

            slots = self.slot_locator.locate_slots(
                img,
                ig,
                #on_progress=reporter
            )

            reporter(sub, 100.0)
            slots_list.append(slots)

        # merge all slots across screenshots
        merged = {}
        for slots in slots_list:
            for label, items in slots.items():
                merged.setdefault(label, []).extend(items)

        ctx.slots_list = slots_list
        ctx.slots      = merged

        # final stage completion
        report(
            self.name,
            f"Completed – Found {sum(len(v) for v in merged.values())} icon slots",
            100.0
        )
        return StageOutput(ctx, merged)
