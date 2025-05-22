from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.icon_slot_detector import IconSlotDetector


class IconSlotDetectionStage(PipelineStage):
    name = "iconslot_detection"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.opts["hash_index"] = self.app_config.get("hash_index")

        self.slot_detector = IconSlotDetector(**self.opts)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        ctx.slots = self.slot_detector.detect_slots(ctx.screenshot, ctx.icon_groups)

        report(self.name, 1.0)
        return StageOutput(ctx, ctx.slots)
