import os
import sys
import importlib.resources

from typing import Any, Callable, Dict, List, Tuple, Optional
from pathlib import Path

import logging

from ..log_config import setup_logging

from ..pipeline.core import PipelineTask, TaskOutput, PipelineState
from ..pipeline.progress_reporter import TaskProgressReporter

from ..utils.hashindex import HashIndex
from ..utils.image import load_overlays

logger = logging.getLogger(__name__)

class AppInitTask(PipelineTask):
    name = "app_init"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.config = opts
        
    def execute(
        self,
        ctx: PipelineState,
        report: Callable[[str, str, float], None]
    ) -> TaskOutput:
        report(self.name, "Initializing", 0.0)
        
        sub = f"Initializing"

        reporter = TaskProgressReporter(
            task_name   = self.name,
            sub_prefix   = sub,
            report_fn    = report,
            window_start = 0.0,
            window_end   = 1.0,
        )

        self.app_init(reporter)
        
        report(self.name, "Initialized", 100.0)

        return TaskOutput(ctx, None)

    def app_init(self, reporter: Callable[[str, float], None]) -> None:
               
        # Expand data directory path
        self.app_config["data_dir"] = Path(os.path.expanduser(self.config.get("data_dir", "~/.sister_sto")))

        # Set up default paths relative to data_dir if not overridden
        default_paths = {
            "log_dir": "log",
            "icon_dir": "icons",
            "overlay_dir": "overlays",
            "cache_dir": "cache",
            "cargo_dir": "cargo",
            "config_dir": "config",
        }
        

        for key, value in default_paths.items():
            if self.config.get(key):
                self.app_config[key] = Path(os.path.expanduser(self.config.get(key)))
            else:
                self.app_config[key] = self.app_config["data_dir"] / value
            
        self.validate_app_directory(reporter)

        reporter("Loading hash cache", 10.0)
        self.app_config["hash_match_size"] = self.config.get("hash_match_size", (16, 16))
        self.app_config["hash_index"] = HashIndex(
            self.app_config.get("cache_dir"),
            match_size=self.app_config["hash_match_size"],
            cache_file=self.config.get("hash_cache_file", "hash_cache.json"),
        )
        reporter("Loaded hash cache", 95.0)

        self.app_config["log_level"] = self.config.get("log_level", "INFO")
    
        setup_logging(self.app_config.get("log_level"), log_file=self.app_config.get("log_dir") / "sister.log")
        
        icon_root = Path(self.app_config.get("icon_dir"))

        self.app_config["icon_sets"] = {
            "ship": {
                "Fore Weapon": [
                    "space/weapons/fore",
                    "space/weapons/unrestricted",
                ],
                "Aft Weapon": [
                    "space/weapons/aft",
                    "space/weapons/unrestricted",
                ],
                "Experimental Weapon": ["space/weapons/experimental"],
                "Shield": ["space/shield"],
                "Secondary Deflector": ["space/secondary_deflector"],
                "Deflector": [
                    "space/deflector",
                    "space/secondary_deflector",
                ],  # Console doesn't have a specific label for Secondary Deflector, it's located under the Deflector label.
                "Impulse": ["space/impulse"],
                "Warp": ["space/warp"],
                "Singularity": ["space/singularity"],
                "Hangar": ["space/hangar"],
                "Devices": ["space/device"],
                "Universal Console": [
                    "space/consoles/universal",
                    "space/consoles/engineering",
                    "space/consoles/tactical",
                    "space/consoles/science",
                ],
                "Engineering Console": [
                    "space/consoles/engineering",
                    "space/consoles/universal",
                ],
                "Tactical Console": [
                    "space/consoles/tactical",
                    "space/consoles/universal",
                ],
                "Science Console": [
                    "space/consoles/science",
                    "space/consoles/universal",
                ],
            },
            "pc_ground": {
                "Body": ["ground/armor"],
                "Shield": ["ground/shield"],
                "EV Suit": ["ground/ev_suit"],
                "Kit Modules": ["ground/kit_module"],
                "Kit": ["ground/kit"],
                "Devices": ["ground/device"],
                "Weapon": ["ground/weapon"],
            },
            "console_ground": {
                "Body": ["ground/armor"],
                "Shield": ["ground/shield"],
                "EV Suit": ["ground/ev_suit"],
                "Kit": [
                    "ground/kit_module"
                ],  # Console swaps "Kit Modules" to "Kit"
                "Kit Frame": [
                    "ground/kit"
                ],  # And "Kit" becomes "Kit Frame"
                "Devices": ["ground/device"],
                "Weapon": ["ground/weapon"],
            },

            "traits": {
                "Personal Space Traits": [ "space/traits/personal" ],
                "Space Reputation": [ "space/traits/reputation" ],
                "Active Space Reputation": [ "space/traits/active_reputation" ],

                "Personal Ground Traits": [ "ground/traits/personal" ],
                "Ground Reputation": [ "ground/traits/reputation" ],
                "Active Ground Reputation": [ "ground/traits/active_reputation" ],

                "Starship Traits": [ "space/traits/starship" ],
            }
        }

        reporter("Completed", 100.0)

    def validate_app_directory(self, reporter):
        src_dir = None

        try:
            # Python 3.9+: get a Traversable for resources dir
            import importlib.resources as pkg_resources
            resources_root = pkg_resources.files("sister_sto").joinpath("resources")
            
            if not (resources_root.is_dir() and any(resources_root.iterdir())):
                raise FileNotFoundError
            
            # If we got here, resources_root points inside the wheel/egg or source tree.
            src_dir = resources_root
        except (ModuleNotFoundError, FileNotFoundError, AttributeError):
            # importlib.resources didn't work (no package-data or running raw exe without it)
            if getattr(sys, "frozen", False):
                bundle_dir = Path(sys.executable).parent
                src_dir = bundle_dir / "resources"
            else:
                import sister_sto
                bundle_dir = Path(sister_sto.__file__).resolve().parent.parent
                src_dir = bundle_dir / "resources"

        # Create required directories
        for directory in ["data_dir", "log_dir", "cache_dir", "cargo_dir", "icon_dir", "overlay_dir", "config_dir"]:
            self.app_config[directory].mkdir(parents=True, exist_ok=True)
        
        # find all files under src_dir and copy them to the data directory, preserving the directory structure
        for src_path in src_dir.rglob('*'):
            if src_path.is_file():
                relative_path = src_path.relative_to(src_dir)
                dest_path = self.app_config["data_dir"] / relative_path
                if dest_path.exists():
                    continue
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(src_path.read_bytes())

