from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.icon_slot_locator import IconSlotLocator


class LocateIconSlotsStage(PipelineStage):
    name = "locate_icon_slots"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.opts["hash_index"] = self.app_config.get("hash_index")

        self.slot_locator = IconSlotLocator(**self.opts)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        # ctx.slots = self.slot_locator.locate_slots(ctx.screenshot, ctx.icon_groups)
        ctx.slots_list = [
            self.slot_locator.locate_slots(img, ig)
            for img, ig in zip(ctx.screenshots, ctx.icon_groups_list)
        ]

        # Merge all slots per group
        merged = {}
        for slots in ctx.slots_list:
            for label, data in slots.items():
                merged.setdefault(label, []).extend(data)

        ctx.slots = merged

        report(self.name, 1.0)
        return StageOutput(ctx, ctx.slots)
