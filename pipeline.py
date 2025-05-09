# run_pipeline.py
import argparse
import cv2

from pathlib import Path



from src.sister import build_default_pipeline, PipelineContext
from src.hashindex import HashIndex

from log_config import setup_logging

setup_logging()

def on_progress(stage, pct, ctx): 
    return ctx
    if stage == "label_locator":
        print(f"[Callback] [on_progress] [{stage}] {pct} {ctx.labels}%")
    elif stage == "region_detector":
        print(f"[Callback] [on_progress] [{stage}] {pct} {ctx.regions}%")
    elif stage == 'classifier':
        print(f"[Callback] [on_progress] [{stage}] {pct} {ctx.classification}%")

def on_stage_complete(stage, ctx, output):
    if stage == 'label_locator':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.labels)} labels")
    elif stage == 'region_detector':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.regions)} regions")
    elif stage == 'classifier':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.classification)} matches")   
    elif stage == 'iconslot_detection':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.slots)} slots: {ctx.slots}")
    elif stage == 'icon_quality_detection':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.predicted_qualities)} predicted qualities: {ctx.predicted_qualities}")
    else:
        print(f"[Callback] [on_stage_complete] [{stage}] complete") 


def on_interactive(stage, ctx): return ctx  # no-op


def on_pipeline_complete(ctx, output): 
    print(f"[Callback] [on_pipeline_complete] Pipeline is complete. Output: {output}")


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


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("image", help="Path to screenshot")
    p.add_argument("--icons", default="images", help="Directory containing downloaded icons. Defaults to 'images' in current directory.")
    p.add_argument("--overlays", default="overlays", help="Directory containing icon overlay images. Defaults to 'overlays' in current directory.")
    p.add_argument("--log-level", default="INFO", help="Log level: DEBUG, VERBOSE, INFO, WARNING, ERROR")

    args = p.parse_args()

    if args.log_level:
        setup_logging(log_level=args.log_level)

    # 1. load image
    img = cv2.imread(args.image)
    if img is None:
        raise RuntimeError("Could not read image")


    icon_root = Path(args.icons)
    hash_index = HashIndex(icon_root, "phash", match_size=(16, 16))
    
    icon_dir_map_master = build_icon_dir_map(Path(args.icons))

    # 2. assemble config dict
    config = {
        "debug": True,
        "icon_dirs": icon_dir_map_master,
        "hash_index": hash_index,
        "overlay_dir": args.overlays
    }

    # 3. build & run
    pipeline = build_default_pipeline(on_progress, on_interactive, config=config, on_stage_complete=on_stage_complete, on_pipeline_complete=on_pipeline_complete)
    result: PipelineContext = pipeline.run(img)

    # 4. dump
    #for slot, match in result.icon_matches.items():
    #    print(f"{slot.region_label}[{slot.index}] → {match}")
