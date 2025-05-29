import time
load_start_time = time.time()

import argparse
import cv2
import traceback

from functools import partial
from tqdm import tqdm
from collections import defaultdict
from pathlib import Path
from pprint import pprint

from log_config import setup_logging

from sto_sister.pipeline import build_default_pipeline, PipelineState
from sto_sister.exceptions import SISTERError, PipelineError, StageError

from sto_sister.utils.hashindex import HashIndex
from sto_sister.utils.image import load_image, load_overlays

import traceback

_progress_bars = {}
_prev_percents = defaultdict(int)

def on_progress(stage, substage, pct, ctx):
    # on any 0.0, reset the progress bar
    if pct == 0.0:
        old = _progress_bars.pop(stage, None)
        if old:
            old.close()
        bar = tqdm(total=100, desc=stage, bar_format='{l_bar}{bar}|', leave=False)
        _progress_bars[stage] = bar
        _prev_percents[stage] = 0

    bar = _progress_bars.get(stage)
    if not bar:
        return ctx

    # normalize 0–1 or 0–100 -> integer 0–100
    new_pct = int(pct * 100) if pct <= 1 else int(pct)
    delta   = new_pct - _prev_percents[stage]
    if delta > 0:
        bar.update(delta)
        _prev_percents[stage] = new_pct

    if substage:
        bar.set_description(f"{stage}[{substage}]")
    bar.refresh()
    return ctx


def on_stage_start(stage, ctx): 
    return #print(f"[Callback] [on_stage_start] [{stage}]")

def on_stage_complete(stage, ctx, output):
    bar = _progress_bars.pop(stage, None)
    if bar:
        # if we never actually hit 100 inside on_progress, finish it now
        prev = _prev_percents[stage]
        if prev < bar.total:
            bar.update(bar.total - prev)
        bar.close()

    if stage == 'locate_labels':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Found {sum(len(label) for label in ctx.labels_list)} labels")
        return
    elif stage == 'locate_icon_groups':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.icon_groups)} icon groups")
        return
    elif stage == 'classify_layout':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Detected build type: {ctx.classification["build_type"]}")   
        return
    elif stage == 'locate_icon_slots':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Found {sum(len(icon_group) for icon_group in output.values())} icon slots") #
        return
    elif stage == 'detect_icon_overlays':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Matched {sum(1 for icon_group_dict in output.values() for slot_items in icon_group_dict.values() for item in slot_items if item.get("overlay") != "common")} icon overlays")
        return
    elif stage == 'detect_icons':
        methods = {}
        match_count = 0
        for icon_group in output.keys():
            for slot in output[icon_group].keys():
                match_count += len(output[icon_group][slot])
                for candidate in output[icon_group][slot]:
                    method = candidate["method"]
                    methods[candidate["method"]] = (
                        methods.get(candidate["method"], 0) + 1
                    )
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Matched {match_count} icons in total")
        for method, count in methods.items():
            tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Matched {count} icons with {method}")
        
        return
    elif stage == 'prefilter_icons':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Found {sum(len(slots) for icon_group in output.values() for slots in icon_group.values())} potential matches")
        return
    elif stage == 'load_icons':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Loaded icons")
        return
    elif stage == 'output_transformation':
        #tqdm.write(f"[Callback] [on_stage_complete] [{stage}]")
        return
    else:
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] complete") 
    
    #print(f"[Callback] [on_stage_complete] [{stage}] Output: {output}")
    tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Pretty output: ")
    pprint(output)


def on_task_start(task, ctx): 
    return #print(f"[Callback] [on_task_start] [{task}]")

def on_task_complete(task, ctx, output):
    bar = _progress_bars.pop(task, None)
    if bar:
        # if we never actually hit 100 inside on_progress, finish it now
        prev = _prev_percents[task]
        if prev < bar.total:
            bar.update(bar.total - prev)
        bar.close()

    if task == 'start_executor_pool':
        tqdm.write(f"[Callback] [on_task_complete] [{task}] Started executor pool ({ctx.executor_pool_total} workers)")
        return
    elif task == 'stop_executor_pool':
        tqdm.write(f"[Callback] [on_task_complete] [{task}] Stopped executor pool")
        return
    elif task == 'build_hash_cache':
        tqdm.write(f"[Callback] [on_task_complete] [{task}] Built hash cache ({ctx.hashed_items} items)")
        return
    else:
        tqdm.write(f"[Callback] [on_task_complete] [{task}] complete") 
    
    #print(f"[Callback] [on_task_complete] [{stage}] Output: {output}")
    tqdm.write(f"[Callback] [on_task_complete] [{task}] Pretty output: ")
    pprint(output)

def on_interactive(stage, ctx): return ctx  # no-op


def on_pipeline_complete(ctx, output, all_results, save_dir, save_file): 
    
    success, result = save_match_summary(save_dir, save_file, output["matches"])

    tqdm.write(f"[Callback] [on_pipeline_complete] Pipeline is complete. Saved: {success} File: {result}")

    #print(f"[Callback] [on_pipeline_complete] Output: {ctx}")

    #print(f"[Callback] [on_pipeline_complete] Pretty output: ")
    #pprint(output['matches'])
    #pprint(output['detected_overlays'])

def on_error(err): 
    print(f"[Callback] [on_error] {err}")
    traceback.print_exc()

def on_metrics_complete(metrics): 
    #print(f"[Callback] [on_metrics] {metrics}")
    for metric in metrics:
        if not metric['name'].endswith('_complete') and not metric['name'].endswith('_interactive'):
            print(f"[Callback] [on_metrics] {"\t" if not metric['name'].startswith('pipeline') else ""}{metric['name']} took {metric['duration']:.2f} seconds")

def save_match_summary(output_dir, output_prefix, matches):
    """
    Save the match results to a text file, deduping any runner-ups
    that end up with the same item_name (keeping only the top score).
    """
    output_file = Path(output_dir) / f"{output_prefix}_matches.txt"

    with open(output_file, "w", encoding="utf-8") as f:
        for icon_group, slots in sorted(matches.items()):
            f.write(f"=== Icon Group: {icon_group} ===\n")
            for slot_idx, slot_matches in sorted(slots.items()):
                f.write(f"  -- Slot {slot_idx} --\n")

                if not slot_matches:
                    f.write("    <no matches>\n\n")
                    continue

                # Detect hash-based methods
                first_method   = slot_matches[0].get("method", "")
                is_hash_method = first_method.startswith("hash")

                # Sort appropriately
                sorted_matches = sorted(
                    slot_matches,
                    key=lambda m: m.get("score", 0),
                    reverse=not is_hash_method
                )

                # Helpers to pull overlay info
                def get_overlay_scale(m):
                    det = m.get("detected_overlay")
                    if isinstance(det, (list, tuple)) and det:
                        return det[0].get("scale", 0.0)
                    return m.get("overlay_scale", 0.0)

                def get_overlay_name(m):
                    det = m.get("detected_overlay")
                    if isinstance(det, (list, tuple)) and det:
                        return det[0].get("overlay", "unknown")
                    return m.get("overlay", "unknown")

                # --- BEST match and its name(s) ---
                best = sorted_matches[0]
                best_meta = best.get("metadata", []) or [best]
                best_names = {
                    md.get("item_name", "<unknown>") for md in best_meta
                }

                if len(best_names) > 1:
                    display_best = "ANY OF\n\t- " + "\n\t- ".join(sorted(best_names)) + "\n\t"
                else:
                    display_best = next(iter(best_names))

                b_ovr = get_overlay_name(best)
                b_score = best.get("score", 0.0)
                b_scale = best.get("scale", 0.0)
                b_qs = get_overlay_scale(best)

                f.write(
                    f"    BEST: {display_best} ({b_ovr}) "
                    f"using {best.get('method','')} "
                    f"(score {b_score:.2f}, scale {b_scale:.2f}, "
                    f"overlay scale {b_qs:.2f})\n"
                )

                # --- COLLECT runners, skipping any whose name overlaps best_names ---
                runners = []
                for m in sorted_matches[1:]:
                    meta_list = m.get("metadata", []) or [m]
                    names = {md.get("item_name", "<unknown>") for md in meta_list}
                    # skip if any name is the same as best
                    if names & best_names:
                        continue

                    # build a stable display name
                    if len(names) > 1:
                        name_str = "ANY OF\n\t- " + "\n\t- ".join(sorted(names)) + "\n\t"
                    else:
                        name_str = next(iter(names))

                    runners.append((name_str, m))

                # --- DEDUPE runners by name_str, keeping only the highest-score one ---
                deduped = {}
                for name_str, m in runners:
                    score = m.get("score", 0.0)
                    prev = deduped.get(name_str)
                    if prev is None or score > prev.get("score", 0.0):
                        deduped[name_str] = m

                # If any remain, emit “Others:”
                if deduped:
                    f.write("    Others:\n")
                    # sort the deduped runners by descending score
                    for name_str, m in sorted(
                        deduped.items(),
                        key=lambda kv: kv[1].get("score", 0.0),
                        reverse=True
                    ):
                        ovr   = get_overlay_name(m)
                        sc    = m.get("score", 0.0)
                        sca   = m.get("scale", 0.0)
                        qs    = get_overlay_scale(m)
                        f.write(
                            f"      - {name_str} ({ovr}) using {m.get('method','')} "
                            f"(score {sc:.2f}, scale {sca:.2f}, overlay scale {qs:.2f})\n"
                        )

            f.write("\n")

    return True, output_file

if __name__ == "__main__":
    start_time = time.time()

    p = argparse.ArgumentParser()
    p.add_argument("--screenshot", "-s", nargs="+", help="Path to screenshot")
    p.add_argument("--icons", default="images", help="Directory containing downloaded icons. Defaults to 'images' in current directory.")
    p.add_argument("--overlays", default="overlays", help="Directory containing icon overlay images. Defaults to 'overlays' in current directory.")
    p.add_argument("--log-level", default="WARNING", help="Log level: DEBUG, VERBOSE, INFO, WARNING, ERROR")
    p.add_argument("--no-resize", action="store_true", help="Disable image downscaling to 1920x1080. Downscales only if screenshot is greater than 1920x1080.")
    p.add_argument("--download", action="store_true", help="Download icon data from STO Wiki. Exit after.")
    p.add_argument("--build-hash-cache", action="store_true", help="Build a hash (phash, dhash) cache for all icons.")
    p.add_argument("--output_dir", default="output", help="Directory to store output summaries. Defaults to 'output' in current directory.")
    p.add_argument("--output", "-o", help="Output file prefix to save match summary to. Must be specified if more than one screenshot is provided.")
    p.add_argument("--gpu", action="store_true", help="Enable GPU usage for OCR.")

    args = p.parse_args()

    if args.log_level:
        setup_logging(log_level=args.log_level)
   
    # 2. assemble config dict
    config = {
        "debug": True,
        "log_level": args.log_level,
        "locate_labels": {
            "gpu": args.gpu
        },
        "prefilter_icons": {
            "method": "phash"
        },
        "output_transformation": {
            "transformations_enabled_list": [
                "BACKFILL_MATCHES_WITH_PREFILTERED" # If no matches are found for a given slot, this transformation will merge any prefiltered icons into the output
            ]
        },
        "engine": "phash",
        "hash_index_dir": args.icons,
        "hash_index_file": "hash_index.json",
        "hash_max_size": (16, 16),

        "icon_dir": args.icons,
        "overlay_dir": args.overlays,
    }

    # bind args to on_pipeline_complete
    bound_on_pipeline_complete = partial(on_pipeline_complete, save_dir=args.output_dir, save_file=args.output)

    # 3. build & run
    try:
        pipeline = build_default_pipeline(on_progress, on_interactive, on_error, config=config, on_metrics_complete=on_metrics_complete, on_stage_start=on_stage_start, on_stage_complete=on_stage_complete, on_task_start=on_task_start, on_task_complete=on_task_complete, on_pipeline_complete=bound_on_pipeline_complete)


        if args.download or args.build_hash_cache:
            if args.download:
                print("Downloading icon data from STO Wiki...")
                result: PipelineState = pipeline.execute_task("download_all_icons")

            if args.build_hash_cache:
                print("Building Hash cache...")
                result: PipelineState = pipeline.execute_task("build_hash_cache")

            exit(0)

        if args.download:
            print("Downloading icon data from STO Wiki...")
            result: PipelineState = pipeline.execute_task("download_all_icons")
            exit(0)

        if len(args.screenshot) == 1 and args.output is None:
            args.output = Path(args.screenshot[0]).stem


        if args.screenshot is None or args.output is None:
            p.print_help()
            exit(1)


        # 1. load image
        images = [
            load_image(path, resize_fullhd=not args.no_resize)
            for path in args.screenshot
        ]
        
        if images is None:
            raise RuntimeError("Could not read image")

        pipeline.startup()

        result: PipelineState = pipeline.run(images)
        
        
        pipeline.shutdown()
        # save_match_summary(args.output_dir, args.output, result[1]["detect_icons"])
    except SISTERError as e:
        print(e)
        import sys
        sys.exit(1)

    end_time = time.time()
#    print(f"[sister-cli.py] Python dependencies load time: {start_time - load_start_time}")
    print(f"[sister-cli.py] Total time: {end_time - start_time}")

