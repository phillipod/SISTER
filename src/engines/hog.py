
import cv2
import numpy as np
from skimage.feature import hog
from skimage.metrics import structural_similarity as ssim
from concurrent.futures import ProcessPoolExecutor, as_completed
from ..utils.image import apply_overlay, apply_mask

import logging
logger = logging.getLogger(__name__)

class HOGEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None):
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader

    def _compute_hog(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        features = hog(gray, orientations=8, pixels_per_cell=(8, 8),
                       cells_per_block=(2, 2), block_norm='L2-Hys', visualize=False, feature_vector=True)
        return features

    def _compare_hog(self, f1, f2):
        if f1.shape != f2.shape:
            return -1.0
        return np.dot(f1, f2) / (np.linalg.norm(f1) * np.linalg.norm(f2))

    def identify_overlay(self, region_crop, overlays):
        best_score = -np.inf
        best_quality = None

        for quality_name, overlay in overlays.items():
            overlay_rgb = overlay[:, :, :3]
            overlay_alpha = overlay[:, :, 3] / 255.0
            try:
                region_crop_resized = cv2.resize(region_crop, (overlay_rgb.shape[1], overlay_rgb.shape[0]))
                masked_region = (region_crop_resized * overlay_alpha[..., np.newaxis]).astype(np.uint8)
                masked_overlay = (overlay_rgb * overlay_alpha[..., np.newaxis]).astype(np.uint8)

                #h1 = self._compute_hog(masked_region)
                #h2 = self._compute_hog(masked_overlay)
                h1 = self._compute_hog(cv2.resize(masked_region, (64, 64)))
                h2 = self._compute_hog(cv2.resize(masked_overlay, (64, 64)))

                score = self._compare_hog(h1, h2)
            except Exception as e:
                logger.debug(f"[HOG] Overlay HOG comparison failed: {e}")
                continue

            if score > best_score:
                best_score = score
                best_quality = quality_name

        logger.debug(f"[HOG] Best overlay: {best_quality} with score {best_score:.4f}")
        return best_quality, 1.0, 'hog'

    # def identify_overlay(self, region_crop, overlays, step=1, scales=np.linspace(0.6, 1.0, 40)):
    #     if "common" in overlays:
    #         base_overlay = overlays["common"]
    #         oh, ow = base_overlay.shape[:2]
    #         rh, rw = region_crop.shape[:2]
    #         if rh > 43 * 1.1 or rw > 33 * 1.1:
    #             scale_factor = min(43 / rh, 33 / rw)
    #             region_crop = cv2.resize(region_crop, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
    #             #logger.debug(f"Resized region_crop to {region_crop.shape[:2]} using scale factor {scale_factor:.2f}")


    #     best_score = -np.inf
    #     best_quality = None
    #     best_scale = None
    #     best_method = None
    #     for quality_name, overlay in reversed(list(overlays.items())):
    #         if quality_name == "common" and best_score > 0.6: 
    #             continue
    #         #logger.debug(f"Trying quality overlay {quality_name}")

    #         overlay_rgb = overlay[:, :, :3]
    #         overlay_alpha = overlay[:, :, 3] / 255.0

    #         for scale in scales:
    #             #logger.debug(f"Trying scale {scale}")
    #             resized_rgb = cv2.resize(overlay_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    #             resized_alpha = cv2.resize(overlay_alpha, (resized_rgb.shape[1], resized_rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

    #             h, w = resized_rgb.shape[:2]
    #             H, W = region_crop.shape[:2]

    #             if h > H or w > W:
    #                 continue

    #             for y in range(0, H - h + 1, step):
    #                 for x in range(0, W - w + 1, step):
    #                     roi = region_crop[y:y+h, x:x+w]

    #                     masked_region = (roi * resized_alpha[..., np.newaxis]).astype(np.uint8)
    #                     masked_overlay = (resized_rgb * resized_alpha[..., np.newaxis]).astype(np.uint8)

    #                     try:
    #                         score = ssim(masked_region, masked_overlay, channel_axis=-1)
    #                     except ValueError:
    #                         continue

    #                     #logger.debug(f"Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")
    #                     if score > best_score:
    #                         best_score = score
    #                         best_quality = quality_name
    #                         best_scale = scale
    #                         best_method = 'ssim'

    #     #logger.debug(f"Best matched overlay: {best_quality} with score {best_score:.4f} at scale {best_score if best_score is not None else 'N/A'} using {best_method}")
    #     return best_quality, best_scale, best_method

    def match_single_icon(self, args):
        name, icon_color, screenshot_color, candidate_regions, predicted_qualities, threshold, overlays, idx, total, region_label, fallback_mode = args
        found_matches = []
        matched_candidate_indexes = set()

        logger.verbose(f"[HOG] Matching icon {idx}/{total} '{name}' in region '{region_label}'")

        for idx_region, (x, y, w, h) in enumerate(candidate_regions):
            quality, _, _ = predicted_qualities[idx_region]
            if not quality or quality not in overlays:
                continue

            roi = screenshot_color[y:y+h, x:x+w]
            roi = apply_mask(roi)

            overlay = overlays[quality]
            blended = apply_overlay(icon_color, overlay)

            try:
                h1 = self._compute_hog(cv2.resize(blended, (64, 64)))
                h2 = self._compute_hog(cv2.resize(roi, (64, 64)))
                score = self._compare_hog(h1, h2)
            except Exception as e:
                logger.debug(f"[HOG] Match comparison failed: {e}")
                continue

            logger.debug(f"[HOG] Score for '{name}' in region {x},{y},{w},{h}: {score:.4f}")

            if score >= threshold:
                found_matches.append({
                    "name": f"{name} ({quality})",
                    "top_left": (x, y),
                    "bottom_right": (x + w, y + h),
                    "score": score,
                    "scale": 1.0,
                    "quality_scale": 1.0,
                    "method": "hog",
                    "region": region_label
                })
                matched_candidate_indexes.add(idx_region)

        return found_matches, matched_candidate_indexes

    def match_all(self, screenshot_color, build_info, icon_slots, icon_dir_map, overlays, threshold=0.85):
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

            logger.info(f"[HOG] Matching {len(icons)} icons against {len(candidate_regions)} candidates for '{region_label}'")
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

        logger.info(f"[HOG] Completed matching.")
        return matches
