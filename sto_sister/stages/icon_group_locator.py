from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.icon_group_locator import IconGroupLocator

class IconGroupLocatorStage(PipelineStage):
    name = "icon_group_locator"
    interactive = True  # allow UI confirmation

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.detector = IconGroupLocator(**opts)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        ctx.icon_groups = self.detector.locate_icon_groups(
            ctx.screenshot, ctx.labels, ctx.classification
        )

        report(self.name, 1.0)
        return StageOutput(ctx, ctx.icon_groups)