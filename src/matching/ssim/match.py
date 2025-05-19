import cv2
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed, ThreadPoolExecutor
from multiprocessing import shared_memory
import logging

from .common import multi_scale_match
from ...utils.image import apply_overlay

from ...exceptions import SISTERError

logger = logging.getLogger(__name__)


class SSIMMatchEngine:
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

    def match_all(
        self,
        icon_slots,
        icon_dir_map,
        overlays,
        predicted_qualities_by_region,
        filtered_icons,
        found_icons,
        threshold=0.7,
    ):
        """
        Run icon matching using the selected engine.
        """
        matches = {}

        try:
            args_list = []

            for region_label in icon_slots:
                matches[region_label] = {}

                region_filtered_icons = filtered_icons.get(region_label, {})
                if not region_filtered_icons:
                    logger.warning(
                        f"No filtered icons available for region '{region_label}'"
                    )
                    continue

                predicted_qualities = predicted_qualities_by_region.get(
                    region_label, {}
                )
                if len(predicted_qualities.keys()) != len(icon_slots[region_label]):
                    logger.warning(
                        f"Mismatch between candidate regions and predicted qualities for '{region_label}'"
                    )

                for slot in icon_slots[region_label]:
                    idx = slot["Slot"]
                    box = slot["Box"]
                    roi = slot["ROI"]

                    if idx not in matches[region_label]:
                        matches[region_label][idx] = []

                    icons_for_slot = found_icons[region_label].get(box, {})
                    # print(f"icons_for_slot: {icons_for_slot}")

                    if not icons_for_slot:
                        continue

                    
                    predicted_quality = predicted_qualities[idx]

                    logger.info(
                        f"Matching {len(icons_for_slot)} icons into label '{region_label}' at slot {idx} with quality {predicted_quality[0]["quality"]} at scale {predicted_quality[0]['scale']}"
                    )

                    for idx_icon, (name, icon_color) in enumerate(
                        region_filtered_icons.items(), 1
                    ):
                        # print(f"Matching {name} against {len(icons_for_slot)} icons for label '{region_label}' at slot {idx_region} with quality {predicted_quality}")
                        if name not in icons_for_slot:
                            # print(f"Skipping {name} against {len(icons_for_slot)} icons for label '{region_label}' at slot {idx_region} with quality {predicted_quality}")
                            continue

                        if icon_color is None:
                            # print(f"Skipping {name} against {len(icons_for_slot)} icons for label '{region_label}' at slot {idx_region} with quality {predicted_quality} as ")
                            continue

                        args = (
                            name,
                            idx,
                            roi,
                            icon_color,
                            predicted_quality,
                            threshold,
                            overlays,
                            region_label,
                            False,
                        )
                        args_list.append(args)

            with ThreadPoolExecutor() as executor:
                for result in executor.map(self.match_single_icon, args_list, chunksize=100):
                    for item in result:
                        matches[item["region"]][item["slot"]].append(item)

            # future_to_args = {}
            # with ProcessPoolExecutor() as executor:
            #     futures = [
            #         executor.submit(self.match_single_icon, args) for args in args_list
            #     ]
            #     for future, args in zip(futures, args_list):
            #         future_to_args[future] = args

            #     for future in as_completed(future_to_args):
            #         args = future_to_args[future]
            #         result = future.result()

            #         for item in result:
            #             matches[item["region"]][item["slot"]].append(item)

            # Fallback pass
            fallback_args_list = []
            for region_label in icon_slots:
                region_filtered_icons = filtered_icons.get(region_label, {})
                if not region_filtered_icons:
                    logger.warning(
                        f"No filtered icons available for region '{region_label}'"
                    )
                    continue

                predicted_qualities = predicted_qualities_by_region.get(
                    region_label, {}
                )

                for slot in icon_slots[region_label]:
                    idx = slot["Slot"]
                    box = slot["Box"]
                    roi = slot["ROI"]

                    if (
                        matches[region_label].get(idx) is not None
                        and len(matches[region_label][idx]) > 0
                    ):
                        # logger.info(f"Skipping {region_label} {idx} as already matched")
                        continue

                    icons_for_slot = found_icons[region_label].get(box, {})
                    if not icons_for_slot:
                        continue

                    fallback_icons = list(icons_for_slot.keys())
                    if not fallback_icons:
                        continue

                    predicted_quality = predicted_qualities[idx]

                    logger.info(
                        f"Fallback matching {len(icons_for_slot.keys())} icons into label '{region_label}' at slot {idx}"
                    )

                    for idx_icon, (name, icon_color) in enumerate(
                        region_filtered_icons.items(), 1
                    ):
                        if name not in icons_for_slot:
                            continue

                        if icon_color is None:
                            continue

                        args = (
                            name,
                            idx,
                            roi,
                            icon_color,
                            predicted_quality,
                            threshold,
                            overlays,
                            region_label,
                            True,
                        )
                        fallback_args_list.append(args)

            future_to_args = {}
            with ProcessPoolExecutor() as executor:
                futures = [
                    executor.submit(self.match_single_icon, args)
                    for args in fallback_args_list
                ]
                for future, args in zip(futures, fallback_args_list):
                    future_to_args[future] = args

                for future in as_completed(future_to_args):
                    args = future_to_args[future]
                    result = future.result()

                    for item in result:
                        matches[item["region"]][item["slot"]].append(item)

        except SISTERError as e:
            raise IconMatchingError(e) from e

        logger.info("Completed all region matches.")
        return matches

    def match_single_icon(self, args):
        (
            name,
            slot_idx,
            roi,
            icon_color,
            predicted_qualities,
            threshold,
            overlays,
            region_label,
            fallback_mode,
        ) = args

        found_matches = []
        matched_candidate_indexes = set()

        
        for quality_idx, predicted_quality in enumerate(predicted_qualities):
            if predicted_quality is None:
                continue

            #print(f"Predicted quality: {predicted_quality}")
            quality = predicted_quality["quality"]
            quality_scale = predicted_quality["scale"]
            quality_method = predicted_quality["method"]

            quality_steps = None
            if predicted_quality["step_x"] is not None and predicted_quality["step_y"] is not None:
                quality_steps = (predicted_quality["step_x"], predicted_quality["step_y"])

            # quality, quality_scale, quality_method = predicted_quality

            if not quality or quality not in overlays:
                return found_matches, matched_candidate_indexes, slot_idx

            scale_factor = None

            #if roi.shape[0] > 43 * 1.1 or roi.shape[1] > 33 * 1.1:
            if roi.shape[0] != 47 or roi.shape[1] != 36:
                scale_factor = min(47 / roi.shape[0], 36 / roi.shape[1])
                roi = cv2.resize(
                    roi.copy(),
                    None,
                    fx=scale_factor,
                    fy=scale_factor,
                    interpolation=cv2.INTER_AREA,
                )

            best_match = None
            method = "ssim-all-overlays-all-scales-fallback"
            quality_used = quality

            if quality == "common":
                best_score = -np.inf
                for overlay_name, overlay_img in overlays.items():
                    blended_icon = apply_overlay(icon_color, overlay_img)
                    match = multi_scale_match(name, roi, blended_icon, threshold=threshold)

                    if match and match[2] > best_score:
                        best_score = match[2]
                        best_match = match
                        quality_used = overlay_name
                        method_suffix = match[4]

                # print(f"quality==common: best_match: {best_match} best_score: {best_score} quality_used: {quality_used}")
            else:
                blended_icon = apply_overlay(icon_color, overlays[quality])
                icon_h, icon_w = icon_color.shape[:2]
                overlay_h, overlay_w = overlays[quality].shape[:2]

                #if icon_h == overlay_h and icon_w == overlay_w and quality_scale:
                scales = [quality_scale]
                method = f"ssim-predicted-overlay-scale"
                # else:
                #     scales = np.linspace(0.6, 0.7, 11)
                #     method = (
                #         "ssim-predicted-overlays-all-scales-icon-size-mismatch-fallback"
                #     )

                if not fallback_mode:
                    best_match = multi_scale_match(
                        name, roi, blended_icon, scales=scales, steps=quality_steps, threshold=threshold
                    )
                else:
                    method = "ssim-predicted-overlay-all-scales-fallback"
                    best_match = multi_scale_match(name, roi, blended_icon, threshold=threshold)

                # print(f"quality!=common: best_match: {best_match} scales: {scales} method: {method}")

            if best_match:
                top_left, size, score, scale, method_suffix = best_match
                gx, gy = top_left
                match_w, match_h = size

                if scale_factor:
                    inv_scale = 1.0 / scale_factor
                    gx = int(np.floor(gx * inv_scale))
                    gy = int(np.floor(gy * inv_scale))
                    match_w = int(np.ceil(match_w * inv_scale)) + 1
                    match_h = int(np.ceil(match_h * inv_scale)) + 1

                found_matches.append(
                    {
                        "region": region_label,
                        "slot": slot_idx,
                        "name": f"{name}",
                        "score": score,
                        "scale": scale,
                        "quality_scale": quality_scale,
                        "quality": quality_used,
                        "method": f"{method}-{method_suffix}",
                    }
                )
                matched_candidate_indexes.add(slot_idx)
                #print(f"Found match for {name} at slot {slot_idx}: {best_match}")
                break

        # print(f"Completed {name} against {total} icons for label '{region_label}' at slot {slot_idx}")
        # print(f"found_matches: {found_matches}")
        return found_matches
