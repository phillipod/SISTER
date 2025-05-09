import os
import cv2
import numpy as np
import tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import shared_memory
import logging

from .ssim_common import multi_scale_match

logger = logging.getLogger(__name__)

class SSIMMatchEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None, hash_index=None):
        """
        Initialize the IconMatcher.
        """
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader
        self.hash_index = hash_index 

    def match_all(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, predicted_qualities_by_region, filtered_icons, found_icons, threshold=0.8):
        """
        Run icon matching using the selected engine.
        """
        matches = []
        matched_indexes_global = set()
        matched_icon_slot_pairs = set()

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

            future_to_args = {}
            with ProcessPoolExecutor() as executor:
                futures = [executor.submit(self.match_single_icon, args) for args in args_list]
                for future, args in zip(futures, args_list):
                    future_to_args[future] = args

                for future in as_completed(future_to_args):
                    args = future_to_args[future]
                    result, matched, slot_idx = future.result()
                    matches.extend(result)
                    for idx in matched:
                        matched_indexes_global.add((args[-2], args[1]))
                        matched_icon_slot_pairs.add((args[-2], args[0], idx))

            # Fallback pass
            fallback_args_list = []
            for region_label, candidate_regions in icon_slots.items():
                region_filtered_icons = filtered_icons.get(region_label, {})
                if not region_filtered_icons:
                    continue

                predicted_qualities = predicted_qualities_by_region.get(region_label, [])

                for (x, y, w, h) in candidate_regions:
                    original_idx = candidate_regions.index((x, y, w, h))
                    if (region_label, original_idx) in matched_indexes_global:
                        continue

                    region_key = (x, y, w, h)
                    icons_for_slot = found_icons[region_label].get(region_key, {})
                    if not icons_for_slot:
                        continue

                    fallback_icons = list(icons_for_slot.keys())
                    if not fallback_icons:
                        continue

                    logger.info(f"Fallback matching {len(fallback_keys)} icons against 1 candidate for label '{region_label}' at slot {original_idx}")

                    for idx_icon, name in enumerate(fallback_icons, 1):
                        if (region_label, name, original_idx) in matched_icon_slot_pairs:
                            continue

                        icon_color = region_filtered_icons.get(name)
                        if icon_color is None:
                            continue

                        args = (
                            name, original_idx, icon_color, shm_name, shape, dtype,
                            [(x, y, w, h)], [predicted_qualities[original_idx]],
                            threshold, overlays, idx_icon, len(fallback_icons),
                            region_label, True
                        )
                        fallback_args_list.append(args)

            future_to_args = {}
            with ProcessPoolExecutor() as executor:
                futures = [executor.submit(self.match_single_icon, args) for args in fallback_args_list]
                for future, args in zip(futures, fallback_args_list):
                    future_to_args[future] = args

                for future in as_completed(future_to_args):
                    args = future_to_args[future]
                    result, matched, slot_idx = future.result()
                    matches.extend(result)
                    for idx in matched:
                        matched_indexes_global.add((args[-2], args[1]))
                        matched_icon_slot_pairs.add((args[-2], args[0], idx))
        finally:
            shm.close()
            shm.unlink()

        logger.info(f"Completed all region matches.")
        return matches

    def match_single_icon(self, args):
        name, slot_idx, icon_color, shm_name, shape, dtype, candidate_regions, predicted_qualities, threshold, overlays, idx, total, region_label, fallback_mode = args

        shm = shared_memory.SharedMemory(name=shm_name)
        screenshot_color = np.ndarray(shape, dtype=dtype, buffer=shm.buf)

        found_matches = []
        matched_candidate_indexes = set()

        for idx_region, (x, y, w, h) in enumerate(candidate_regions):
            quality, quality_scale, quality_method = predicted_qualities[idx_region]
            if not quality or quality not in overlays:
                continue

            roi = screenshot_color[y:y+h, x:x+w]
            scale_factor = None

            if roi.shape[0] > 43 * 1.1 or roi.shape[1] > 33 * 1.1:
                scale_factor = min(43 / roi.shape[0], 33 / roi.shape[1])
                roi = cv2.resize(roi, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)

            best_match = None
            method = "ssim-all-overlays-all-scales-fallback"
            quality_used = quality

            if quality == "common":
                best_score = -np.inf
                for overlay_name, overlay_img in overlays.items():
                    blended_icon = apply_overlay(icon_color, overlay_img)
                    match = multi_scale_match(roi, blended_icon, threshold=threshold)

                    if match and match[2] > best_score:
                        best_score = match[2]
                        best_match = match
                        quality_used = overlay_name
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
                    best_match = multi_scale_match(roi, blended_icon, scales=scales, threshold=threshold)
                else:
                    method = 'ssim-predicted-overlay-all-scales-fallback'
                    best_match = multi_scale_match(roi, blended_icon, threshold=threshold)

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
