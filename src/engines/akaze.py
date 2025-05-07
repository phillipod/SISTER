import cv2
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from ..utils.image import apply_overlay, apply_mask

import logging
logger = logging.getLogger(__name__)

class AKAZEEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None):
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader

    def align_to_common_scale(self, icon_img, roi_img, min_height=128):
        """
        Resize both icon and ROI to roughly match size, and ensure height ≥ min_height.
        Preserves aspect ratio.
        """
        icon_h, icon_w = icon_img.shape[:2]
        roi_h, roi_w = roi_img.shape[:2]

        # Determine target height (at least min_height, or match roi height)
        target_h = max(min_height, max(icon_h, roi_h))

        # Calculate scale factors
        icon_scale = target_h / icon_h
        roi_scale = target_h / roi_h

        return icon_scale, roi_scale

    def match_single_icon(self, args):
        name, icon_color, screenshot_color, candidate_regions, predicted_qualities, threshold, overlays, idx, total, region_label, fallback_mode = args
        found_matches = []
        matched_candidate_indexes = set()

        detector = cv2.AKAZE_create()
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        #print(f"[AKAZE] Matching icon {idx}/{total} '{name}' in region '{region_label}'")

        for idx_region, (x, y, w, h) in enumerate(candidate_regions):
            roi = screenshot_color[y:y+h, x:x+w]
    
            icon_scale, roi_scale = self.align_to_common_scale(icon_color, roi) 
            roi = cv2.resize(roi, None, fx=roi_scale, fy=roi_scale, interpolation=cv2.INTER_AREA)
            #print(f"[AKAZE] Upscaled ROI for '{name}' from {w}x{h} to {roi.shape[1]}x{roi.shape[0]}")

            #roi = apply_mask(roi)
            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            matched_this_region = False

            for quality_name, overlay in overlays.items():
                #blended = icon_color.copy() 
                blended = apply_overlay(icon_color, overlay)
                icon_for_akaze = blended.copy()

                icon_for_akaze = cv2.resize(icon_for_akaze, None, fx=icon_scale, fy=icon_scale, interpolation=cv2.INTER_AREA)

                gray_blended = cv2.cvtColor(icon_for_akaze, cv2.COLOR_BGR2GRAY)

                kp1, des1 = detector.detectAndCompute(gray_blended, None)
                kp2, des2 = detector.detectAndCompute(gray_roi, None)

                #print(f"[AKAZE] Icon '{name}' w/ overlay '{quality_name}' -> kp1: {len(kp1) if kp1 else 0}, kp2: {len(kp2) if kp2 else 0}")

                if des1 is None or des2 is None or len(kp1) == 0 or len(kp2) == 0:
                    continue

                matches = matcher.match(des1, des2)
                matches = sorted(matches, key=lambda x: x.distance)

                if not matches:
                    continue

                top_matches = matches[:10]
                avg_distance = sum(m.distance for m in top_matches) / len(top_matches)
                inv_score = 1 / (1 + avg_distance)

                #print(f"[AKAZE] '{name}' overlay '{quality_name}' score: {inv_score:.4f} (avg distance: {avg_distance:.2f})")

                if inv_score >= threshold:
                    found_matches.append({
                        "name": f"{name} ({quality_name})",
                        "top_left": (x, y),
                        "bottom_right": (x + w, y + h),
                        "score": inv_score,
                        "scale": 1.0,
                        "quality_scale": 1.0,
                        "method": "akaze-feature-matching",
                        "region": region_label
                    })
                    matched_candidate_indexes.add(idx_region)
                    matched_this_region = True
                    break  # Stop after first good match

            #if not matched_this_region:
            #    print(f"[AKAZE] No match found for icon '{name}' in region box {x},{y},{w},{h}")

        return found_matches, matched_candidate_indexes

    def match_all(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.04):
        matches = []
        matched_indexes_global = set()

        for region_label, candidate_regions in icon_slots.items():
            folders = icon_dir_map.get(region_label, [])
            if not folders:
                logger.warning(f"No icon directories found for region '{region_label}'")
                continue

            icons = self.load_icons(folders)
            if not icons:
                logger.warning(f"No icons loaded for label '{region_label}' from folders {folders}")
                continue

            logger.info(f"Matching {len(icons)} icons against {len(candidate_regions)} candidates for label '{region_label}'")

            predicted_qualities = [(None, None, None)] * len(candidate_regions)  # Not used in AKAZE
            args_list = [
                (name, icon_color, screenshot_color, candidate_regions, predicted_qualities, threshold, overlays, idx, len(icons), region_label, False)
                for idx, (name, icon_color) in enumerate(icons.items(), 1)
            ]

            with ProcessPoolExecutor() as executor:
                futures = [executor.submit(self.match_single_icon, args) for args in args_list]
                for future in as_completed(futures):
                    result, matched = future.result()
                    matches.extend(result)
                    matched_indexes_global.update((region_label, idx) for idx in matched)

        logger.info(f"[AKAZE] Completed all region matches.")
        return matches
