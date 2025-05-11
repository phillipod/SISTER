import os
import cv2
import numpy as np
import statistics
import traceback
from pathlib import Path
from multiprocessing import shared_memory
from collections import Counter
from pprint import pprint

import sys

import logging

from ..utils.image import apply_overlay, apply_mask
#from ..iconmap import IconDirectoryMap

logger = logging.getLogger(__name__)

class PHashEngine:
    """
    Prefiltering engine using perceptual hash.
    """

    def __init__(self, debug=False, icon_root=None, hash_index=None):
        self.debug = debug
        self.icon_root = icon_root
        #self.load_icons = icon_loader
        self.hash_index = hash_index 

    def dynamic_hamming_score_cutoff(self, scores, best_score, max_next_ranks=2, max_allowed_gap=4):
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

    def icon_predictions(self, image, icon_slots, icon_set):
        predictions = []
        similar_icons = {}
        filtered_icons = {}
        found_icons = {}


        for region_label, candidate_regions in icon_slots.items():
            folders = icon_set.get(region_label)    

            #print(f"region_label: {region_label} folders: {folders}")
            if not folders:
                print(f"No icon directories found for region '{region_label}'")
                continue

            folders = [Path(f) for f in folders]

            filtered_icons[region_label] = {}
            similar_icons[region_label] = {}
            found_icons[region_label] = {}

            #print(f"candidate_regions: {candidate_regions}")
            for idx, (x, y, w, h) in candidate_regions.items():
                #print(f"Predicting icons for region '{region_label}' at slot {idx}")
                box = (x, y, w, h)
                roi = image[y:y+h, x:x+w]
                found_icons[region_label][box] = {}
                similar_icons[region_label][box] = {}
                filtered_icons[region_label][box] = {}

                try:
                    #print(f"Hash prefiltering region '{region_label}' at {box}")
                    results = self.hash_index.find_similar_to_image(roi, max_distance=18, top_n=None, grayscale=False)
                    #print(f"Hash prefilter complete for region '{region_label}' at {box}")
                except Exception as e:
                    print(f"Hash prefilter failed for region '{region_label}' at {box}: {e}")
                    traceback.print_exc()
                    continue

                if region_label == "Aft Weapon":
                    print(f"results pre filter: {results}")
#                    sys.exit(1)

                #print(f"Found {len(results)} similar icons for region '{region_label}' at {box}")   
                for rel_path, dist in results:
                    #print(f"[Prefilter] Found icon '{rel_path}' at distance {dist}")
                    if "::" in rel_path:
                        path_part, quality = rel_path.split("::", 1)
                    else:
                        path_part, quality = rel_path, None

                    #print(f"[Prefilter] Found icon '{path_part}' at distance {dist} with quality {quality}")

                    full_path = self.icon_root / path_part
                    filename = os.path.basename(path_part)
                    name = os.path.splitext(filename)[0]
                    normalized_path = os.path.normpath(path_part)

                    #print(f"full_path: {full_path} filename: {filename} name: {name} normalized_path: {normalized_path}")
   #                 print(f"[Prefilter] Full path: {full_path}, path_part: {path_part} -> relative to hash_index.base_dir: {self.hash_index.base_dir}")
                    # base_dir = self.hash_index.base_dir.resolve()
                    # candidate = full_path.resolve()
  #                  print(f"[Prefilter] Base dir: {base_dir}")
 #                   print(f"[Prefilter] Candidate dir: {candidate_dir}")

                    # allowed = False
                    # for folder in folders:
                    #     #print(f"[Prefilter] Checking {candidate} against {folder}")
                    #     folder = Path(folder).resolve()

                    #     if candidate.is_relative_to(folder):
                    #         allowed = True
                    #         break

                    #print(f"folders: {folders}")
                    allowed = False
                    for folder in folders:
                        normalized_folder = Path(os.path.normpath(path_part)) 

                     #   print(f"[Prefilter] Checking {full_path} against {self.icon_root}")
                        # print(Path(full_path).relative_to(self.icon_root))
                        try:
                            relative_folder = folder.relative_to(self.icon_root)
                      #      print(f"[Prefilter] Relative folder: {relative_folder}")

                            if normalized_path.startswith(os.path.normpath(str(relative_folder))):
                       #         print(f"{normalized_path} starts with {os.path.normpath(str(relative_folder))}")
                                allowed = True
                                break
                        except ValueError:
                            continue

                    if not allowed or not full_path.exists():
#                        print(f"[Prefilter] Icon '{full_path}' not allowed")
                        continue
                    #print(f"[Prefilter] Icon '{full_path}' allowed")
                    box_icons = found_icons[region_label][box]
                    if filename not in box_icons or box_icons[path_part]["dist"] > dist:
                        box_icons[path_part] = {
                            "dist": dist,
                            "quality": quality,
                            "name": name,
                            "file": path_part
                        }

                    #if filename not in filtered_icons[region_label]:
                    #    print(f"[Prefilter] Selecting icon '{full_path}' for load")
                    #    filtered_icons[region_label][path_part] = None
                        #icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                        #if icon is not None:
                        #    filtered_icons[region_label][idx][filename] = icon
                if region_label == "Aft Weapon":
                    print(f"results post filter: {found_icons[region_label]}")
                    sys.exit(1)

        #print(f"[Prefilter] Found icons: ")
        #for region_label, candidate_regions in found_icons.items():
        #    print(f"[Prefilter] Region '{region_label}': \n")
        #    pprint(candidate_regions, indent=4)
            
        # print(f"[Prefilter] Filtered icons: {filtered_icons}")

        # Second pass for thresholding
        for region_label, candidate_regions in icon_slots.items():
            for idx_region, (x, y, w, h) in candidate_regions.items():
                print(f"Running thresholding for region '{region_label}' at slot {idx_region}")
                print(f"Found icons: {found_icons[region_label]}")
                candidates = found_icons[region_label].get((x, y, w, h), {})

                dists = [info["dist"] for info in candidates.values()]
                if not dists:
                    continue

                best_score = min(dists)
                stddev = statistics.stdev(dists) if len(dists) > 1 else 0
                stddev_threshold = best_score + (2 * stddev)
                dm_threshold = self.dynamic_hamming_score_cutoff(dists, best_score, max_next_ranks=1, max_allowed_gap=6)
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
                        #"skipped": info["dist"] > threshold_val
                    })
                    filtered_slot_icons[filename] = info

                for region, preds in candidate_predictions.items():
                    predictions.extend(preds)
                
                found_icons[region_label][(x, y, w, h)] = filtered_slot_icons

                # update filtered_icons for final slots
                # print(f"filtered_slot_icons: {filtered_slot_icons}")
                for filename in filtered_slot_icons:
                    # print(f"[Prefilter] Loading icon '{filename}'")

                    # if filename not in filtered_icons[region_label]:
                    #      print(f"[Prefilter] Icon not in filtered_icons")

                    if filtered_slot_icons[filename] is not None:
                        # print(f"[Prefilter] Icon not in filtered_slot_icons")
                        full_path = self.icon_root / filename
                        # print(f"[Prefilter] Loading icon '{full_path}'")
                        icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                        if icon is not None:
                            # print(f"[Prefilter] Icon {filename} loaded")
                            filtered_icons[region_label][filename] = icon

        #print(f"[Prefilter] Found icons: {found_icons}")
        logger.info(f"Prefilter predictions complete: {len(predictions)} entries.")
        return predictions, found_icons, filtered_icons
