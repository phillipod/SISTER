from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.layout_classifier import LayoutClassifier

class ClassifierStage(PipelineStage):
    name = "classifier"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.classifier = LayoutClassifier(**opts)

    def run(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)
        ctx.classification = self.classifier.classify(ctx.labels)

        if (
            ctx.classification["build_type"] == "PC Ship Build"
            or ctx.classification["build_type"] == "Console Ship Build"
        ):
            ctx.classification["icon_set"] = "ship"

        elif ctx.classification["build_type"] == "PC Ground Build":
            ctx.classification["icon_set"] = "pc_ground"

        elif ctx.classification["build_type"] == "Console Ground Build":
            ctx.classification["icon_set"] = "console_ground"

        report(self.name, 1.0)
        return StageOutput(ctx, ctx.classification)
