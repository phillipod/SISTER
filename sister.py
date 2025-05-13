import os
import argparse
import time
import traceback
from collections import defaultdict
from pathlib import Path

# C-ext fast-ssim
#import sys
#sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from src.cargo import CargoDownloader
from src.locator import LabelLocator
from src.classifier import Classifier
from src.region import RegionDetector
from src.iconslot import IconSlotDetector
from src.iconmatch import IconMatcher
from src.hashindex import HashIndex
from src.prefilter import IconPrefilter
from src.utils.image import load_image, load_quality_overlays

from log_config import setup_logging

def download_icons(icons_dir):
    """
    Download all icons for equipment, personal traits, and starship traits from STO wiki.
    
    This function is a wrapper around CargoDownloader, which is used to download icons.
    The mappings from cargo types to subdirectories are hardcoded.
    """
    images_root = Path(icons_dir)
    image_cache_path = images_root / "image_cache.json"

    downloader = CargoDownloader()
    downloader.download_all()

    # Define all mappings as a list of tuples: (cargo_type, filters, subdirectory)
    download_mappings = [
        # Equipment types
        ('equipment', {'type': 'Body Armor'}, 'ground/armor'),
        ('equipment', {'type': 'Personal Shield'}, 'ground/shield'),
        ('equipment', {'type': 'EV Suit'}, 'ground/ev_suit'),
        ('equipment', {'type': 'Kit Module'}, 'ground/kit_module'),
        ('equipment', {'type': 'Kit'}, 'ground/kit'),
        ('equipment', {'type': 'Ground Weapon'}, 'ground/weapon'),
        ('equipment', {'type': 'Ground Device'}, 'ground/device'),
        ('equipment', {'type': 'Ship Deflector Dish'}, 'space/deflector'),
        ('equipment', {'type': 'Ship Secondary Deflector'}, 'space/secondary_deflector'),
        ('equipment', {'type': 'Ship Shields'}, 'space/shield'),
        ('equipment', {'type': 'Ship Vanity Shield'}, 'space/vanity_shield'),
        ('equipment', {'type': 'Experimental Weapon'}, 'space/weapons/experimental'),
        ('equipment', {'type': 'Ship Weapon'}, 'space/weapons/unrestricted'),
        ('equipment', {'type': 'Ship Aft Weapon'}, 'space/weapons/aft'),
        ('equipment', {'type': 'Ship Fore Weapon'}, 'space/weapons/fore'),
        ('equipment', {'type': 'Universal Console'}, 'space/consoles/universal'),
        ('equipment', {'type': 'Ship Engineering Console'}, 'space/consoles/engineering'),
        ('equipment', {'type': 'Ship Tactical Console'}, 'space/consoles/tactical'),
        ('equipment', {'type': 'Ship Science Console'}, 'space/consoles/science'),
        ('equipment', {'type': 'Impulse Engine'}, 'space/impulse'),
        ('equipment', {'type': 'Warp Engine'}, 'space/warp'),
        ('equipment', {'type': 'Singularity Engine'}, 'space/singularity'),
        ('equipment', {'type': 'Hangar Bay'}, 'space/hangar'),
        ('equipment', {'type': 'Ship Device'}, 'space/device'),

        # Personal traits
        ('personal_trait', {'environment': 'ground', 'chartype': 'char'}, 'ground/traits/personal'),
        ('personal_trait', {'environment': 'ground', 'type': 'reputation', 'chartype': 'char'}, 'ground/traits/reputation'),
        ('personal_trait', {'environment': 'ground', 'type': 'activereputation', 'chartype': 'char'}, 'ground/traits/active_reputation'),
        ('personal_trait', {'environment': 'space', 'chartype': 'char'}, 'space/traits/personal'),
        ('personal_trait', {'environment': 'space', 'type': 'reputation', 'chartype': 'char'}, 'space/traits/reputation'),
        ('personal_trait', {'environment': 'space', 'type': 'activereputation', 'chartype': 'char'}, 'space/traits/active_reputation'),

        # Starship traits (no filters)
        ('starship_trait', None, 'space/traits/starship')
    ]

    # Download all icons in one loop
    for cargo_type, filters, subdir in download_mappings:
        dest_dir = images_root / subdir
        downloader.download_icons(cargo_type, dest_dir, image_cache_path, filters)

    return download_mappings

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
        }
    }

def save_match_summary(output_dir, screenshot_path, slots, matches):
    """
    Save the match results to a text file.

    The match results are grouped by region and slot, and the best match is
    highlighted along with its score and scale. If there are multiple good matches,
    they are also listed.

    Args:
        output_dir (Path): Directory to save the output file.
        screenshot_path (str): Path to the screenshot file.
        matches (list[dict]): List of match results, each containing the keys
            "region", "top_left", "name", "method", "score", "scale", and
            "quality_scale".

    Returns:
        None
    """
    base_name = Path(screenshot_path).stem
    output_file = Path(output_dir) / f"{base_name}_matches.txt"

    with open(output_file, "w") as f:
        for region, slots in sorted(matches.items()):
            f.write(f"=== Region: {region} ===\n")
            for slot_idx, slot_matches in sorted(slots.items()):
                f.write(f"  -- Slot {slot_idx} --\n")
                
                if not slot_matches:
                    f.write("    <no matches>\n")
                    continue

                # detect hash-based methods (e.g. 'hash', 'hash-phash', etc.)
                first_method = slot_matches[0].get("method", "")
                is_hash_method = first_method.startswith("hash")

                # sort descending for SSIM, ascending for hash
                sorted_matches = sorted(
                    slot_matches,
                    key=lambda m: m.get("score", 0),
                    reverse=not is_hash_method
                )

                # helper to pull out a quality_scale, even from predicted_quality
                def get_quality_scale(m):
                    if "quality_scale" in m:
                        return m["quality_scale"]
                    elif "predicted_quality" in m and isinstance(m["predicted_quality"], (list, tuple)):
                        return m["predicted_quality"][1]
                    return 0.0

                best = sorted_matches[0]
                best_qs = get_quality_scale(best)
                best_scale = best.get("scale", 0.0)
                f.write(
                    f"    BEST: {best.get('name','<unknown>')} ({best.get('quality','')}) "
                    f"using {best.get('method','')} "
                    f"(score {best.get('score',0):.2f}, scale {best_scale:.2f}, "
                    f"quality scale {best_qs:.2f})\n"
                )

                # if there are any runners-up, list them
                if len(sorted_matches) > 1:
                    f.write("    Others:\n")
                    for m in sorted_matches[1:]:
                        qs = get_quality_scale(m)
                        sc = m.get("scale", 0.0)
                        f.write(
                            f"      - {m.get('name','<unknown>')} using {m.get('method','')} "
                            f"(score {m.get('score',0):.2f}, scale {sc:.2f}, quality scale {qs:.2f})\n"
                        )

            f.write("\n")

    print(f"Saved match summary to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Icon Matching CLI for Star Trek Online screenshots.")
    parser.add_argument("--screenshot", help="Path to the screenshot to analyze.")
    parser.add_argument("--icons", default="images", help="Directory containing downloaded icons. Defaults to 'images' in current directory.")
    parser.add_argument("--overlays", default="overlays", help="Directory containing icon overlay images. Defaults to 'overlays' in current directory.")
    parser.add_argument("--output", default="output", help="Directory to store output summaries. Defaults to 'output' in current directory.")
    parser.add_argument("--log-level", default="INFO", help="Log level: DEBUG, VERBOSE, INFO, WARNING, ERROR.")
    parser.add_argument("--no-resize", action="store_true", help="Disable image downscaling to 1920x1080. Downscales only if screenshot is greater than 1920x1080.")
    parser.add_argument("--download", action="store_true", help="Download icon data from STO Wiki. Exit after.")
    parser.add_argument("--threshold", type=float, default=0.7, help="Threshold for icon matching. Defaults to 0.7")
    parser.add_argument("--debug", action="store_true", help="Enable debug image output.")
    parser.add_argument("--gpu", action="store_true", help="Enable GPU usage for OCR.")
    parser.add_argument("--build-phash-cache", action="store_true", help="Build a perceptual hash (phash) cache for all icons.")

    args = parser.parse_args()

    setup_logging(log_level=args.log_level)

    icon_root = Path(args.icons)
    hash_index = HashIndex(icon_root, "phash", match_size=(16, 16))
    
    if args.download or args.build_phash_cache:
        if args.download:
            print("Downloading icon data from STO Wiki...")
            download_icons(args.icons)

        if args.build_phash_cache:
            print("Building PHash cache with overlays...")
     
            overlays = load_quality_overlays(args.overlays)  # Must return dict of quality -> RGBA overlay np.array
            hash_index.build_with_overlays(overlays)

            print(f"[DONE] Built PHash index with {len(hash_index.hashes)} entries.")
            return
        exit(0)

    if args.screenshot is None:
        parser.print_help()
        exit(1)

    os.makedirs(args.output, exist_ok=True)
    
    screenshot = load_image(args.screenshot, resize_fullhd=not args.no_resize)

    locator = LabelLocator(gpu=args.gpu, debug=args.debug)
    classifier = Classifier(debug=args.debug)
    regioner = RegionDetector(debug=args.debug)
    slot_finder = IconSlotDetector(hash_index=hash_index, debug=args.debug)
    prefilter = IconPrefilter(hash_index=hash_index, debug=args.debug)
    matcher = IconMatcher(hash_index=hash_index, debug=args.debug)

    icon_dir_map_master = build_icon_dir_map(Path(args.icons))
    overlays = matcher.load_quality_overlays(args.overlays)

    print(f"Processing: {args.screenshot}")
    try:
        timings = {}

        # --- Label Location ---
        start = time.perf_counter()
        labels = locator.locate(screenshot)
        timings["Label Detection"] = time.perf_counter() - start
        print(f"Found {len(labels)} labels")

        start = time.perf_counter()
        build_info = classifier.classify(labels)
        timings["Build Classification"] = time.perf_counter() - start

        print(f"Detected build type: {build_info['build_type']} (score: {build_info['score']})")
        
        icon_set = None
        if "Ship Build" in build_info["build_type"]:
            icon_set = "ship"
        elif "PC Ground Build" in build_info["build_type"]:
            icon_set = "pc_ground"
        elif "Console Ground Build" in build_info["build_type"]:
            icon_set = "console_ground"

        if "PC Ship Build" in build_info["build_type"] or "PC Ground Build" in build_info["build_type"] or "Console Ship Build" in build_info["build_type"] or "Console Ground Build" in build_info["build_type"]:       
            start = time.perf_counter()
            regions = regioner.detect_regions(screenshot, labels, build_info)
            timings["Region Detection"] = time.perf_counter() - start
            print(f"Found {len(regions)} regions")

            start = time.perf_counter()
            slots = slot_finder.detect_slots(screenshot, regions)
            timings["Slot Detection"] = time.perf_counter() - start
            print(f"Found {sum(len(v) for v in slots.values())} slots")

            # Build icon dir map based on icon slots found and build type icon set
            icon_dir_map = {
                label: list(map(str, icon_dir_map_master[icon_set].get(label, [args.icons])))
                for label in slots
            }

            start = time.perf_counter()
            predicted_icons = prefilter.icon_predictions(slots, icon_dir_map)
            timings["Icon Prefilter"] = time.perf_counter() - start
            print(f"Found {sum(len(slots) for region in predicted_icons.values() for slots in region.values())} icon predictions")

            start = time.perf_counter()
            predicted_qualities = matcher.quality_predictions(slots, overlays, threshold=args.threshold)
            timings["Quality Prediction"] = time.perf_counter() - start
            print(f"Found {sum(len(slots) for slots in predicted_qualities.values())} quality predictions")

            start = time.perf_counter()
            matches = matcher.match_all(slots, icon_dir_map, overlays, predicted_qualities, prefilter.filtered_icons, prefilter.found_icons, threshold=args.threshold)
            timings["Icon Matching"] = time.perf_counter() - start
            print(f"Found {len(matches)} matches")

            save_match_summary(args.output, args.screenshot, slots, matches)
            #save_match_summary(args.output, args.screenshot, slots, predicted_icons)

            print("\n--- Timing Summary ---")
            for stage, seconds in timings.items():
                print(f"{stage}: {seconds:.2f} seconds")

            print(f"\nTotal: {sum(timings.values()):.2f} seconds")
        else:
            print(f"No icon matching performed - unknown build type '{build_info['build_type']}'")

    except Exception as e:
        print(traceback.format_exc())
        print(f"Error processing {args.screenshot}: {e}")

if __name__ == "__main__":
    main()
