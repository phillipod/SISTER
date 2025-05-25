import os
import cv2
import numpy as np
import logging

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

from ..metrics.ms_ssim import multi_scale_match
from ..utils.image import apply_overlay


from ..exceptions import SISTERError


logger = logging.getLogger(__name__)


class IconDetector:
    def __init__(self, debug=False, on_progress=None, executor_pool=None):
        """
        IconDetector runner that delegates to a selected engine.

        Args:
            debug (bool): Enable debug mode.
        """
        self.debug = debug
        self.on_progress = on_progress
        self.executor_pool = executor_pool


    def load_icons(self, icon_folders):
        icons = {}
        for folder in icon_folders:
            if not os.path.exists(folder):
                continue
            for filename in os.listdir(folder):
                if filename.lower().endswith((".png", ".jpg", ".jpeg")):
                    path = os.path.join(folder, filename)
                    icon = cv2.imread(path, cv2.IMREAD_COLOR)
                    if icon is not None:
                        icons[filename] = icon
        return icons

    def load_overlays(self, overlay_folder):
        overlays = {}
        for name in [
            "common.png",
            "uncommon.png",
            "rare.png",
            "very rare.png",
            "ultra rare.png",
            "epic.png",
        ]:
            path = os.path.join(overlay_folder, name)
            if os.path.exists(path):
                overlay = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                overlays[name.split(".")[0]] = overlay
        return overlays

    def detect(
        self,
        icon_slots,
        icon_dir_map,
        overlays,
        detected_overlays_by_icon_group,
        filtered_icons,
        found_icons,
        threshold=0.7,
    ):
        """
        Run icon detector using the selected engine.
        """
        matches = {}

        try:
            args_list = []
            self.on_progress("Detecting icons", 10.0)
            for icon_group_label in icon_slots:
                matches[icon_group_label] = {}

                icon_group_filtered_icons = filtered_icons.get(icon_group_label, {})
                if not icon_group_filtered_icons:
                    logger.warning(
                        f"No filtered icons available for icon group '{icon_group_label}'"
                    )
                    continue

                detected_overlays = detected_overlays_by_icon_group.get(
                    icon_group_label, {}
                )
                if len(detected_overlays.keys()) != len(icon_slots[icon_group_label]):
                    logger.warning(
                        f"Mismatch between candidate icon groups and detected overlays for '{icon_group_label}'"
                    )

                for slot in icon_slots[icon_group_label]:
                    idx = slot["Slot"]
                    box = slot["Box"]
                    roi = slot["ROI"]

                    if idx not in matches[icon_group_label]:
                        matches[icon_group_label][idx] = []

                    icons_for_slot = found_icons[icon_group_label].get(box, {})
                    # print(f"icons_for_slot: {icons_for_slot}")

                    if not icons_for_slot:
                        continue

                    detected_overlay = detected_overlays[idx]

                    logger.info(
                        f"Matching {len(icons_for_slot)} icons into icon group '{icon_group_label}' at slot {idx} with overlay {detected_overlay[0]["overlay"]} at scale {detected_overlay[0]['scale']}"
                    )

                    for idx_icon, (name, icon_color) in enumerate(
                        icon_group_filtered_icons.items(), 1
                    ):
                        # print(f"Matching {name} against {len(icons_for_slot)} icons for label '{icon_group_label}' at slot {idx_icon_group} with overlay {detected_overlay}")
                        if name not in icons_for_slot:
                            # print(f"Skipping {name} against {len(icons_for_slot)} icons for label '{icon_group_label}' at slot {idx_icon_group} with overlay {detected_overlay}")
                            continue

                        if icon_color is None:
                            # print(f"Skipping {name} against {len(icons_for_slot)} icons for label '{icon_group_label}' at slot {idx_icon_group} with overlay {detected_overlay} as ")
                            continue

                        args = (
                            name,
                            idx,
                            roi,
                            icon_color,
                            detected_overlay,
                            threshold,
                            overlays,
                            icon_group_label,
                            False,
                        )
                        args_list.append(args)

            start_pct = 10.0
            end_pct   = 65.0

            self.on_progress("Detecting icons", start_pct)

            args_total     = len(args_list)
            args_completed = 0
            for result in self.executor_pool.map(
                match_single_icon, args_list, chunksize=10
            ):
                for item in result:
                    matches[item["icon_group"]][item["slot"]].append(item)
                
                args_completed += 1
                
                if args_completed % 10 == 0 or args_completed == args_total:
                    frac       = args_completed / args_total
                    scaled_pct = start_pct + frac * (end_pct - start_pct)

                    sub = f"{args_completed}/{args_total}"
                    self.on_progress(f"Detecting icons -> {sub}", scaled_pct)

            # Fallback pass
            fallback_args_list = []
            for icon_group_label in icon_slots:
                icon_group_filtered_icons = filtered_icons.get(icon_group_label, {})
                if not icon_group_filtered_icons:
                    logger.warning(
                        f"No filtered icons available for icon group '{icon_group_label}'"
                    )
                    continue

                detected_overlays = detected_overlays_by_icon_group.get(
                    icon_group_label, {}
                )

                for slot in icon_slots[icon_group_label]:
                    idx = slot["Slot"]
                    box = slot["Box"]
                    roi = slot["ROI"]

                    if (
                        matches[icon_group_label].get(idx) is not None
                        and len(matches[icon_group_label][idx]) > 0
                    ):
                        # logger.info(f"Skipping {icon_group_label} {idx} as already matched")
                        continue

                    icons_for_slot = found_icons[icon_group_label].get(box, {})
                    if not icons_for_slot:
                        continue

                    fallback_icons = list(icons_for_slot.keys())
                    if not fallback_icons:
                        continue

                    detected_overlay = detected_overlays[idx]

                    logger.info(
                        f"Fallback matching {len(icons_for_slot.keys())} icons into icon group '{icon_group_label}' at slot {idx}"
                    )

                    for idx_icon, (name, icon_color) in enumerate(
                        icon_group_filtered_icons.items(), 1
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
                            detected_overlay,
                            threshold,
                            overlays,
                            icon_group_label,
                            True,
                        )
                        fallback_args_list.append(args)

            start_pct = 66.0
            end_pct   = 95.0

            self.on_progress("Detecting icons(Fallback pass)", start_pct)

            args_total     = len(fallback_args_list)
            args_completed = 0

            for result in self.executor_pool.map(
                match_single_icon, fallback_args_list, chunksize=10
            ):
                for item in result:
                    matches[item["icon_group"]][item["slot"]].append(item)
                
                args_completed += 1
                
                if args_completed % 10 == 0 or args_completed == args_total:
                    frac       = args_completed / args_total
                    scaled_pct = start_pct + frac * (end_pct - start_pct)

                    sub = f"{args_completed}/{args_total}"
                    self.on_progress(f"Detecting icons(Fallback pass) -> {sub}", scaled_pct)

        except SISTERError as e:
            raise IconDetectorError(e) from e

        self.on_progress("Finalising", 99.0)

        match_count = 0
        methods = {}
        for icon_group in matches.keys():
            for slot in matches[icon_group].keys():
                match_count += len(matches[icon_group][slot])
                for candidate in matches[icon_group][slot]:
                    method = candidate["method"]
                    methods[candidate["method"]] = (
                        methods.get(candidate["method"], 0) + 1
                    )

        logger.verbose(f"[IconDetector] Total matches: {match_count}")

        for method, count in methods.items():
            logger.verbose(f"Summary: {count} matches via {method}")

        if self.debug:
            debug_img = screenshot_color.copy()
            for match in matches:
                cv2.rectangle(
                    debug_img, match["top_left"], match["bottom_right"], (0, 255, 0), 2
                )
            os.makedirs("output", exist_ok=True)
            cv2.imwrite("output/debug_matched_icons.png", debug_img)

        return matches

def match_single_icon(args):
    (
        name,
        slot_idx,
        roi,
        icon_color,
        detected_overlays,
        threshold,
        overlays,
        icon_group_label,
        fallback_mode,
    ) = args

    found_matches = []
    matched_candidate_indexes = set()

    for overlay_idx, detected_overlay in enumerate(detected_overlays):
        if detected_overlay is None:
            continue

        # print(f"Detected overlay: {detected_overlay}")
        overlay = detected_overlay["overlay"]
        overlay_scale = detected_overlay["scale"]
        overlay_method = detected_overlay["method"]

        overlay_steps =None
        if (
            detected_overlay["step_x"] is not None
            and detected_overlay["step_y"] is not None
        ):
            overlay_steps =(
                detected_overlay["step_x"],
                detected_overlay["step_y"],
            )

        # overlay, overlay_scale, overlay_method =detected_overlay

        if not overlay or overlay not in overlays:
            return found_matches, matched_candidate_indexes, slot_idx

        scale_factor = None

        # if roi.shape[0] > 43 * 1.1 or roi.shape[1] > 33 * 1.1:
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
        overlay_used = overlay

        if overlay == "common":
            best_score = -np.inf

            if icon_group_label in ("Personal Space Traits", "Personal Ground Traits", "Starship Traits", "Space Reputation", "Ground Reputation", "Active Space Reputation", "Active Ground Reputation"):
                scales = np.linspace(0.6, 0.7, 11)
                method = (
                    "ssim-detected-overlays-all-scales"
                )

                best_match = multi_scale_match(
                    name,
                    roi,
                    icon_color,
                    scales=scales,
                    threshold=threshold,
                )

            else:
                for overlay_name, overlay_img in overlays.items():
                    blended_icon = apply_overlay(icon_color, overlay_img)
                    match = multi_scale_match(
                        name, roi, blended_icon, threshold=threshold
                    )

                    if match and match[2] > best_score:
                        best_score = match[2]
                        best_match = match
                        overlay_used = overlay_name
                        method_suffix = match[4]

            # print(f"overlay==common: best_match: {best_match} best_score: {best_score} overlay_used:{overlay_used}")
        else:
            blended_icon = apply_overlay(icon_color, overlays[overlay])
            icon_h, icon_w = icon_color.shape[:2]
            overlay_h, overlay_w = overlays[overlay].shape[:2]

            # if icon_h == overlay_h and icon_w == overlay_w and overlay_scale:
            scales = [overlay_scale]
            method = f"ssim-detected-overlay-scale"
            # else:
            #     scales = np.linspace(0.6, 0.7, 11)
            #     method = (
            #         "ssim-detected-overlays-all-scales-icon-size-mismatch-fallback"
            #     )

            if not fallback_mode:
                best_match = multi_scale_match(
                    name,
                    roi,
                    blended_icon,
                    scales=scales,
                    steps=overlay_steps,
                    threshold=threshold,
                )
            else:
                method = "ssim-detected-overlay-all-scales-fallback"
                best_match = multi_scale_match(
                    name, roi, blended_icon, threshold=threshold
                )

            # print(f"overlay!=common: best_match: {best_match} scales: {scales} method: {method}")

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
                    "icon_group": icon_group_label,
                    "slot": slot_idx,
                    "name": f"{name}",
                    "score": score,
                    "scale": scale,
                    "overlay_scale": overlay_scale,
                    "overlay": overlay_used,
                    "method": f"{method}-{method_suffix}",
                }
            )
            matched_candidate_indexes.add(slot_idx)
            # print(f"Found match for {name} at slot {slot_idx}: {best_match}")
            break

    # print(f"Completed {name} against {total} icons for label '{icon_group_label}' at slot {slot_idx}")
    # print(f"found_matches: {found_matches}")
    return found_matches
