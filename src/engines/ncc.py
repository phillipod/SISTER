import cv2
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from ..utils.image import apply_overlay, apply_mask

import logging
logger = logging.getLogger(__name__)

class NCCEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None):
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader

    def _ncc_score(self, template, roi):
        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        return result.max()

    def resize_to_common_height(self, icon_img, roi_img, min_height=128):
        icon_h = icon_img.shape[0]
        roi_h = roi_img.shape[0]
        target_h = max(min_height, max(icon_h, roi_h))

        icon_scale = target_h / icon_h
        roi_scale = target_h / roi_h

        return icon_scale, roi_scale

    def identify_overlay(self, region_crop, overlays, step=1, scales=np.linspace(0.6, 1.0, 40)):
        best_score = -np.inf
        best_quality = None
        best_scale = None
        best_method = None

        for quality_name, overlay in reversed(list(overlays.items())):
            overlay_rgb = overlay[:, :, :3]
            overlay_alpha = overlay[:, :, 3] / 255.0

            for scale in scales:
                resized_rgb = cv2.resize(overlay_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                resized_alpha = cv2.resize(overlay_alpha, (resized_rgb.shape[1], resized_rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

                icon_overlay = (resized_rgb * resized_alpha[..., np.newaxis]).astype(np.uint8)
                icon_scale, roi_scale = self.resize_to_common_height(icon_overlay, region_crop)

                normalized_icon = cv2.resize(icon_overlay, None, fx=icon_scale, fy=icon_scale, interpolation=cv2.INTER_CUBIC)
                normalized_region = cv2.resize(region_crop, None, fx=roi_scale, fy=roi_scale, interpolation=cv2.INTER_CUBIC)

                h, w = normalized_icon.shape[:2]
                H, W = normalized_region.shape[:2]

                if h > H or w > W:
                    continue

                for y in range(0, H - h + 1, step):
                    for x in range(0, W - w + 1, step):
                        roi = normalized_region[y:y+h, x:x+w]

                        try:
                            score = self._ncc_score(normalized_icon, roi)
                        except Exception:
                            continue

                        if score > best_score:
                            best_score = score
                            best_quality = quality_name
                            best_scale = scale
                            best_method = 'ncc'

        logger.debug(f"[NCC] Best overlay: {best_quality} (score={best_score if best_score is not None else 'N/A'}, scale={best_scale if best_scale is not None else 'N/A'})")
        return best_quality, best_scale, best_method

    def match_single_icon(self, args):
        name, icon_color, screenshot_color, candidate_regions, predicted_qualities, threshold, overlays, idx, total, region_label, fallback_mode = args
        found_matches = []
        matched_candidate_indexes = set()

        logger.verbose(f"[NCC] Matching icon {idx}/{total} '{name}' in region '{region_label}'")

        for idx_region, (x, y, w, h) in enumerate(candidate_regions):
            quality, quality_scale, quality_method = predicted_qualities[idx_region]
            if not quality or quality not in overlays:
                continue

            roi = screenshot_color[y:y+h, x:x+w]
            roi = apply_mask(roi)
            matched_this_region = False

            overlay = overlays[quality]
            overlay_rgb = overlay[:, :, :3]

            scales = [quality_scale] if quality_scale and not fallback_mode else np.linspace(0.6, 1.0, 20)

            for scale in scales:
                resized_overlay = cv2.resize(overlay_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

                icon_overlayed = apply_overlay(icon_color, overlay)
                icon_scale, roi_scale = self.resize_to_common_height(icon_overlayed, roi)
                template = cv2.resize(icon_overlayed, None, fx=icon_scale, fy=icon_scale, interpolation=cv2.INTER_CUBIC)
                roi_resized = cv2.resize(roi, None, fx=roi_scale, fy=roi_scale, interpolation=cv2.INTER_CUBIC)

                h_s, w_s = template.shape[:2]
                H, W = roi_resized.shape[:2]

                if h_s > H or w_s > W:
                    continue

                for y_offset in range(0, H - h_s + 1, 1):
                    for x_offset in range(0, W - w_s + 1, 1):
                        roi_crop = roi_resized[y_offset:y_offset+h_s, x_offset:x_offset+w_s]

                        try:
                            score = self._ncc_score(template, roi_crop)
                        except Exception:
                            continue

                        if score >= threshold:
                            found_matches.append({
                                "name": f"{name} ({quality})",
                                "top_left": (x + int(x_offset / roi_scale), y + int(y_offset / roi_scale)),
                                "bottom_right": (x + int((x_offset + w_s) / roi_scale), y + int((y_offset + h_s) / roi_scale)),
                                "score": score,
                                "scale": scale,
                                "quality_scale": quality_scale,
                                "method": f"ncc-{quality_method if quality_method else 'direct'}",
                                "region": region_label
                            })
                            matched_candidate_indexes.add(idx_region)
                            matched_this_region = True
                            break
                    if matched_this_region:
                        break

            if not matched_this_region:
                logger.debug(f"[NCC] No match for '{name}' in region {x},{y},{w},{h}")

        return found_matches, matched_candidate_indexes

    def match_all(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.7):
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

            logger.info(f"[NCC] Matching {len(icons)} icons against {len(candidate_regions)} candidates for '{region_label}'")
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

        logger.info(f"[NCC] Completed matching.")
        return matches