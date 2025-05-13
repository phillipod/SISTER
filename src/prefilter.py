import logging
from pathlib import Path

# Import available engines
from .prefilters.phash import PHashEngine

# from .engines.dhash import DHashEngine  # future support

logger = logging.getLogger(__name__)

ENGINE_CLASSES = {
    "phash": PHashEngine,
    # "dhash": DHashEngine,
}


class IconPrefilter:
    def __init__(self, hash_index=None, debug=False, engine_type="phash"):
        """
        IconPrefilter runner that delegates to a selected engine.

        Args:
            debug (bool): Enable debug mode.
            engine_type (str): Engine backend to use. Options: 'phash', etc.
        """
        self.debug = debug
        self.found_icons = None
        self.filtered_icons = None

        engine_key = engine_type.lower()

        try:
            self.engine = ENGINE_CLASSES[engine_key](debug=debug, hash_index=hash_index)

            self.engine_type = engine_key
        except KeyError as e:
            raise HashIndexError(f"Unknown hasher '{hasher_key}'") from e

        logger.info(f"[IconPrefilter] Using engine: {self.engine_type}")

    # def load_icons(self, icon_folders):
    #     icons = {}
    #     for folder in icon_folders:
    #         if not os.path.exists(folder):
    #             continue
    #         for filename in os.listdir(folder):
    #             if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
    #                 path = os.path.join(folder, filename)
    #                 icon = cv2.imread(path, cv2.IMREAD_COLOR)
    #                 if icon is not None:
    #                     icons[filename] = icon
    #     return icons

    def icon_predictions(self, icon_slots, icon_set):
        """
        Run icon matching using the selected engine.
        """
        (
            self.predicted_icons,
            self.found_icons,
            self.filtered_icons,
        ) = self.engine.icon_predictions(icon_slots, icon_set)

        logger.info(
            f"[IconPrefilter] Total icon predictions: {sum(len(slots) for region in self.predicted_icons.values() for slots in region.values())}"
        )      

        # if self.debug:
        #     debug_img = screenshot_color.copy()
        #     for match in matches:
        #         cv2.rectangle(debug_img, match["top_left"], match["bottom_right"], (0, 255, 0), 2)
        #     os.makedirs("output", exist_ok=True)
        #     cv2.imwrite("output/debug_matched_icons.png", debug_img)

        return self.predicted_icons
