from typing import Any, Callable, Dict, List, Tuple, Optional
from pathlib import Path
import logging

from ..pipeline.core import PipelineTask, TaskOutput, PipelineState
from ..pipeline.progress_reporter import TaskProgressReporter

from ..utils.cargo import CargoDownloader

logger = logging.getLogger(__name__)

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
        
        self.download_icons(report)

        report(self.name, "Downloaded all icons", 100.0)

        return TaskOutput(ctx, None)

    def download_icons(self, report: Callable[[str, str, float], None]):
        """
        Download all icons for equipment, personal traits, and starship traits from STO wiki.
        
        This function is a wrapper around CargoDownloader, which is used to download icons.
        The mappings from cargo types to subdirectories are hardcoded.
        """
        images_root = Path(self.app_config["icon_dir"])
        image_cache_path = images_root / "image_cache.json"

        downloader = CargoDownloader()
        downloader.download_all()

        # Define all mappings as a list of tuples: (cargo_type, filters, subdirectory)
        download_mappings = [
            # Equipment types
            ('equipment', {'type': 'Body Armor'}, 'ground/armor'),
            ('equipment', {'type': 'Personal Shield'}, 'ground/shield'),
            ('equipment', {'type': 'EV Suit'}, 'ground/ev_suit'),
            ('equipment', {'type': 'Kit Module'}, 'ground/kit_module'),
            ('equipment', {'type': 'Kit'}, 'ground/kit'),
            ('equipment', {'type': 'Ground Weapon'}, 'ground/weapon'),
            ('equipment', {'type': 'Ground Device'}, 'ground/device'),
            ('equipment', {'type': 'Ship Deflector Dish'}, 'space/deflector'),
            ('equipment', {'type': 'Ship Secondary Deflector'}, 'space/secondary_deflector'),
            ('equipment', {'type': 'Ship Shields'}, 'space/shield'),
            ('equipment', {'type': 'Ship Vanity Shield'}, 'space/vanity_shield'),
            ('equipment', {'type': 'Experimental Weapon'}, 'space/weapons/experimental'),
            ('equipment', {'type': 'Ship Weapon'}, 'space/weapons/unrestricted'),
            ('equipment', {'type': 'Ship Aft Weapon'}, 'space/weapons/aft'),
            ('equipment', {'type': 'Ship Fore Weapon'}, 'space/weapons/fore'),
            ('equipment', {'type': 'Universal Console'}, 'space/consoles/universal'),
            ('equipment', {'type': 'Ship Engineering Console'}, 'space/consoles/engineering'),
            ('equipment', {'type': 'Ship Tactical Console'}, 'space/consoles/tactical'),
            ('equipment', {'type': 'Ship Science Console'}, 'space/consoles/science'),
            ('equipment', {'type': 'Impulse Engine'}, 'space/impulse'),
            ('equipment', {'type': 'Warp Engine'}, 'space/warp'),
            ('equipment', {'type': 'Singularity Engine'}, 'space/singularity'),
            ('equipment', {'type': 'Hangar Bay'}, 'space/hangar'),
            ('equipment', {'type': 'Ship Device'}, 'space/device'),

            # Personal traits
            ('personal_trait', {'environment': 'ground', 'type': '!reputation,!activereputation', 'chartype': 'char'}, 'ground/traits/personal'),
            ('personal_trait', {'environment': 'ground', 'type': 'reputation', 'chartype': 'char'}, 'ground/traits/reputation'),
            ('personal_trait', {'environment': 'ground', 'type': 'activereputation', 'chartype': 'char'}, 'ground/traits/active_reputation'),
            ('personal_trait', {'environment': 'space', 'type': '!reputation,!activereputation', 'chartype': 'char'}, 'space/traits/personal'),
            ('personal_trait', {'environment': 'space', 'type': 'reputation', 'chartype': 'char'}, 'space/traits/reputation'),
            ('personal_trait', {'environment': 'space', 'type': 'activereputation', 'chartype': 'char'}, 'space/traits/active_reputation'),

            # Starship traits (no filters)
            ('starship_trait', None, 'space/traits/starship')
        ]

         # Download all icons in one loop
        for i, (cargo_type, filters, subdir) in enumerate(download_mappings):
            start_frac = i / len(download_mappings)
            end_frac   = (i + 1) / len(download_mappings)
            sub = f"[{i+1}/{len(download_mappings)}] {subdir}"
            # print(f"Downloading {sub} starting at {start_frac} and ending at {end_frac}")

            reporter = TaskProgressReporter(
                task_name   = self.name,
                sub_prefix   = sub,
                report_fn    = report,
                window_start = start_frac,
                window_end   = end_frac,
            )

            reporter("Downloading", 0.0)
            
            dest_dir = images_root / subdir
            downloader.download_icons(cargo_type, dest_dir, image_cache_path, filters, on_progress=reporter)
            
            reporter("Completed", 100.0)