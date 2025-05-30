from typing import Any, Callable, Dict, List, Tuple, Optional
from pathlib import Path

from logging import getLogger
from log_config import setup_logging

from ..pipeline import PipelineTask, TaskOutput, PipelineState
from ..pipeline.progress_reporter import TaskProgressReporter

from ..utils.hashindex import HashIndex
from ..utils.image import load_overlays

logger = getLogger(__name__)

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
        
        self.app_init()
        
        report(self.name, "Initialized", 100.0)

        return TaskOutput(ctx, None)


    def app_init(self) -> None:
        logger.info(f"Initializing SISTER with config: {self.config}")
        self.app_config["hash_index"] = HashIndex(
            self.config.get("hash_index_dir"),
            self.config.get("engine", "phash"),
            match_size=self.config.get("hash_max_size", (16, 16)),
            output_file=self.config.get("hash_index_file", "hash_index.json"),
        )

        self.app_config["log_level"] = self.config.get("log_level", "INFO")
        setup_logging(self.app_config.get("log_level"))


        self.app_config["icon_dir"] = self.config.get("icon_dir")
        self.app_config["overlay_dir"] = self.config.get("overlay_dir")
        
        icon_root = Path(self.config.get("icon_dir"))

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
