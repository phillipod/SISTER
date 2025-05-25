from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.label_locator import LabelLocator


class LocateLabelsStage(PipelineStage):
    name = "locate_labels"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.label_locator = LabelLocator(**opts)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, "Running", 0.0)

        ctx.labels_list = [
            self.label_locator.locate_labels(image)
            for image in ctx.screenshots
        ]
        
        report(self.name, "Completed", 100.0)
        return StageOutput(ctx, ctx.labels_list)
