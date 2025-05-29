from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineTask, TaskOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter

class DownloadAllIconsTask(PipelineTask):
    name = "download_all_icons"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)


    def execute(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> TaskOutput:
        report(self.name, "Downloading all icons", 0.0)
        
        print("Task: Downloading all icons")


        report(self.name, "Downloaded all icons", 100.0)

        return TaskOutput(ctx, None)
