import cv2
import numpy as np

from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter

from ..utils.persistent_executor import PersistentProcessPoolExecutor

def _dummy_job(i):
    # no-op work; could also do time.sleep(0) or something trivial
    return i

class LoadIconsStage(PipelineStage):
    name = "load_icons"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)


    def process(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> StageOutput:
        report(self.name, "Loading icons", 0.0)

        unique_files = {}
        slot_file_pair_count = 0

        ctx.loaded_icons = {}

        for icon_group in ctx.found_icons:
            ctx.loaded_icons[icon_group] = {}

            for slot in ctx.found_icons[icon_group]:
                for file in ctx.found_icons[icon_group][slot]:
                    if file not in ctx.loaded_icons[icon_group]:
                            full_path = ctx.app_config.get("hash_index").base_dir / file
                            data = np.fromfile(str(full_path), dtype=np.uint8)
                            icon = cv2.imdecode(data, cv2.IMREAD_COLOR)
                            
                            if icon is not None:
                                # Ensure icon is 49x64
                                if icon.shape[0] != 64 or icon.shape[1] != 49:
                                    icon = cv2.resize(icon, (49, 64))                                
                    
                                ctx.loaded_icons[icon_group][file] = icon
                    
        #print(f"Loaded icons: {ctx.loaded_icons}")

        report(self.name, "Complete", 100.0)

        return StageOutput(ctx, ctx.loaded_icons)
