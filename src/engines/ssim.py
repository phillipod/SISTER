import os
import cv2
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from skimage.metrics import structural_similarity as ssim
#from collections import Counter, defaultdict

from ..utils.image import apply_overlay, apply_mask

import logging

logger = logging.getLogger(__name__)

class SSIMEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None):
        """
        Initialize the IconMatcher.

        Args:
            debug (bool): If True, enables debug logging.
        """

        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader

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

                        #logger.debug(f"Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")
                        if score > best_score:
                            best_score = score
                            best_quality = quality_name
                            best_scale = scale
                            best_method = 'ssim'

        logger.debug(f"Best matched overlay: {best_quality} with score {best_score:.4f} at scale {best_scale:.2f} using {best_method}")
        return best_quality, best_scale, best_method

 
    def match_single_icon(self, args):
        name, icon_color, screenshot_color, candidate_regions, predicted_qualities, threshold, overlays, idx, total, region_label, fallback_mode = args
        found_matches = []
        matched_candidate_indexes = set()

        logger.verbose(f"Matching icon {idx}/{total} '{name}' in region '{region_label}'")
        
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
                    "name": f"{name} ({quality_used})",
                    "top_left": (x + gx, y + gy),
                    "bottom_right": (x + gx + match_w, y + gy + match_h),
                    "score": score,
                    "scale": scale,
                    "quality_scale": quality_scale,
                    "method": method,
                    "region": region_label
                })
                matched_candidate_indexes.add(idx_region)

        return found_matches, matched_candidate_indexes

    def match_all(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.8):
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

            # Precompute overlay quality once per candidate region
            predicted_qualities = [
                self.identify_overlay(screenshot_color[y:y+h, x:x+w], overlays)
                for (x, y, w, h) in candidate_regions
            ]

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

            # Fallback matcher using the same predicted overlays using full scales, not predicted scales
            unmatched_regions = [region for idx, region in enumerate(candidate_regions)
                                 if (region_label, idx) not in matched_indexes_global]

            if unmatched_regions:
                logger.info(f"Fallback matching {len(icons)} icons against {len(unmatched_regions)} candidates for label '{region_label}'")

                fallback_args_list = [
                    (name, icon_color, screenshot_color, unmatched_regions, [predicted_qualities[idx] for idx, _ in enumerate(candidate_regions) if (region_label, idx) not in matched_indexes_global], threshold, overlays, idx, len(icons), region_label, True)
                    for idx, (name, icon_color) in enumerate(icons.items(), 1)
                ]

                with ProcessPoolExecutor() as executor:
                    futures = [executor.submit(self.match_single_icon, args) for args in fallback_args_list]
                    for future in as_completed(futures):
                        result, _ = future.result()
                        matches.extend(result)

        logger.info(f"Completed all region matches.")

        return matches

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

 