import os
import cv2
import numpy as np
import statistics
import traceback
from pathlib import Path
from multiprocessing import shared_memory
import logging

from ..utils.image import apply_overlay, apply_mask
from .ssim_common import dynamic_hamming_cutoff

logger = logging.getLogger(__name__)

class PHashEngine:
    """
    Prefiltering engine using perceptual hash.
    """

    def __init__(self, debug=False, icon_loader=None, overlay_loader=None, hash_index=None):
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader
        self.hash_index = hash_index 

    def icon_predictions(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.8):
        predictions = []
        similar_icons = {}
        filtered_icons = {}
        found_icons = {}

        for region_label, candidate_regions in icon_slots.items():
            folders = icon_dir_map.get(region_label, [])
            if not folders:
                logger.warning(f"No icon directories found for region '{region_label}'")
                continue
            folders = [Path(f) for f in folders]

            filtered_icons[region_label] = {}
            similar_icons[region_label] = {}
            found_icons[region_label] = {}

            for idx, (x, y, w, h) in enumerate(candidate_regions):
                logger.debug(f"Predicting icons for region '{region_label}' at slot {idx}")
                box = (x, y, w, h)
                roi = screenshot_color[y:y+h, x:x+w]
                found_icons[region_label][box] = {}
                similar_icons[region_label][box] = {}
                filtered_icons[region_label][box] = {}

                try:
                    results = self.hash_index.find_similar_to_image(roi, max_distance=18, top_n=None, grayscale=False)
                except Exception as e:
                    logger.warning(f"Hash prefilter failed for region '{region_label}' at {box}: {e}")
                    traceback.print_exc()
                    continue

                for rel_path, dist in results:
                    if "::" in rel_path:
                        path_part, quality = rel_path.split("::", 1)
                    else:
                        path_part, quality = rel_path, None

                    full_path = self.hash_index.base_dir / path_part
                    filename = os.path.basename(path_part)
                    name = os.path.splitext(filename)[0]
                    normalized_path = os.path.normpath(path_part)

                    # Folder filtering
                    allowed = False
                    for folder in folders:
                        try:
                            relative_folder = folder.relative_to(self.hash_index.base_dir)
                            if normalized_path.startswith(os.path.normpath(str(relative_folder))):
                                allowed = True
                                break
                        except ValueError:
                            continue

                    if not allowed or not full_path.exists():
                        continue

                    box_icons = found_icons[region_label][box]
                    if filename not in box_icons or box_icons[filename]["dist"] > dist:
                        box_icons[filename] = {
                            "dist": dist,
                            "quality": quality,
                            "name": name,
                        }

                    if filename not in filtered_icons[region_label]:
                        icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                        if icon is not None:
                            filtered_icons[region_label][filename] = icon

        # Second pass for thresholding
        for region_label, candidate_regions in icon_slots.items():
            for idx_region, (x, y, w, h) in enumerate(candidate_regions):
                candidates = found_icons[region_label].get((x, y, w, h), {})
                dists = [info["dist"] for info in candidates.values()]
                if not dists:
                    continue

                best_score = min(dists)
                stddev = statistics.stdev(dists) if len(dists) > 1 else 0
                stddev_threshold = best_score + (2 * stddev)
                dm_threshold = dynamic_hamming_cutoff(dists, best_score, max_next_ranks=1, max_allowed_gap=6)
                threshold_val = np.ceil(max(dm_threshold, stddev_threshold)).astype(int)

                candidate_predictions = {}
                filtered_slot_icons = {}

                for filename, info in candidates.items():
                    if info["dist"] > threshold_val:
                        continue

                    candidate_predictions.setdefault(region_label, []).append({
                        "name": info["name"],
                        "top_left": (x, y),
                        "bottom_right": (x + w, y + h),
                        "score": info["dist"],
                        "match_threshold": int(threshold_val),
                        "region": region_label,
                        "method": "hash",
                        "quality": info["quality"],
                        "quality_scale": 1.0,
                        "quality_score": 0.0,
                        "scale": 1.0,
                        "skipped": info["dist"] > threshold_val
                    })
                    filtered_slot_icons[filename] = info

                for region, preds in candidate_predictions.items():
                    predictions.extend(preds)
                # update filtered_icons for final slots
                for filename in filtered_slot_icons:
                    if filename not in filtered_icons[region_label]:
                        full_path = self.hash_index.base_dir / filename
                        icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                        if icon is not None:
                            filtered_icons[region_label][filename] = icon

        logger.info(f"Prefilter predictions complete: {len(predictions)} entries.")
        return predictions, found_icons, filtered_icons
