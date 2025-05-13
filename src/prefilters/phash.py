import os
import cv2
import numpy as np
import statistics
import traceback
from pathlib import Path
from collections import Counter

from ..exceptions import PrefilterError

import logging

# from ..iconmap import IconDirectoryMap

logger = logging.getLogger(__name__)


class PHashEngine:
    """
    Prefiltering engine using perceptual hash.
    """

    def __init__(self, debug=False, icon_root=None, hash_index=None):
        self.debug = debug
        self.icon_root = icon_root
        self.hash_index = hash_index

    def dynamic_hamming_score_cutoff(
        self, scores, best_score, max_next_ranks=2, max_allowed_gap=4
    ):
        freqs = Counter(scores)
        sorted_scores = sorted(freqs.items())

        threshold = best_score
        previous = best_score

        rank_count = 0
        for score, count in sorted_scores:
            if score == best_score:
                continue

            # if this next tier is a massive jump from the best, break
            if score - previous > max_allowed_gap:
                break

            threshold = score
            previous = score
            rank_count += 1

            if rank_count >= max_next_ranks:
                break

        return threshold

    def icon_predictions(self, icon_slots, icon_set):
        predictions = {}

        filtered_icons = {}
        similar_icons = {}
        found_icons = {}
        
        for region_label in icon_slots:
            # print(f"region_label: {region_label}")
            folders = icon_set.get(region_label, [])
            if not folders:
                logger.warning(f"No icon directories found for region '{region_label}'")
                continue
            folders = [Path(f) for f in folders]

            filtered_icons[region_label] = {}
            similar_icons[region_label] = {}
            found_icons[region_label] = {}
           
            for slot in icon_slots[region_label]:
                idx = slot['Slot']
                box = slot['Box']
                roi = slot['ROI']

                logger.debug(
                    f"Predicting icons for region '{region_label}' at slot {idx}"
                )

                found_icons[region_label][box] = {}
                similar_icons[region_label][box] = {}
                filtered_icons[region_label][box] = {}

                try:
                    results = self.hash_index.find_similar_to_image(
                        roi, max_distance=18, top_n=None, grayscale=False
                    )
                except Exception as e:
                    raise PrefilterError(
                        f"Hash prefilter failed for region '{region_label}' at {box}: {e}"
                    ) from e

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
                            relative_folder = folder.relative_to(
                                self.hash_index.base_dir
                            )
                            if normalized_path.startswith(
                                os.path.normpath(str(relative_folder))
                            ):
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
                            "name": filename,
                        }

                    try:
                        if filename not in filtered_icons[region_label]:
                            icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                            if icon is not None:
                                filtered_icons[region_label][filename] = icon
                    except Exception as e:
                        raise PrefilterError(
                            f"Hash prefilter failed for region '{region_label}' at {box}: {e}"
                        ) from e

        for region_label in icon_slots:
            predictions[region_label] = {}

            for slot in icon_slots[region_label]:
                idx = slot['Slot']
                box = slot['Box']
                roi = slot['ROI']

                predictions[region_label][idx] = []

                candidates = found_icons[region_label][box]

                dists = [info["dist"] for info in candidates.values()]
                if not dists:
                    continue

                best_score = min(dists)
                stddev = statistics.stdev(dists) if len(dists) > 1 else 0
                stddev_threshold = best_score + (2 * stddev)
                dm_threshold = self.dynamic_hamming_score_cutoff(
                    dists, best_score, max_next_ranks=1, max_allowed_gap=6
                )
                threshold_val = np.ceil(max(dm_threshold, stddev_threshold)).astype(int)

                # candidate_predictions = []
                filtered_slot_icons = {}

                for filename, info in candidates.items():
                    if info["dist"] > threshold_val:
                        continue

                    predictions[region_label][idx].append(
                        {
                            "name": info["name"],
                            # "top_left": (x, y),
                            # "bottom_right": (x + w, y + h),
                            "score": info["dist"],
                            "match_threshold": int(threshold_val),
                            "region": region_label,
                            "slot": idx,
                            "method": "hash-phash",
                            "quality": info["quality"],
                            # "quality_scale": 1.0,
                            # "quality_score": 0.0,
                            # "scale": 1.0,
                        }
                    )

                    filtered_slot_icons[filename] = info

                found_icons[region_label][box] = filtered_slot_icons

                try:
                    for filename in filtered_slot_icons:
                        if filename not in filtered_icons[region_label]:
                            full_path = self.hash_index.base_dir / filename
                            icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                            if icon is not None:
                                filtered_icons[region_label][filename] = icon
                except Exception as e:
                    raise PrefilterError(
                        f"Hash prefilter failed for region '{region_label}' at {box}: {e}"
                    ) from e

                logger.debug(
                    f"Predicted {len(predictions[region_label][idx])} icons for region '{region_label}' at slot {idx}."
                )
                # predictions.extend(candidate_predictions)

        logger.info("Completed all candidate predictions.")


        return predictions, found_icons, filtered_icons
