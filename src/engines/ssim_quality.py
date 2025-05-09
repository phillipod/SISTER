import os
import cv2
import numpy as np
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import shared_memory
import logging

from .ssim_common import identify_overlay

logger = logging.getLogger(__name__)

class SSIMQualityEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None, hash_index=None):
        """
        Initialize the IconMatcher.
        """
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader
        self.hash_index = hash_index 

    def quality_predictions(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.8):
        """
        Run icon matching using the selected engine.
        """
        matches = []

        max_x = 0
        max_y = 0
        for candidate_regions in icon_slots.values():
            for (x, y, w, h) in candidate_regions:
                max_x = max(max_x, x + w)
                max_y = max(max_y, y + h)

        if max_x > 0 and max_y > 0:
            screenshot_color = screenshot_color[:max_y, :max_x]
            logger.debug(f"Cropped screenshot to ({max_x}, {max_y}) based on candidate regions.")

        shm = shared_memory.SharedMemory(create=True, size=screenshot_color.nbytes)
        shm_array = np.ndarray(screenshot_color.shape, dtype=screenshot_color.dtype, buffer=shm.buf)
        np.copyto(shm_array, screenshot_color)

        shm_name = shm.name
        shape = screenshot_color.shape
        dtype = screenshot_color.dtype
        logger.debug(f"Created shared memory block with name '{shm_name}' and shape {shape} and dtype {dtype}.")

        try:
            overlay_tasks = []
            region_slot_index = []

            for region_label, candidate_regions in icon_slots.items():
                for idx, (x, y, w, h) in enumerate(candidate_regions):
                    logger.debug(f"Predicting quality for region '{region_label}', slot {idx}")
                    roi = screenshot_color[y:y+h, x:x+w]
                    overlay_tasks.append((roi, overlays))
                    region_slot_index.append((region_label, idx))

            predicted_qualities_by_label = {}
            with ProcessPoolExecutor() as executor:
                futures = {
                    executor.submit(identify_overlay, roi, overlays): (region_label, idx)
                    for (roi, overlays), (region_label, idx) in zip(overlay_tasks, region_slot_index)
                }

                for future in as_completed(futures):
                    region_label, idx = futures[future]
                    try:
                        quality, scale, method = future.result()
                    except Exception as e:
                        logger.warning(f"Overlay prediction failed for region '{region_label}', slot {idx}: {e}")
                        quality, scale, method = "common", 1.0, "default"

                    predicted_qualities_by_label.setdefault(region_label, []).append((quality, scale, method))
        finally:
            shm.close()
            shm.unlink()

        logger.info(f"Performed all quality predictions.")

        return predicted_qualities_by_label
