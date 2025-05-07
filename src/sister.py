# sister.py
from cargo import CargoDownloader
from locator import LabelLocator
from classifier import BuildClassifier
from region import RegionDetector
from iconslot import IconSlotDetector
from iconmatch import IconMatcher
from hashindex import HashIndex
from utils.image import load_image, load_quality_overlays

class SISTER:
    def __init__(self, config=None, callbacks=None):
        self.config = config or {}
        self.callbacks = callbacks or {}

        # Initialize components
        self.hash_index = HashIndex(config["icon_dir"], hasher="phash")  # assumes icon_dir in config

        self.classifier = BuildClassifier(debug=config.get("debug", False))
        self.cargo = CargoDownloader(force_download=config.get("force_download", False))
        self.label_locator = LabelLocator(gpu=config.get("gpu", False), debug=config.get("debug", False))
        self.region_detector = RegionDetector(debug=config.get("debug", False))
        self.icon_slot_detector = IconSlotDetector(debug=config.get("debug", False))
        self.icon_matcher = IconMatcher(hash_index=self.hash_index, debug=config.get("debug", False))

        
    def run_pipeline(self, image_input):
        try:
            screenshot = load_image(image_input, resize_fullhd=True)
            labels = self.label_locator.locate_labels(screenshot)
            self._trigger("on_labels_detected", labels)

            build_info = self.classifier.classify(labels)
            self._trigger("on_build_classified", build_info)

            regions = self.region_detector.detect(screenshot, build_info, labels)
            self._trigger("on_regions_detected", regions)

            slots = self.icon_slot_detector.detect(screenshot, build_info, regions)
            self._trigger("on_slots_detected", slots)

            return slots #final_matches
        except Exception as e:
            self._trigger("on_error", e)
            raise

    def load_icons(self):
        # Logic to load icons from disk/cache
        ...

    def load_overlays(self):
        # Load quality overlays
        ...

    def _trigger(self, event_name, payload):
        if event_name in self.callbacks:
            self.callbacks[event_name](payload)
