# run_pipeline.py
import argparse
import cv2
from src.sister import build_default_pipeline, PipelineContext

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
    print(f"[Callback] [on_stage_complete] [{stage}] complete")
    if stage == 'label_locator':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.labels)} labels")
    elif stage == 'region_detector':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.regions)} regions")
    elif stage == 'classifier':
        print(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.classification)} matches")
       
def on_interactive(stage, ctx): return ctx  # no-op


def on_pipeline_complete(ctx, output): 
    print(f"[Callback] [on_pipeline_complete] Pipeline is complete. Output: {output}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("image", help="Path to screenshot")
    p.add_argument("--region-min-area", type=int, default=5000,
                   help="Minimum pixel area for a region")
    p.add_argument("--iconslot-threshold", type=int, default=100,
                   help="Binarization threshold for slot detection")
    p.add_argument("--log-level", default="INFO", help="Log level: DEBUG, VERBOSE, INFO, WARNING, ERROR")

    args = p.parse_args()

    if args.log_level:
        setup_logging(log_level=args.log_level)

    # 1. load image
    img = cv2.imread(args.image)
    if img is None:
        raise RuntimeError("Could not read image")

    # 2. assemble config dict
    config = {
        "debug": True,
    }

    # 3. build & run
    pipeline = build_default_pipeline(on_progress, on_interactive, config=config, on_stage_complete=on_stage_complete, on_pipeline_complete=on_pipeline_complete)
    result: PipelineContext = pipeline.run(img)

    # 4. dump
    #for slot, match in result.icon_matches.items():
    #    print(f"{slot.region_label}[{slot.index}] → {match}")
