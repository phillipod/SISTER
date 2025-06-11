from typing import Any, Callable, Dict, List, Tuple, Optional
from pathlib import Path
import logging

from ..pipeline.core import PipelineTask, TaskOutput, PipelineState
from ..pipeline.progress_reporter import TaskProgressReporter

from ..utils.hashindex import HashIndex
from ..utils.image import load_overlays

logger = logging.getLogger(__name__)

class BuildHashCacheTask(PipelineTask):
    name = "build_hash_cache"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)


    def execute(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> TaskOutput:
        report(self.name, "Building hash cache", 0.0)
        
        ctx.hashed_items = self.build_hash_cache(report)
        
        report(self.name, "Downloaded all icons", 100.0)

        return TaskOutput(ctx, ctx.hashed_items)


    def build_hash_cache(self, report: Callable[[str, str, float], None]):

        icon_root = Path(self.app_config["icon_dir"])
        cache_dir = Path(self.app_config["cache_dir"])
        
        hash_index = HashIndex(icon_root, cache_dir, match_size=(16, 16), empty=True)
        
        overlays = load_overlays(self.app_config["overlay_dir"])  # Must return dict of overlay -> RGBA overlay np.array
        
        reporter = TaskProgressReporter(
            task_name   = self.name,
            report_fn    = report,
            window_start = 0.0,
            window_end   = 1.0,
        )

        hash_index.build_with_overlays(overlays, on_progress=reporter)

        return len(hash_index.hashes)
