from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import Stage, StageResult, PipelineContext
from ..iconslot import IconSlotDetector

class IconSlotDetectionStage(Stage):
    name = "iconslot_detection"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)

        self.opts["hash_index"] = self.app_config.get("hash_index")

        self.slot_detector = IconSlotDetector(**self.opts)

    def run(
        self, ctx: PipelineContext, report: Callable[[str, float], None]
    ) -> StageResult:
        report(self.name, 0.0)

        ctx.slots = self.slot_detector.detect_slots(ctx.screenshot, ctx.regions)

        report(self.name, 1.0)
        return StageResult(ctx, ctx.slots)
