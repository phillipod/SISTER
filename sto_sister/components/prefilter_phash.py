import os
import cv2
import numpy as np
import statistics
import traceback
from pathlib import Path
from collections import Counter

from ..exceptions import PrefilterError

from ..utils.image import show_image

import logging

# from ..iconmap import IconDirectoryMap

logger = logging.getLogger(__name__)


class PHashEngine:
    """
    Prefiltering engine using perceptual hash.
    """

    def __init__(self, debug=False, hash_index=None):
        self.debug = debug
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

    def prefilter(self, icon_slots, build_info, icon_sets, select_items=None):
        builds = build_info if isinstance(build_info, list) else [build_info]

        prefiltered = {}

        filtered_icons = {}
        similar_icons = {}
        found_icons = {}
        target_hashes = {}

        # select_items = {
        #    "Science Console": { 3: True },
        # }


        for info in builds:
            bt = info.get("build_type", "Unknown")
            # print(f"prefiltering icons for build: {bt} [{info['icon_set'] if 'icon_set' in info else 'default'}]")

            icon_set = icon_sets[info["icon_set"]]


            for icon_group_label in icon_slots:
                # print(f"icon_group_label: {icon_group_label}")
                folders = icon_set.get(icon_group_label, [])
                if not folders:
                    logger.warning(
                        f"No icon directories found for icon group '{icon_group_label}'"
                    )
                    continue
                folders = [Path(f) for f in folders]

                filtered_icons[icon_group_label] = {}
                similar_icons[icon_group_label] = {}
                found_icons[icon_group_label] = {}
                target_hashes[icon_group_label] = []

                for slot in icon_slots[icon_group_label]:
                    idx = slot["Slot"]
                    box = slot["Box"]
                    roi = slot["ROI"]
                    roi_hash = slot["Hash"]

                    logger.debug(
                        f"Prefiltering icons for icon group '{icon_group_label}' at slot {idx}"
                    )

                    found_icons[icon_group_label][box] = {}
                    similar_icons[icon_group_label][box] = {}
                    filtered_icons[icon_group_label][box] = {}

                    try:
                        results = self.hash_index.find_similar_to_image(
                            roi_hash, max_distance=18, top_n=None, grayscale=False
                        )
                        target_hashes[icon_group_label].append(roi_hash)
                    except Exception as e:
                        raise PrefilterError(
                            f"Hash prefilter failed for icon group '{icon_group_label}' at {box}: {e}"
                        ) from e

                    # if icon_group_label == "Active Ground Reputation":
                    #     print(f"Active Ground Reputation")
                    #     print(f"roi_hash: {roi_hash}")
                    #     print(f"results: {results}")
                    #     show_image([roi])

                    for rel_path, dist in results:
                        if "::" in rel_path:
                            path_part, overlay = rel_path.split("::", 1)
                        else:
                            path_part, overlay = rel_path, None

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

                        box_icons = found_icons[icon_group_label][box]
                        if filename not in box_icons or box_icons[filename]["dist"] > dist:
                            box_icons[filename] = {
                                "dist": dist,
                                "overlay": overlay,
                                "name": filename,
                            }

                        try:
                            if filename not in filtered_icons[icon_group_label]:
                                icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                                if icon is not None:
                                    # Ensure icon is 49x64
                                    if icon.shape[0] != 64 or icon.shape[1] != 49:
                                        icon = cv2.resize(icon, (49, 64))
                                    filtered_icons[icon_group_label][filename] = icon
                        except Exception as e:
                            raise PrefilterError(
                                f"Hash prefilter failed for icon group '{icon_group_label}' at {box}: {e}"
                            ) from e

        for icon_group_label in icon_slots:
            if select_items:
                if icon_group_label not in select_items.keys():
                    logger.info(
                        f"Skipping icon group '{icon_group_label}' - user selection"
                    )
                    continue

            prefiltered[icon_group_label] = {}

            for slot in icon_slots[icon_group_label]:
                idx = slot["Slot"]
                box = slot["Box"]
                roi = slot["ROI"]
                roi_hash = slot["Hash"]

                if select_items and icon_group_label in select_items:
                    if (
                        idx not in select_items[icon_group_label]
                        or select_items[icon_group_label][idx] == False
                    ):
                        logger.info(
                            f"Skipping icon group '{icon_group_label}' at slot {idx} - user selection"
                        )
                        continue

                prefiltered[icon_group_label][idx] = []

                candidates = found_icons[icon_group_label][box]

                dists = [info["dist"] for info in candidates.values()]
                if not dists:
                    continue

                best_score = min(dists)
                stddev = statistics.stdev(dists) if len(dists) > 1 else 0
                stddev_threshold = best_score + (2 * stddev)
                dm_threshold = self.dynamic_hamming_score_cutoff(
                    dists, best_score, max_next_ranks=2, max_allowed_gap=6
                )
                threshold_val = np.ceil(max(dm_threshold, stddev_threshold)).astype(int)

                # candidate_prefiltered = []
                filtered_slot_icons = {}

                for filename, info in candidates.items():
                    if info["dist"] > threshold_val:
                        continue

                    prefiltered[icon_group_label][idx].append(
                        {
                            "name": info["name"],
                            # "top_left": (x, y),
                            # "bottom_right": (x + w, y + h),
                            "score": info["dist"],
                            "match_threshold": int(threshold_val),
                            "icon_group": icon_group_label,
                            "slot": idx,
                            "method": "hash-phash",
                            "overlay": info["overlay"],
                            "roi_hash": target_hashes[icon_group_label][idx],
                            # "overlay_scale": 1.0,
                            # "overlay_score":0.0,
                            # "scale": 1.0,
                        }
                    )

                    filtered_slot_icons[filename] = info

                found_icons[icon_group_label][box] = filtered_slot_icons

                try:
                    for filename in filtered_slot_icons:
                        if filename not in filtered_icons[icon_group_label]:
                            full_path = self.hash_index.base_dir / filename
                            icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                            if icon is not None:
                                # Ensure icon is 49x64
                                if icon.shape[0] != 64 or icon.shape[1] != 49:
                                    icon = cv2.resize(icon, (49, 64))                                
                                filtered_icons[icon_group_label][filename] = icon
                except Exception as e:
                    raise PrefilterError(
                        f"Hash prefilter failed for icon group '{icon_group_label}' at {box}: {e}"
                    ) from e

                logger.debug(
                    f"Prefiltered {len(prefiltered[icon_group_label][idx])} icons for icon group '{icon_group_label}' at slot {idx}."
                )
                # prefiltered.extend(candidate_prefiltered)

        logger.verbose(
            f"Total icons prefiltered: {sum(len(slots) for icon_group in prefiltered.values() for slots in icon_group.values())}"
        )
        logger.verbose("Completed prefiltering all candidates.")

        return prefiltered, found_icons, filtered_icons
