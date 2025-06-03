from typing import Any, Callable, Dict, List, Tuple, Optional
import logging

from ..pipeline.core import PipelineStage, StageOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter

from ..components.icon_group_locator import IconGroupLocator

logger = logging.getLogger(__name__)

class LocateIconGroupsStage(PipelineStage):
    name = "locate_icon_groups"
    interactive = True  # allow UI confirmation. Unimplemented.

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.detector = IconGroupLocator(**opts)

    def process(
        self, 
        ctx: PipelineState, 
        report: Callable[[str, str, float], None]
    ) -> StageOutput:
        screenshots      = ctx.screenshots
        labels_list      = ctx.labels_list
        classifications  = ctx.classifications
        screenshots_count = len(screenshots)

        # Hold per-image results
        icon_groups_list = []

        for i, (img, labels, cls) in enumerate(zip(screenshots, labels_list, classifications)):
            # carve out [i/screenshots_count ... (i+1)/screenshots_count] of the 0–100% range
            start_frac = i / screenshots_count
            end_frac   = (i + 1) / screenshots_count

            sub = f"Screenshot {i+1}/{screenshots_count}"

            reporter = StageProgressReporter(
                stage_name   = self.name,
                sub_prefix   = sub,
                report_fn    = report,
                window_start = start_frac,
                window_end   = end_frac,
            )

            reporter(sub, 0.0)

            # Pass the labels with ROI data to locate_icon_groups
            groups = self.detector.locate_icon_groups(
                img, 
                labels, 
                cls, 
                #on_progress=reporter
            )

            reporter(sub, 100.0)
            icon_groups_list.append(groups)

        # merge all icon_group dicts while preserving the full structure
        merged = {}
        for groups in icon_groups_list:
            merged.update(groups)

        ctx.icon_groups_list = icon_groups_list
        ctx.icon_groups      = merged

        # final stage completion
        report(
            self.name,
            f"Completed – Found {len(merged)} icon groups",
            100.0
        )
        return StageOutput(ctx, merged)