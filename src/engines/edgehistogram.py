import cv2
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
from ..utils.image import apply_overlay, apply_mask

import logging
logger = logging.getLogger(__name__)

class EdgeHistogramEngine:
    def __init__(self, debug=False, icon_loader=None, overlay_loader=None):
        self.debug = debug
        self.load_icons = icon_loader
        self.load_quality_overlays = overlay_loader

    def _edge_map(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        return edges

    def _edge_difference_score(self, edge1, edge2):
        if edge1.shape != edge2.shape:
            return -1.0
        diff = cv2.absdiff(edge1, edge2)
        return 1.0 - (np.mean(diff) / 255.0)

    def identify_overlay(self, region_crop, overlays):
        best_score = -np.inf
        best_quality = None
        best_scale = 1.0

        for quality_name, overlay in overlays.items():
            overlay_rgb = overlay[:, :, :3]
            overlay_alpha = overlay[:, :, 3] / 255.0
            if quality_name == "common" and best_score > 0.6:
                continue

            try:
                region_crop = cv2.resize(region_crop, (overlay_rgb.shape[1], overlay_rgb.shape[0]), interpolation=cv2.INTER_AREA)
                masked_region = (region_crop * overlay_alpha[..., np.newaxis]).astype(np.uint8)
                masked_overlay = (overlay_rgb * overlay_alpha[..., np.newaxis]).astype(np.uint8)

                region_edges = self._edge_map(masked_region)
                overlay_edges = self._edge_map(masked_overlay)
                score = self._edge_difference_score(region_edges, overlay_edges)
            except Exception as e:
                logger.debug(f"[EdgeHist] Masked edge comparison failed: {e}")
                continue

            if score > best_score:
                best_score = score
                best_quality = quality_name

        logger.debug(f"[EdgeHist] Best overlay: {best_quality} with score {best_score:.4f}")
        return best_quality, 1.0, 'edgepixel'

    def _edge_histogram(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        hist = cv2.calcHist([edges], [0], None, [256], [0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        return hist

    def _compare_histograms(self, hist1, hist2):
        return cv2.compareHist(hist1.astype(np.float32), hist2.astype(np.float32), cv2.HISTCMP_CORREL)

    def match_single_icon(self, args):
        name, icon_color, screenshot_color, candidate_regions, predicted_qualities, threshold, overlays, idx, total, region_label, fallback_mode = args
        found_matches = []
        matched_candidate_indexes = set()

        logger.verbose(f"[EdgeHist] Matching icon {idx}/{total} '{name}' in region '{region_label}'")

        for idx_region, (x, y, w, h) in enumerate(candidate_regions):
            quality, _, _ = predicted_qualities[idx_region]
            if not quality or quality not in overlays:
                continue

            roi = screenshot_color[y:y+h, x:x+w]
            roi = apply_mask(roi)

            overlay = overlays[quality]
            blended = apply_overlay(icon_color, overlay)

            try:
                hist_icon = self._edge_histogram(blended)
                hist_roi = self._edge_histogram(roi)
                score = self._compare_histograms(hist_icon, hist_roi)
            except Exception:
                continue

            logger.debug(f"[EdgeHist] Score for '{name}' in region {x},{y},{w},{h}: {score:.4f}")

            if score >= threshold:
                found_matches.append({
                    "name": f"{name} ({quality})",
                    "top_left": (x, y),
                    "bottom_right": (x + w, y + h),
                    "score": score,
                    "scale": 1.0,
                    "quality_scale": 1.0,
                    "method": "edgehist",
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

            logger.info(f"[EdgeHist] Matching {len(icons)} icons against {len(candidate_regions)} candidates for '{region_label}'")
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

        logger.info(f"[EdgeHist] Completed matching.")
        return matches
