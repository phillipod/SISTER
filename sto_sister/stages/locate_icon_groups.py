from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.icon_group_locator import IconGroupLocator


class LocateIconGroupsStage(PipelineStage):
    name = "locate_icon_groups"
    interactive = True  # allow UI confirmation

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.detector = IconGroupLocator(**opts)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, "Running", 0.0)

        # ctx.icon_groups = self.detector.locate_icon_groups(
        #     ctx.screenshot, ctx.labels, ctx.classification
        # )
        # Batch icon groups across screenshots
        # print("ctx.classification", ctx.classification)
        ctx.icon_groups_list = [
            self.detector.locate_icon_groups(img, labels, cls)
            for img, labels, cls in zip(ctx.screenshots, ctx.labels_list, ctx.classifications)
        ]
        # Merge all icon groups
        merged = {}
        for g in ctx.icon_groups_list:
            merged.update(g)

        ctx.icon_groups = merged

        # print("ctx.icon_groups", ctx.icon_groups)

        report(self.name, "Completed", 100.0)
        return StageOutput(ctx, ctx.icon_groups)
