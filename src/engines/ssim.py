import os
import cv2
import numpy as np
import tempfile
#import atexit
#import cProfile, pstats
import statistics
import traceback

from collections import Counter
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import shared_memory

from skimage.metrics import structural_similarity as ssim
#from src.utils.image import ssim
#from collections import Counter, defaultdict

from ..utils.image import apply_overlay, apply_mask

import logging

logger = logging.getLogger(__name__)


#if os.environ.get("PROFILE_CHILDREN") == "1":
#    _worker_profiler = cProfile.Profile()
#    _worker_profiler.enable()
#    _profile_path = os.path.join(tempfile.gettempdir(), f"profile_worker_{os.getpid()}.prof")
#
#    def _dump_worker_profile():
#        _worker_profiler.disable()
#        _worker_profiler.dump_stats(_profile_path)
#        print(f"[Profiler] Saved profile to {_profile_path}")
#
#    atexit.register(_dump_worker_profile)

class SSIMEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None, hash_index=None):
        """
        Initialize the IconMatcher.

        Args:
            debug (bool): If True, enables debug logging.
        """

        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader
        self.hash_index = hash_index 

    def dynamic_hamming_cutoff(self, scores, best_score, max_next_ranks=2, max_allowed_gap=4):
        from collections import Counter
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



    def identify_overlay(self, region_crop, overlays, step=1, scales=np.linspace(0.6, 1.0, 40)):
        if "common" in overlays:
            base_overlay = overlays["common"]
            oh, ow = base_overlay.shape[:2]
            rh, rw = region_crop.shape[:2]
            if rh > 43 * 1.1 or rw > 33 * 1.1:
                scale_factor = min(43 / rh, 33 / rw)
                region_crop = cv2.resize(region_crop, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
                #logger.debug(f"Resized region_crop to {region_crop.shape[:2]} using scale factor {scale_factor:.2f}")


        best_score = -np.inf
        best_quality = None
        best_scale = None
        best_method = None
        for quality_name, overlay in reversed(list(overlays.items())):
            if quality_name == "common" and best_score > 0.6: 
                continue
            #logger.debug(f"Trying quality overlay {quality_name}")

            overlay_rgb = overlay[:, :, :3]
            overlay_alpha = overlay[:, :, 3] / 255.0

            for scale in scales:
                #logger.debug(f"Trying scale {scale}")
                resized_rgb = cv2.resize(overlay_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                resized_alpha = cv2.resize(overlay_alpha, (resized_rgb.shape[1], resized_rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

                h, w = resized_rgb.shape[:2]
                H, W = region_crop.shape[:2]

                if h > H or w > W:
                    continue

                for y in range(0, H - h + 1, step):
                    for x in range(0, W - w + 1, step):
                        roi = region_crop[y:y+h, x:x+w]

                        masked_region = (roi * resized_alpha[..., np.newaxis]).astype(np.uint8)
                        masked_overlay = (resized_rgb * resized_alpha[..., np.newaxis]).astype(np.uint8)

                        try:
                            score = ssim(masked_region, masked_overlay, channel_axis=-1)
                        except ValueError:
                            continue

                        #print(f"Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")
                        if score > best_score:
                            best_score = score
                            best_quality = quality_name
                            best_scale = scale
                            best_method = 'ssim'

        #print(f"Best matched overlay: {best_quality} with score {best_score:.4f} at scale {best_score if best_score is not None else 'N/A'} using {best_method}")
        return best_quality, best_scale, best_method

    def match_single_icon(self, args):
        name, slot_idx, icon_color, shm_name, shape, dtype, candidate_regions, predicted_qualities, threshold, overlays, idx, total, region_label, fallback_mode = args

        shm = shared_memory.SharedMemory(name=shm_name)
        screenshot_color = np.ndarray(shape, dtype=dtype, buffer=shm.buf)

        found_matches = []
        matched_candidate_indexes = set()

        #logger.verbose(f"Matching icon {idx}/{total} '{name}' in region '{region_label}'")
        
        for idx_region, (x, y, w, h) in enumerate(candidate_regions):
            quality, quality_scale, quality_method = predicted_qualities[idx_region]
            if not quality or quality not in overlays:
                continue

            roi = screenshot_color[y:y+h, x:x+w]
            scale_factor = None

            # Resize ROI down if it's too large
            if roi.shape[0] > 43 * 1.1 or roi.shape[1] > 33 * 1.1:
                scale_factor = min(43 / roi.shape[0], 33 / roi.shape[1])
                roi = cv2.resize(roi, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)

            best_match = None
            method = "ssim-all-overlays-all-scales-fallback"
            quality_used = quality  # could be overwritten if common

            if quality == "common":
                best_score = -np.inf
                for overlay_name, overlay_img in overlays.items():
                    blended_icon = apply_overlay(icon_color, overlay_img)
                    match = self.multi_scale_match(roi, blended_icon, threshold=threshold)

                    if match and match[2] > best_score:
                        best_score = match[2]
                        best_match = match
                        quality_used = overlay_name  # override quality
            else:
                blended_icon = apply_overlay(icon_color, overlays[quality])
                icon_h, icon_w = icon_color.shape[:2]
                overlay_h, overlay_w = overlays[quality].shape[:2]

                if icon_h == overlay_h and icon_w == overlay_w and quality_scale:
                    scales = [quality_scale]
                    method = 'ssim-predicted-overlay-scale'
                else:
                    scales = np.linspace(0.6, 0.8, 20)
                    method = 'ssim-predicted-overlays-all-scales-icon-size-mismatch-fallback'

                if not fallback_mode:
                    best_match = self.multi_scale_match(roi, blended_icon, scales=scales, threshold=threshold)
                else:
                    method = 'ssim-predicted-overlay-all-scales-fallback'
                    best_match = self.multi_scale_match(roi, blended_icon, threshold=threshold)

            if best_match:
                top_left, size, score, scale = best_match
                gx, gy = top_left
                match_w, match_h = size

                if scale_factor:
                    inv_scale = 1.0 / scale_factor
                    gx = int(np.floor(gx * inv_scale))
                    gy = int(np.floor(gy * inv_scale))
                    match_w = int(np.ceil(match_w * inv_scale)) + 1
                    match_h = int(np.ceil(match_h * inv_scale)) + 1

                found_matches.append({
                    "name": f"{name}",
                    "top_left": (x + gx, y + gy),
                    "bottom_right": (x + gx + match_w, y + gy + match_h),
                    "score": score,
                    "scale": scale,
                    "quality_scale": quality_scale,
                    "quality": quality_used,
                    "method": method,
                    "region": region_label
                })
                matched_candidate_indexes.add(idx_region)

        return found_matches, matched_candidate_indexes, slot_idx

    def match_all(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, predicted_qualities_by_region, filtered_icons, found_icons, threshold=0.8):
        matches = []
        matched_indexes_global = set()
        matched_icon_slot_pairs = set()  # Track (region_label, icon_name, candidate_idx)

        max_x = 0
        max_y = 0
        for candidate_regions in icon_slots.values():
            for (x, y, w, h) in candidate_regions:
                max_x = max(max_x, x + w)
                max_y = max(max_y, y + h)

        if max_x > 0 and max_y > 0:
            screenshot_color = screenshot_color[:max_y, :max_x]
            logger.debug(f"Cropped screenshot to ({max_x}, {max_y}) based on candidate regions.")

        # Create shared memory block for screenshot_color
        shm = shared_memory.SharedMemory(create=True, size=screenshot_color.nbytes)
        shm_array = np.ndarray(screenshot_color.shape, dtype=screenshot_color.dtype, buffer=shm.buf)
        np.copyto(shm_array, screenshot_color)

        shm_name = shm.name
        shape = screenshot_color.shape
        dtype = screenshot_color.dtype
        logger.debug(f"Created shared memory block with name '{shm_name}' and shape {shape} and dtype {dtype}.")

        try:
            args_list = []

            for region_label, candidate_regions in icon_slots.items():
                region_filtered_icons = filtered_icons.get(region_label, {})
                if not region_filtered_icons:
                    logger.warning(f"No filtered icons available for region '{region_label}'")
                    continue

                predicted_qualities = predicted_qualities_by_region.get(region_label, [])
                if len(predicted_qualities) != len(candidate_regions):
                    logger.warning(f"Mismatch between candidate regions and predicted qualities for '{region_label}'")

                for idx_region, (x, y, w, h) in enumerate(candidate_regions):
                    region_key = (x, y, w, h)
                    icons_for_slot = found_icons[region_label].get(region_key, {})

                    if not icons_for_slot:
                        continue

                    logger.info(f"Matching {len(icons_for_slot)} icons against 1 candidate for label '{region_label}' at slot {idx_region}")
                    predicted_quality = predicted_qualities[idx_region]

                    for idx_icon, (name, icon_color) in enumerate(region_filtered_icons.items(), 1):
                        if name not in icons_for_slot:
                            continue

                        args = (
                            name, idx_region, icon_color, shm_name, shape, dtype,
                            [(x, y, w, h)], [predicted_quality],
                            threshold, overlays, idx_icon, len(region_filtered_icons),
                            region_label, False
                        )
                        args_list.append(args)

            # Initial parallel pass
            future_to_args = {}
            with ProcessPoolExecutor() as executor:
                futures = [executor.submit(self.match_single_icon, args) for args in args_list]
                for future, args in zip(futures, args_list):
                    future_to_args[future] = args

                for future in as_completed(future_to_args):
                    args = future_to_args[future]
                    region_label = args[-2]
                    name = args[0]
                    candidate_regions = args[6]
                    result, matched, slot_idx = future.result()
                    matches.extend(result)
                    #print(f'Matched {result}')
                    for idx in matched:
                        matched_indexes_global.add((region_label, args[1]))
                        matched_icon_slot_pairs.add((region_label, name, idx))

            # Fallback pass only for unmatched icon-slot pairs
            fallback_args_list = []
            for region_label, candidate_regions in icon_slots.items():
                region_filtered_icons = filtered_icons.get(region_label, {})
                if not region_filtered_icons:
                    continue

                predicted_qualities = predicted_qualities_by_region.get(region_label, [])

                for (x, y, w, h) in candidate_regions:
                    try:
                        original_idx = candidate_regions.index((x, y, w, h))
                    except ValueError:
                        logger.warning(f"Region ({x}, {y}, {w}, {h}) not found in original candidate list for '{region_label}'")
                        continue

                    if (region_label, original_idx) in matched_indexes_global:
                        continue  # already matched

                    region_key = (x, y, w, h)
                    icons_for_slot = found_icons[region_label].get(region_key, {})
                    if not icons_for_slot:
                        continue

                    predicted_quality = predicted_qualities[original_idx]

                    fallback_icons = list(icons_for_slot.keys())
                    if not fallback_icons:
                        continue

                    logger.info(f"Fallback matching {len(fallback_icons)} icons against 1 candidate for label '{region_label}' at slot {original_idx}")

                    for idx_icon, name in enumerate(fallback_icons, 1):
                        if (region_label, name, original_idx) in matched_icon_slot_pairs:
                            continue  # already matched this icon into this slot

                        icon_color = region_filtered_icons.get(name)
                        if icon_color is None:
                            continue

                        args = (
                            name, original_idx, icon_color, shm_name, shape, dtype,
                            [(x, y, w, h)], [predicted_quality],
                            threshold, overlays, idx_icon, len(fallback_icons),
                            region_label, True  # Fallback mode
                        )
                        fallback_args_list.append(args)

            # Run fallback pass
            future_to_args = {}
            with ProcessPoolExecutor() as executor:
                futures = [executor.submit(self.match_single_icon, args) for args in fallback_args_list]
                for future, args in zip(futures, args_list):
                    future_to_args[future] = args

                for future in as_completed(future_to_args):
                    args = future_to_args[future]
                    region_label = args[-2]
                    name = args[0]
                    candidate_regions = args[6]
                    result, matched, slot_idx = future.result()
                    matches.extend(result)
                    for idx in matched:
                        matched_indexes_global.add((region_label, args[1]))
                        matched_icon_slot_pairs.add((region_label, name, idx))
        finally:
            shm.close()
            shm.unlink()

        logger.info(f"Completed all region matches.")
        return matches

    def icon_predictions(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.8):
        predictions = []

        max_x = 0
        max_y = 0
        for candidate_regions in icon_slots.values():
            for (x, y, w, h) in candidate_regions:
                max_x = max(max_x, x + w)
                max_y = max(max_y, y + h)

        if max_x > 0 and max_y > 0:
            screenshot_color = screenshot_color[:max_y, :max_x]
            logger.debug(f"Cropped screenshot to ({max_x}, {max_y}) based on candidate regions.")

        # Create shared memory block for screenshot_color
        shm = shared_memory.SharedMemory(create=True, size=screenshot_color.nbytes)
        shm_array = np.ndarray(screenshot_color.shape, dtype=screenshot_color.dtype, buffer=shm.buf)
        np.copyto(shm_array, screenshot_color)

        shm_name = shm.name
        shape = screenshot_color.shape
        dtype = screenshot_color.dtype
        logger.debug(f"Created shared memory block with name '{shm_name}' and shape {shape} and dtype {dtype}.")

        try:
            filtered_icons = {}
            similar_icons = {}
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

            for region_label, candidate_regions in icon_slots.items():
                for idx_region, (x, y, w, h) in enumerate(candidate_regions):
                    roi = screenshot_color[y:y+h, x:x+w]
                    candidates = found_icons[region_label][(x, y, w, h)]

                    dists = [info["dist"] for info in candidates.values()]
                    if not dists:
                        continue

                    best_score = min(dists)
                    stddev = statistics.stdev(dists) if len(dists) > 1 else 0
                    stddev_threshold = best_score + (2 * stddev)
                    dm_threshold = self.dynamic_hamming_cutoff(dists, best_score, max_next_ranks=1, max_allowed_gap=6)
                    threshold_val = np.ceil(max(dm_threshold, stddev_threshold)).astype(int)

                    candidate_predictions = []
                    filtered_slot_icons = {}

                    for filename, info in candidates.items():
                        if info["dist"] > threshold_val:
                            continue

                        candidate_predictions.append({
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

                    found_icons[region_label][(x, y, w, h)] = filtered_slot_icons
                    for filename in filtered_slot_icons:
                        if filename not in filtered_icons[region_label]:
                            full_path = self.hash_index.base_dir / filename
                            icon = cv2.imread(str(full_path), cv2.IMREAD_COLOR)
                            if icon is not None:
                                filtered_icons[region_label][filename] = icon

                    logger.debug(f"Predicted {len(candidate_predictions)} icons for region '{region_label}' at slot {idx_region}.")
                    predictions.extend(candidate_predictions)

        finally:
            shm.close()
            shm.unlink()

        logger.info(f"Completed all candidate predictions.")
        return predictions, found_icons, filtered_icons

    def quality_predictions(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.8):
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

        # Create shared memory block for screenshot_color
        shm = shared_memory.SharedMemory(create=True, size=screenshot_color.nbytes)
        shm_array = np.ndarray(screenshot_color.shape, dtype=screenshot_color.dtype, buffer=shm.buf)
        np.copyto(shm_array, screenshot_color)

        shm_name = shm.name
        shape = screenshot_color.shape
        dtype = screenshot_color.dtype
        logger.debug(f"Created shared memory block with name '{shm_name}' and shape {shape} and dtype {dtype}.")

        try:
            from concurrent.futures import ProcessPoolExecutor, as_completed

            # Collect all ROIs from all regions
            overlay_tasks = []
            region_slot_index = []

            # Step 1: Collect all tasks
            for region_label, candidate_regions in icon_slots.items():
                for idx, (x, y, w, h) in enumerate(candidate_regions):
                    logger.debug(f"Predicting quality for region '{region_label}', slot {idx}")
                    roi = screenshot_color[y:y+h, x:x+w]
                    overlay_tasks.append((roi, overlays))
                    region_slot_index.append((region_label, idx))

            # Step 2: Run in parallel
            predicted_qualities_by_label = {}
            with ProcessPoolExecutor() as executor:
                futures = {
                    executor.submit(self.identify_overlay, roi, overlays): (region_label, idx)
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
            # Always cleanup shared memory
            shm.close()
            shm.unlink()

        logger.info(f"Performed all quality predictions.")

        return predicted_qualities_by_label


    def multi_scale_match(self, region_color, template_color, scales=np.linspace(0.6, 0.8, 20), threshold=0.7):
        best_val = -np.inf
        best_match = None
        best_loc = None
        best_scale = 1.0

        region_color = apply_mask(cv2.GaussianBlur(region_color, (3, 3), 0))
        template_color = apply_mask(cv2.GaussianBlur(template_color, (3, 3), 0))

        for scale in scales:
            resized_template = cv2.resize(template_color, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            th, tw = resized_template.shape[:2]
            if th > region_color.shape[0] or tw > region_color.shape[1]:
                continue

            for y in range(0, region_color.shape[0] - th + 1, 1):
                for x in range(0, region_color.shape[1] - tw + 1, 1):
                    roi = region_color[y:y+th, x:x+tw]
                    try:
                        s = ssim(roi, resized_template, channel_axis=-1)
                    except ValueError:
                        continue
                    if s > best_val:
                        best_val = s
                        best_loc = (x, y)
                        best_match = (tw, th)
                        best_scale = scale
        if best_val >= threshold:
            return best_loc, best_match, best_val, best_scale
        else:
            return None

 