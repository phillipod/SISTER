from typing import Any, Callable, Dict, List, Tuple, Optional
import logging

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.label_locator import LabelLocator
from ..pipeline.progress_reporter import StageProgressReporter

logger = logging.getLogger(__name__)

class LocateLabelsStage(PipelineStage):
    name = "locate_labels"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        # no on_progress here yet—they get built per-image
        self.label_locator = LabelLocator(**opts)

    def process(
        self, 
        ctx: PipelineState, 
        report: Callable[[str, str, float], None]
    ) -> StageOutput:
        screenshots = ctx.screenshots
        screenshots_count = len(screenshots)
        labels_list = []

        for i, image in enumerate(screenshots):
            # carve out [i/screenshots_count ... (i+1)/screenshots_count] of the 0–100% range
            start_frac = i / screenshots_count
            end_frac   = (i + 1) / screenshots_count

            sub = f"Screenshot {i+1}/{screenshots_count}"

            reporter = StageProgressReporter(
                stage_name    = self.name,
                sub_prefix    = sub,
                report_fn     = report,
                window_start  = start_frac,
                window_end    = end_frac,
            )

            reporter(sub, 0.0)

            labels = self.label_locator.locate_labels(
                image,
                on_progress=reporter
            )

            reporter(sub, 100.0)

            labels_list.append(labels)

        report(self.name, f"Completed - Found {sum(len(label) for label in labels_list)} labels", 100.0)
        ctx.labels_list = labels_list
        return StageOutput(ctx, labels_list)
