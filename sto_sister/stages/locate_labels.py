from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.label_locator import LabelLocator
from ..pipeline.progress_reporter import StageProgressReporter

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
        total       = len(screenshots)
        labels_list = []

        for i, image in enumerate(screenshots):
            # 1) compute this image’s [start…end] fraction in [0…1]
            start_frac = i / total
            end_frac   = (i + 1) / total

            # 2) build a reporter that maps 0–100→[start_frac…end_frac]
            reporter = StageProgressReporter(
                stage_name    = self.name,
                report_fn     = report,
                window_start  = start_frac,
                window_end    = end_frac,
            )

            # 3) give a little substage name so you see "Screenshot 2/3" in the bar
            sub = f"Screenshot {i+1}/{total}"
            reporter(sub, 0.0)

            # 4) run your locator (assuming you’ve updated locate_labels
            #    to accept an on_progress callback)
            labels = self.label_locator.locate_labels(
                image,
                on_progress=reporter
            )

            # 5) ensure this slice ends at 100%
            reporter(sub, 100.0)

            labels_list.append(labels)

        # finally, the stage itself is done
        report(self.name, f"Completed - Found {sum(len(label) for label in labels_list)} labels", 100.0)
        ctx.labels_list = labels_list
        return StageOutput(ctx, labels_list)


# class LocateLabelsStage(PipelineStage):
#     name = "locate_labels"

#     def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
#         super().__init__(opts, app_config)
#         self.label_locator = LabelLocator(**opts)

#     def process(
#         self, ctx: PipelineState, report: Callable[[str, float], None]
#     ) -> StageOutput:
#         report(self.name, "Running", 0.0)

#         ctx.labels_list = [
#             self.label_locator.locate_labels(image)
#             for image in ctx.screenshots
#         ]
        
#         report(self.name, "Completed", 100.0)
#         return StageOutput(ctx, ctx.labels_list)
