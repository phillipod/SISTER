# sister.py
import os
import json
from pathlib import Path
from collections import defaultdict
import traceback

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

    def download_icons(self):
        """Download all icons for equipment, personal traits, and starship traits from STO wiki."""
        try:
            self.cargo.download_icons(self.config["icon_dir"])
        except Exception as e:
            print(f"Error downloading icons: {e}")

    def build_phash_cache(self, overlays_dir):
        """Build a perceptual hash (phash) cache for all icons."""
        try:
            overlays = self.load_overlays(overlays_dir)
            self.hash_index.build_with_overlays(overlays)
            print(f"[DONE] Built PHash index with {len(self.hash_index.hashes)} entries.")
        except Exception as e:
            print(f"Error building PHash cache: {e}")

    def save_match_summary(self, output_dir, screenshot_path, slots, matches):
        """Save the match results to a text file."""
        try:
            base_name = Path(screenshot_path).stem
            output_file = Path(output_dir) / f"{base_name}_matches.txt"

            matches_by_region_slot = defaultdict(lambda: defaultdict(list))

            for match in matches:
                region = match["region"]
                top_left = match["top_left"]
                matches_by_region_slot[region][top_left].append(match)

            with open(output_file, "w") as f:
                for region, slots in matches_by_region_slot.items():
                    f.write(f"=== Region: {region} ===\n")
                    for slot, slot_matches in slots.items():
                        best = max(slot_matches, key=lambda m: m["score"])
                        f.write(f"  BEST: {best['name']} (score {best['score']:.2f})\n")
            print(f"Saved match summary to {output_file}")
        except Exception as e:
            print(f"Error saving match summary: {e}")

    def load_overlays(self, overlays_dir):
        """Load quality overlays."""
        try:
            return load_quality_overlays(overlays_dir)
        except Exception as e:
            print(f"Error loading overlays: {e}")

    def match_icons(self, screenshot, build_info, slots, icon_dir_map, overlays, threshold):
        """Perform icon matching for the given screenshot and slots."""
        try:
            matches = self.icon_matcher.match_all(
                screenshot, build_info, slots, icon_dir_map, overlays, threshold=threshold
            )
            print(f"Found {len(matches)} matches")
            return matches
        except Exception as e:
            print(f"Error during icon matching: {e}")
            return []

    def _trigger(self, event_name, payload):
        if event_name in self.callbacks:
            self.callbacks[event_name](payload)
