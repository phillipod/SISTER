import os
import logging
from collections import Counter
import cv2

# Import available engines
from ..matching.ssim import SSIMEngine

logger = logging.getLogger(__name__)

ENGINE_CLASSES = {"ssim": SSIMEngine}


class IconMatcher:
    def __init__(self, hash_index=None, debug=False, engine_type="ssim"):
        """
        IconMatcher runner that delegates to a selected engine.

        Args:
            debug (bool): Enable debug mode.
            engine_type (str): Engine backend to use. Options: 'ssim', 'phash', etc.
        """
        self.debug = debug

        self.engine_type = engine_type.lower()

        if self.engine_type not in ENGINE_CLASSES:
            raise ValueError(
                f"Unsupported engine type: '{engine_type}'. Supported: {list(ENGINE_CLASSES.keys())}"
            )

        self.engine = ENGINE_CLASSES[self.engine_type](
            debug=debug,
            icon_loader=self.load_icons,
            overlay_loader=self.load_quality_overlays,
            hash_index=hash_index,
        )
        logger.info(f"[IconMatcher] Using engine: {self.engine_type}")

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

    def load_quality_overlays(self, overlay_folder):
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

    def match_all(
        self,
        icon_slots,
        icon_dir_map,
        overlays,
        predicted_qualities,
        filtered_icons,
        found_icons,
        threshold=0.7,
    ):
        """
        Run icon matching using the selected engine.
        """
        matches = self.engine.match_all(
            icon_slots,
            icon_dir_map,
            overlays,
            predicted_qualities,
            filtered_icons,
            found_icons,
            threshold,
        )

        match_count = 0
        methods = {}
        for region in matches.keys():
            for slot in matches[region].keys():
                match_count += len(matches[region][slot])
                for candidate in matches[region][slot]:
                    method = candidate["method"]
                    methods[candidate["method"]] = (
                        methods.get(candidate["method"], 0) + 1
                    )

        logger.info(f"[IconMatcher] Total matches: {match_count}")

        for method, count in methods.items():
            logger.info(f"Summary: {count} matches via {method}")

        if self.debug:
            debug_img = screenshot_color.copy()
            for match in matches:
                cv2.rectangle(
                    debug_img, match["top_left"], match["bottom_right"], (0, 255, 0), 2
                )
            os.makedirs("output", exist_ok=True)
            cv2.imwrite("output/debug_matched_icons.png", debug_img)

        return matches

    def quality_predictions(
        self,
        icon_slots,
        overlays,
        threshold=0.8,
    ):
        """
        Run icon matching using the selected engine.
        """
        self.predicted_qualities = self.engine.quality_predictions(
            icon_slots, overlays, threshold
        )

        logger.info(
            f"[IconMatcher] Total quality predictions: {sum(len(slots) for slots in self.predicted_qualities.values())}"
        )

        # if self.debug:
        #     debug_img = screenshot_color.copy()
        #     for match in matches:
        #         cv2.rectangle(debug_img, match["top_left"], match["bottom_right"], (0, 255, 0), 2)
        #     os.makedirs("output", exist_ok=True)
        #     cv2.imwrite("output/debug_matched_icons.png", debug_img)

        return self.predicted_qualities
