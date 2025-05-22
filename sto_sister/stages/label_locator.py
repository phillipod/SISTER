from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.label_locator import LabelLocator

class LabelLocatorStage(PipelineStage):
    name = "label_locator"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.locator = LabelLocator(**opts)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)
        ctx.labels = self.locator.locate(ctx.screenshot)
        report(self.name, 1.0)
        return StageOutput(ctx, ctx.labels)
