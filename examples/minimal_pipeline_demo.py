# run_pipeline.py
import argparse
import cv2
import traceback
import time

from pathlib import Path
from pprint import pprint

from log_config import setup_logging

from sto_sister.pipeline import build_default_pipeline, PipelineState
from sto_sister.exceptions import SISTERError, PipelineError, StageError
from sto_sister.utils.hashindex import HashIndex
from sto_sister.utils.image import load_image

import traceback

setup_logging()

def on_progress(stage, pct, ctx): 
    return ctx
    if stage == "label_locator":
        print(f"[Callback] [on_progress] [{stage}] {pct} {ctx.labels}%")
    elif stage == 'icon_group_locator':
        print(f"[Callback] [on_progress] [{stage}] {pct} {ctx.icon_groups}%")
    elif stage == 'layout_classifier':
        print(f"[Callback] [on_progress] [{stage}] {pct} {ctx.classification}%")


def on_stage_start(stage, ctx): 
    print(f"[Callback] [on_stage_start] [{stage}]")

def on_stage_complete(stage, ctx, output):
    if stage == 'label_locator':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.labels)} labels")
        return
    elif stage == 'icon_group_locator':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.icon_groups)} icon groups")
        return
    elif stage == 'layout_classifier':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.classification)} matches")   
        return
    elif stage == 'iconslot_detection':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.slots)}") # slots: {ctx.slots}")
        #return
    elif stage == 'icon_quality_detection':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.predicted_qualities)}")
        return
    elif stage == 'icon_matching':
        print(f"[Callback] [on_stage_complete] [{stage}] ") #Found {len(ctx.matches)} matches") # 
        return
    elif stage == 'icon_prefilter':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.predicted_icons)} matches")
        return
    elif stage == 'output_transformation':
        print(f"[Callback] [on_stage_complete] [{stage}]")
        return
    else:
        print(f"[Callback] [on_stage_complete] [{stage}] complete") 
    
    #print(f"[Callback] [on_stage_complete] [{stage}] Output: {output}")
    print(f"[Callback] [on_stage_complete] [{stage}] Pretty output: ")
    pprint(output)


def on_interactive(stage, ctx): return ctx  # no-op


def on_pipeline_complete(ctx, output, all_results): 
    print(f"[Callback] [on_pipeline_complete] Pipeline is complete.")
    #print(f"[Callback] [on_pipeline_complete] Output: {ctx}")

    print(f"[Callback] [on_pipeline_complete] Pretty output: ")
    pprint(output['matches'])
    #pprint(output['predicted_qualities'])

def on_error(err): 
    print(f"[Callback] [on_error] {err}")
    traceback.print_exc()

def on_metrics_complete(metrics): 
    print(f"[Callback] [on_metrics] {metrics}")


if __name__ == "__main__":
    start_time = time.time()

    p = argparse.ArgumentParser()
    p.add_argument("image", help="Path to screenshot")
    p.add_argument("--icons", default="images", help="Directory containing downloaded icons. Defaults to 'images' in current directory.")
    p.add_argument("--overlays", default="overlays", help="Directory containing icon overlay images. Defaults to 'overlays' in current directory.")
    p.add_argument("--log-level", default="INFO", help="Log level: DEBUG, VERBOSE, INFO, WARNING, ERROR")
    p.add_argument("--no-resize", action="store_true", help="Disable image downscaling to 1920x1080. Downscales only if screenshot is greater than 1920x1080.")

    args = p.parse_args()

    if args.log_level:
        setup_logging(log_level=args.log_level)

    # 1. load image
    img = load_image(args.image, resize_fullhd=not args.no_resize)
    
    if img is None:
        raise RuntimeError("Could not read image")


    #icon_root = Path(args.icons)
    #hash_index = HashIndex(icon_root, "phash", match_size=(16, 16))
    
    
    # 2. assemble config dict
    config = {
        "debug": True,
        
        "prefilter": {
            "method": "phash"
        },
        "engine": "phash",
        "hash_index_dir": args.icons,
        "hash_index_file": "hash_index.json",
        "hash_max_size": (16, 16),

        "icon_dir": args.icons,
        "overlay_dir": args.overlays,
    }

    # 3. build & run
    try:
        pipeline = build_default_pipeline(on_progress, on_interactive, on_error, config=config, on_metrics_complete=on_metrics_complete, on_stage_start=on_stage_start, on_stage_complete=on_stage_complete, on_pipeline_complete=on_pipeline_complete)
        result: PipelineState = pipeline.run(img)
    except SISTERError as e:
        print(e)
        import sys
        sys.exit(1)

    end_time = time.time()
    print(f"[pipeline.py] Total time: {end_time - start_time}")

    # 4. dump
    #for slot, match in result.icon_matches.items():
    #    print(f"{slot.icon_group_label}[{slot.index}] → {match}")
