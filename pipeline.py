# run_pipeline.py
import argparse
import cv2

from pathlib import Path



from src.sister import build_default_pipeline, PipelineContext
from src.hashindex import HashIndex
from src.iconmap import IconDirectoryMap
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
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.slots)}") # slots: {ctx.slots}")
    elif stage == 'icon_quality_detection':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.predicted_qualities)} predicted qualities: {ctx.predicted_qualities}")
    elif stage == 'icon_matching':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.matches)} matches matches: {ctx.matches}")
    else:
        print(f"[Callback] [on_stage_complete] [{stage}] complete") 


def on_interactive(stage, ctx): return ctx  # no-op


def on_pipeline_complete(ctx, output): 
    print(f"[Callback] [on_pipeline_complete] Pipeline is complete.") # Output: {output}")

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
    #hash_index = HashIndex(icon_root, "phash", match_size=(16, 16))
    
    
    # 2. assemble config dict
    config = {
        "debug": True,
        
        "prefilter": {
            "icon_root": icon_root,
            "hash_index_dir": icon_root,
            "hash_index_file": "hash_index.json",
        },

        "icon_dir": args.icons,
        "overlay_dir": args.overlays,

        "icon_sets": IconDirectoryMap({
            "ship": {
                "Fore Weapon": [icon_root / 'space/weapons/fore', icon_root / 'space/weapons/unrestricted'],
                "Aft Weapon": [icon_root / 'space/weapons/aft', icon_root / 'space/weapons/unrestricted'],
                "Experimental Weapon": [icon_root / 'space/weapons/experimental'],
                "Shield": [icon_root / 'space/shield'],
                "Secondary Deflector": [icon_root / 'space/secondary_deflector'],
                "Deflector": [icon_root / 'space/deflector', icon_root / 'space/secondary_deflector' ], # Console doesn't have a specific label for Secondary Deflector, it's located under the Deflector label.
                "Impulse": [icon_root / 'space/impulse'],
                "Warp": [icon_root / 'space/warp'],
                "Singularity": [icon_root / 'space/singularity'],
                "Hangar": [icon_root / 'space/hangar'],
                "Devices": [icon_root / 'space/device'],
                "Universal Console": [icon_root / 'space/consoles/universal', icon_root / 'space/consoles/engineering', icon_root / 'space/consoles/tactical', icon_root / 'space/consoles/science'],
                "Engineering Console": [icon_root / 'space/consoles/engineering', icon_root / 'space/consoles/universal'],
                "Tactical Console": [icon_root / 'space/consoles/tactical', icon_root / 'space/consoles/universal'],
                "Science Console": [icon_root / 'space/consoles/science', icon_root / 'space/consoles/universal']
            },
            "pc_ground": {
                "Body": [icon_root / 'ground/armor'],
                "Shield": [icon_root / 'ground/shield'],
                "EV Suit": [icon_root / 'ground/ev_suit'],
                "Kit Modules": [icon_root / 'ground/kit_module'],
                "Kit": [icon_root / 'ground/kit'],
                "Devices": [icon_root / 'ground/device'],
                "Weapon": [icon_root / 'ground/weapon'],
            },
            "console_ground": {
                "Body": [icon_root / 'ground/armor'],
                "Shield": [icon_root / 'ground/shield'],
                "EV Suit": [icon_root / 'ground/ev_suit'],
                "Kit": [icon_root / 'ground/kit_module'], # Console swaps "Kit Modules" to "Kit"
                "Kit Frame": [icon_root / 'ground/kit'], # And "Kit" becomes "Kit Frame"
                "Devices": [icon_root / 'ground/device'],
                "Weapon": [icon_root / 'ground/weapon'],
            }
        }),
    }

    # 3. build & run
    pipeline = build_default_pipeline(on_progress, on_interactive, config=config, on_stage_complete=on_stage_complete, on_pipeline_complete=on_pipeline_complete)
    result: PipelineContext = pipeline.run(img)

    # 4. dump
    #for slot, match in result.icon_matches.items():
    #    print(f"{slot.region_label}[{slot.index}] → {match}")
