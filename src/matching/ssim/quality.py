import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import shared_memory
import logging

import traceback

from .common import identify_overlay

logger = logging.getLogger(__name__)


class SSIMQualityEngine:
    def __init__(
        self, debug=False, icon_loader=None, overlay_loader=None, hash_index=None
    ):
        """
        Initialize the IconMatcher.
        """
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader
        self.hash_index = hash_index

    def quality_predictions(
        self,
        icon_slots,
        overlays,
        threshold=0.8,
    ):
        """
        Run icon matching using the selected engine.
        """
        matches = []

        overlay_tasks = []
        region_slot_index = []

        for region_label in icon_slots:
            for slot in icon_slots[region_label]:
                idx = slot["Slot"]
                box = slot["Box"]
                roi = slot["ROI"]

                # if region_label != "Hangar":
                #     continue

                logger.debug(
                    f"Predicting quality for region '{region_label}', slot {idx}"
                )

                overlay_tasks.append((roi, overlays))
                region_slot_index.append((region_label, idx))

        predicted_qualities_by_label = {}
        with ProcessPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(identify_overlay, roi, overlays, region_label, idx): (
                    region_label,
                    idx,
                )
                for (roi, overlays), (region_label, idx) in zip(
                    overlay_tasks, region_slot_index
                )
            }

            for future in as_completed(futures):
                region_label, idx = futures[future]
                try:
                    quality, scale, method = future.result()
                except Exception as e:
                    logger.warning(
                        f"Overlay prediction failed for region '{region_label}', slot {idx}: {e}"
                    )
                    traceback.print_exc()
                    quality, scale, method = "common", 1.0, "default"

                predicted_qualities_by_label.setdefault(region_label, {})[idx] = (quality, scale, method)
                

        logger.info("Performed all quality predictions.")


        print(predicted_qualities_by_label)
#        import sys
#        sys.exit()
        return predicted_qualities_by_label
