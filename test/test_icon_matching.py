import os
import json
import argparse
import traceback
import cv2
import time 
from pathlib import Path
from collections import Counter, defaultdict

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.locator import LabelLocator
from src.classifier import BuildClassifier
from src.region import RegionDetector
from src.iconslot import IconSlotDetector
from src.iconmatch import IconMatcher
from src.cargo import CargoDownloader

from log_config import setup_logging


def build_icon_dir_map(images_root):
    """
    Build a mapping of label names (from LabelLocator) to image subdirectories.

    Handles special cases:
      - Fore and Aft Weapons map to unrestricted weapons
      - Tactical, Engineering, and Science Consoles also include universal consoles

    Args:
        images_root (Path): Root directory where icons are stored.

    Returns:
        dict: Mapping from region label to list of directories.
    """
    return {
        "ship": {
            "Fore Weapon": [images_root / 'space/weapons/fore', images_root / 'space/weapons/unrestricted'],
            "Aft Weapon": [images_root / 'space/weapons/aft', images_root / 'space/weapons/unrestricted'],
            "Experimental Weapon": [images_root / 'space/weapons/experimental'],
            "Shield": [images_root / 'space/shield'],
            "Secondary Deflector": [images_root / 'space/secondary_deflector'],
            "Deflector": [images_root / 'space/deflector', images_root / 'space/secondary_deflector'], # Console doesn't have a specific label for Secondary Deflector, it's located under the Deflector label.
            "Impulse": [images_root / 'space/impulse'],
            "Warp": [images_root / 'space/warp'],
            "Singularity": [images_root / 'space/singularity'],
            "Hangar": [images_root / 'space/hangar'],
            "Devices": [images_root / 'space/device'],
            "Universal Console": [images_root / 'space/consoles/universal', images_root / 'space/consoles/engineering', images_root / 'space/consoles/tactical', images_root / 'space/consoles/science'],
            "Engineering Console": [images_root / 'space/consoles/engineering', images_root / 'space/consoles/universal'],
            "Tactical Console": [images_root / 'space/consoles/tactical', images_root / 'space/consoles/universal'],
            #"Tactical Console": [images_root / 'space/consoles/test'],
            "Science Console": [images_root / 'space/consoles/science', images_root / 'space/consoles/universal']
        },
        "pc_ground": {
            "Body": [images_root / 'ground/armor'],
            "Shield": [images_root / 'ground/shield'],
            "EV Suit": [images_root / 'ground/ev_suit'],
            "Kit Modules": [images_root / 'ground/kit_module'],
            "Kit": [images_root / 'ground/kit'],
            "Devices": [images_root / 'ground/device'],
            "Weapon": [images_root / 'ground/weapon'],
        },
        "console_ground": {
            "Body": [images_root / 'ground/armor'],
            "Shield": [images_root / 'ground/shield'],
            "EV Suit": [images_root / 'ground/ev_suit'],
            "Kit": [images_root / 'ground/kit_module'], # Console swaps "Kit Modules" to "Kit"
            "Kit Frame": [images_root / 'ground/kit'], # And "Kit" becomes "Kit Frame"
            "Devices": [images_root / 'ground/device'],
            "Weapon": [images_root / 'ground/weapon'],
        },
        "inventory": { "Inventory": [ p for p in images_root.rglob('*') if p.is_dir() ] }
    }

def main():
    parser = argparse.ArgumentParser(description="Run full SISTER pipeline including icon matching.")
    parser.add_argument("--gpu", action="store_true", help="Use GPU for OCR.")
    parser.add_argument("--debug", action="store_true", help="Enable debug images.")
    parser.add_argument("--input-dir", default="./", help="Directory containing test screenshots.")
    parser.add_argument("--output-dir", default="output/icon_matching", help="Directory to save debug output images.")
    parser.add_argument("--icon-dir", default="../images", help="Directory containing icon images.")
    parser.add_argument("--overlay-dir", default="../overlays", help="Directory containing icon overlay images.")
    parser.add_argument("--log-level", default="WARNING", help="Set log level: DEBUG, VERBOSE, INFO, WARNING, ERROR.")
    parser.add_argument("--logfile", default="../log/sister.log", help="File to write log output.")
    parser.add_argument("--iconmatch-debug", action="store_true", help="Allow DEBUG to include debug output for icon matching (VERY verbose).")
    args = parser.parse_args()

    setup_logging(log_level=args.log_level, log_file=args.logfile, allow_iconmatch_debug=args.iconmatch_debug)

    os.makedirs(args.output_dir, exist_ok=True)

    locator = LabelLocator(gpu=args.gpu, debug=args.debug)
    classifier = BuildClassifier(debug=args.debug)
    detector = RegionDetector(debug=args.debug)
    icon_finder = IconSlotDetector(debug=args.debug)
    matcher = IconMatcher(debug=args.debug)

    icon_dir_map_master = build_icon_dir_map(Path(args.icon_dir))

    sample_images = {
        #"sets_space_1.png": "SETS Ship Build",
        #"screenshot_space_1.png": "PC Ship Build",
        #"screenshot_space_2.png": "Unknown",
        #"screenshot_space_3.png": "PC Ship Build",
        "screenshot_ground_1.png": "PC Ground Build",
        #"screenshot_ground_2.png": "PC Ground Build",
        #"screenshot_ground_3.png": "PC Ground Build",
        #"screenshot_console_ground_1.png": "Console Ground Build",
        #"screenshot_console_ground_2.png": "Unknown",
        #"screenshot_console_space_1.png": "Console Ship Build",
        #"screenshot_console_space_2.png": "Console Ship Build",
        #"screenshot_console_space_3.png": "Unknown",
        #"screenshot_console_space_4.png": "Console Ship Build",
        #"screenshot_console_space_5.png": "Console Ship Build",
        #"screenshot_console_space_6.png": "Console Ship Build",
        #"screenshot_inventory_1.png": "Inventory",

    }

    for image_name, expected_type in sample_images.items():
        input_path = os.path.join(args.input_dir, image_name)
        base_name = os.path.splitext(image_name)[0]
        output_path = os.path.join(args.output_dir, f"debug_{image_name}")
        output_json_path = os.path.join(args.output_dir, f"debug_{base_name}.json")
        region_debug_path = os.path.join(args.output_dir, f"region_{image_name}")
        icon_debug_path = os.path.join(args.output_dir, f"icons_{image_name}")

        print(f"Processing {input_path}... (Expected: {expected_type})")
        try:
            timings = {}

            image = cv2.imread(input_path)

            labels = None
            build_info = None

            if "Inventory" in expected_type:
                detected_type = "Inventory"
            else:
                t0 = time.perf_counter()
                labels = locator.locate_labels(input_path, output_path if args.debug else None)
                timings["Label Location"] = time.perf_counter() - t0
                print(f"Found {len(labels)} labels.")

                t1 = time.perf_counter()
                build_info = classifier.classify(labels)
                timings["Build Classification"] = time.perf_counter() - t1
                detected_type = build_info["build_type"]
                print(f"Detected Build Type: {detected_type}")

            if detected_type == expected_type:
                print(f"[PASS] Classification matches expected.")
            else:
                print(f"[FAIL] Expected '{expected_type}', got '{detected_type}'")

            region_data = {}
            icon_slots = {}
            matches = []

            icon_set = None
            if "Ship Build" in detected_type:
                icon_set = "ship"
            elif "PC Ground Build" in detected_type:
                icon_set = "pc_ground"
            elif "Console Ground Build" in detected_type:
                icon_set = "console_ground"
            elif "Inventory" in detected_type:
                icon_set = "inventory"

            if "PC Ship Build" in detected_type or "PC Ground Build" in detected_type or "Console Ship Build" in detected_type or "Console Ground Build" in detected_type:
                t2 = time.perf_counter()
                region_data = detector.detect(image, build_info, labels, debug_output_path=region_debug_path)
                timings["Region Detection"] = time.perf_counter() - t2

                t3 = time.perf_counter()
                icon_slots = icon_finder.detect(image, build_info, region_data, debug_output_path=icon_debug_path)
                timings["Icon Slot Detection"] = time.perf_counter() - t3
            elif "Inventory" in detected_type:
                t2 = time.perf_counter()
                icon_slots = icon_finder.detect_inventory(image, debug_output_path=icon_debug_path)
                timings["Icon Slot Detection"] = time.perf_counter() - t2
                
            print(f"Detected {sum(len(v) for v in icon_slots.values())} icon slot candidates across {len(icon_slots)} labels.")

            overlays = matcher.load_quality_overlays(args.overlay_dir)

            icon_dir_map = {
                label: list(map(str, icon_dir_map_master[icon_set].get(label, [args.icon_dir])))
                for label in icon_slots
            }

            print("Launching icon matching process...")

            t4 = time.perf_counter()
            matches = matcher.match_all(image, build_info, icon_slots, icon_dir_map, overlays, threshold=0.7)
            timings["Icon Matching"] = time.perf_counter() - t4

            print(f"Matching complete. Total matches found: {len(matches)}")

            os.makedirs("output", exist_ok=True)

            matches_by_region_slot = defaultdict(lambda: defaultdict(list))

            # Map each original region candidate to its index so we can group consistently
            region_slot_index_map = {
                region_label: {
                    tuple(slot): idx for idx, slot in enumerate(slots)
                } for region_label, slots in icon_slots.items()
            }

            for match in matches:
                region = match["region"]
                top_left = match["top_left"]
                # Find the closest candidate region box and get its index
                candidate_idx = None
                for box, idx in region_slot_index_map[region].items():
                    x, y, w, h = box
                    if x <= top_left[0] <= x + w and y <= top_left[1] <= y + h:
                        candidate_idx = idx
                        break
                if candidate_idx is not None:
                    matches_by_region_slot[region][candidate_idx].append(match)

            with open("output/detected_icons.txt", "w") as f:
                for region in sorted(matches_by_region_slot.keys()):
                    f.write(f"=== Region: {region} ===\n")
                    for slot_idx in sorted(matches_by_region_slot[region].keys()):
                        slot_matches = matches_by_region_slot[region][slot_idx]
                        sorted_matches = sorted(slot_matches, key=lambda m: m["score"], reverse=True)
                        best = sorted_matches[0]
                        f.write(f"  -- Slot {slot_idx} --\n")
                        f.write(f"  BEST: {best['name']} using {best['method']} "
                                f"(score {best['score']:.2f}, scale {best['scale']:.2f}, quality scale {best.get('quality_scale', 0):.2f})\n")
                        if len(sorted_matches) > 1:
                            f.write("  Others:\n")
                            for match in sorted_matches[1:]:
                                f.write(f"    - {match['name']} using {match['method']} "
                                        f"(score {match['score']:.2f}, scale {match['scale']:.2f}, quality scale {match.get('quality_scale', 0):.2f})\n")
                    f.write("\n")

            results_dict = {
                "build_type": detected_type,
                "expected_build_type": expected_type,
                "match": detected_type == expected_type,
                "region_data": region_data,
                "icon_slots": icon_slots,
                "matches": matches
            }

            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(results_dict, f, indent=2)
                print(f"Saved results to {output_json_path}")

            print("\nTiming Summary:")
            for stage, duration in timings.items():
                print(f" - {stage}: {duration:.2f} seconds")
            print()

        except Exception as e:
            print(f"[ERROR] Failed to process {image_name}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    main()
