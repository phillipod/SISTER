import cv2
import numpy as np
import logging

from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..pipeline.progress_reporter import StageProgressReporter

from ..utils.cargo import CargoDownloader
from ..utils.persistent_executor import PersistentProcessPoolExecutor

logger = logging.getLogger(__name__)

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

        start_pct = 1.0
        end_pct   = 90.0

        download_icons = {}
        for icon_group in ctx.found_icons:
            for slot in ctx.found_icons[icon_group]:
                for file in ctx.found_icons[icon_group][slot]:
                    for metadata in ctx.found_icons[icon_group][slot][file]['metadata']:
                        full_path = ctx.app_config.get("icon_dir") / metadata['image_path']

                        if full_path.exists():
                             continue

                        destination_dir = metadata['image_category']
                        cargo_item_name = metadata['cargo_item_name']
                        cargo_type = metadata['cargo_type']

                        if cargo_type not in download_icons:
                            download_icons[cargo_type] = {}

                        if destination_dir not in download_icons[cargo_type]:
                            download_icons[cargo_type][destination_dir] = {}

                        cargo_filters = tuple(sorted(metadata['cargo_filters'].items()))
                        if cargo_filters not in download_icons[cargo_type][destination_dir]:
                            download_icons[cargo_type][destination_dir][cargo_filters] = metadata['cargo_filters'].copy()
                            download_icons[cargo_type][destination_dir][cargo_filters]['name'] = []

                        download_icons[cargo_type][destination_dir][cargo_filters]['name'].append(cargo_item_name)                      

                
        downloader = CargoDownloader(cache_dir=ctx.app_config.get("cargo_dir"))
        downloader.download_all()

        image_cache_path = ctx.app_config.get("cache_dir") / "image_cache.json"

        total_cargo_filters = (sum(len(download_icons[cargo_type][destination_dir]) for cargo_type in download_icons for destination_dir in download_icons[cargo_type]))

        cargo_filters_processed = 0
        final_frac = 0
        for cargo_type in download_icons:
            for destination_dir in download_icons[cargo_type]:
                for cargo_filters in download_icons[cargo_type][destination_dir]:
                    start_frac = cargo_filters_processed / (total_cargo_filters+1)
                    end_frac   = (cargo_filters_processed + 1) / (total_cargo_filters+1)
                    final_frac = end_frac
                    sub = f"[{cargo_filters_processed+1}/{total_cargo_filters}] {destination_dir}"

                    reporter = StageProgressReporter(
                        stage_name   = self.name,
                        sub_prefix   = sub,
                        report_fn    = report,
                        window_start = start_frac,
                        window_end   = end_frac,
                    )

                    cargo_filter = download_icons[cargo_type][destination_dir][cargo_filters]
                    dest_dir = ctx.app_config.get("icon_dir") / destination_dir

                    downloader.download_icons(cargo_type, dest_dir, image_cache_path, cargo_filter, on_progress=reporter)
                    
                    cargo_filters_processed += 1
                    

        ctx.loaded_icons = {}

        sub = f"Loading icons"

        reporter = StageProgressReporter(
                stage_name   = self.name,
                sub_prefix   = sub,
                report_fn    = report,
                window_start = final_frac,
                window_end   = 1,
            )

        reporter("Loading icons", 0.0)
        for icon_group in ctx.found_icons:
            ctx.loaded_icons[icon_group] = {}

            for slot in ctx.found_icons[icon_group]:
                for file in ctx.found_icons[icon_group][slot]:
                    if file not in ctx.loaded_icons[icon_group]:
                            # print(f"{icon_group}#{slot} {file}: {ctx.found_icons[icon_group][slot][file]}")

                            full_path = ctx.app_config.get("icon_dir") / file
                            data = np.fromfile(str(full_path), dtype=np.uint8)
                            icon = cv2.imdecode(data, cv2.IMREAD_COLOR)
                            
                            if icon is not None:
                                # Ensure icon is 49x64
                                if icon.shape[0] != 64 or icon.shape[1] != 49:
                                    icon = cv2.resize(icon, (49, 64))                                
                    
                                ctx.loaded_icons[icon_group][file] = icon
                    
        #print(f"Loaded icons: {ctx.loaded_icons}")

        reporter("Complete", 100.0)

        return StageOutput(ctx, ctx.loaded_icons)
