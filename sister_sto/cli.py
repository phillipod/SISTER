import importlib, sys

import os
import sys
import time
load_start_time = time.time()

import argparse
import cv2
import traceback
import multiprocessing

from functools import partial
from tqdm import tqdm
from collections import defaultdict
from pathlib import Path
from pprint import pprint
from logging import getLogger

from sister_sto.pipeline.pipeline import build_default_pipeline, PipelineState
from sister_sto.exceptions import SISTERError, PipelineError, StageError
from sister_sto.log_config import setup_console_logging

from sister_sto.utils.hashindex import HashIndex
from sister_sto.utils.image import load_image, load_overlays

import traceback

logger = getLogger(__name__)   

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

def handle_test_instrumentation_stage(stage: str, ctx, output, collector):
    """Handle test instrumentation data collection for a pipeline stage."""
    if not collector:
        return

    if stage == 'locate_labels':
        # Process all labels from all screenshots
        all_labels = []
        all_positions = []
        for screenshot_labels in ctx.labels_list:
            all_labels.extend(list(screenshot_labels.keys()))
            all_positions.extend([{
                "x": label["top_left"][0],
                "y": label["top_left"][1],
                "width": label["top_right"][0] - label["top_left"][0],
                "height": label["bottom_left"][1] - label["top_left"][1]
            } for label in [{k: v for k, v in label.items() if k != 'roi_data'} for label in screenshot_labels.values()]])
        
        collector.record_labels(
            labels=all_labels,
            positions=all_positions
        )
    elif stage == 'classify_layout':
        collector.record_classification(
            classification=ctx.classification["build_type"],
            confidence=ctx.classification.get("confidence", 0.0)
        )
    elif stage == 'locate_icon_groups':
        # Filter out roi_data field from groups before recording
        filtered_groups = {}  # Changed from list to dict since groups is a dict
        for group_name, group_data in ctx.icon_groups.items():
            if isinstance(group_data, dict) and 'Label' in group_data:
                # Deep copy the Label dict without roi_data
                filtered_groups[group_name] = {
                    'Label': {k: v for k, v in group_data['Label'].items() if k != 'roi_data'}
                }
            else:
                # If it's not a dict with Label, keep as is
                filtered_groups[group_name] = group_data
        collector.record_icon_groups(filtered_groups)
    elif stage == 'locate_icon_slots':
        # Filter out ROI field from each slot before recording
        filtered_output = {}
        for group, slots in output.items():
            filtered_output[group] = []
            for slot in slots:
                filtered_slot = {k: v for k, v in slot.items() if k != 'ROI'}
                filtered_output[group].append(filtered_slot)
        collector.record_icon_slots(filtered_output)
    elif stage == 'prefilter_icons':
        matches = []
        filtered_matches = []
        for icon_group, slots in output.items():
            for slot_idx, slot_matches in slots.items():
                matches.extend(slot_matches)
                filtered_matches.extend([m for m in slot_matches if m.get("filtered", False)])
        collector.record_prefilter_matches(matches, filtered_matches)
    elif stage == 'detect_icon_overlays':
        overlays = []
        for icon_group_dict in output.values():
            for slot_items in icon_group_dict.values():
                for item in slot_items:
                    if item.get("overlay") != "common":
                        overlays.append(item)
        collector.record_overlays(overlays)
    elif stage == 'detect_icons':
        matches = []
        ssim_scores = []
        for icon_group in output:
            for slot in output[icon_group]:
                for match in output[icon_group][slot]:
                    matches.append(match)
                    if "ssim_score" in match:
                        ssim_scores.append(match["ssim_score"])
        collector.record_icon_matches(matches, ssim_scores)
    elif stage == 'output_transformation':
        collector.record_transformations(
            output.get("transformations_applied", []),
            output.get("matches", {})
        )

def on_stage_complete(stage, ctx, output, test_collector=None):
    bar = _progress_bars.pop(stage, None)
    if bar:
        # if we never actually hit 100 inside on_progress, finish it now
        prev = _prev_percents[stage]
        if prev < bar.total:
            bar.update(bar.total - prev)
        bar.close()

    # Handle test instrumentation if enabled
    handle_test_instrumentation_stage(stage, ctx, output, test_collector)

    if stage == 'locate_labels':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Found {sum(len(label) for label in ctx.labels_list)} labels")
        return
    elif stage == 'locate_icon_groups':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Found {len(ctx.icon_groups)} icon groups")
        return
    elif stage == 'classify_layout':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Detected build type: {ctx.classification['build_type']}")
        return
    elif stage == 'crop_label_regions':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Cropped {sum(len(label) for label in ctx.labels_list)} labels")
        return
    elif stage == 'locate_icon_slots':
        tqdm.write(
            f"[Callback] [on_stage_complete] [{stage}] Found {sum(len(icon_group) for icon_group in output.values())} icon slots"
        )
        return
    elif stage == 'detect_icon_overlays':
        tqdm.write(
            f"[Callback] [on_stage_complete] [{stage}] Matched {sum(1 for icon_group_dict in output.values() for slot_items in icon_group_dict.values() for item in slot_items if item.get('overlay') != 'common')} icon overlays"
        )
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

    if task == 'app_init':
        tqdm.write(f"[Callback] [on_task_complete] [{task}] Initialized")
        return
    elif task == 'start_executor_pool':
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


def handle_test_instrumentation_complete(ctx, output, all_results, save_dir, save_file, collector):
    """Handle test instrumentation data saving at pipeline completion."""
    if collector:
        output_file = Path(save_dir) / f"{save_file}_test_data.json"
        print(f"[Callback] [on_pipeline_complete::handle_test_instrumentation_complete] Saving test instrumentation data to {output_file}")
        collector.save(output_file)

def on_pipeline_complete(ctx, output, all_results, save_dir, save_file, test_collector=None): 
    # Get the matches from the output transformation stage results
    # output = {}
    # if 'output_transformation' in results:
    #     output = results['output_transformation']
    # elif hasattr(ctx, 'output') and isinstance(ctx.output, dict):
    #     output = ctx.output
    #pprint(all_results) 
    #pprint(output)

    if not isinstance(output, dict):
        logger.error("Pipeline output is not a dictionary")
        return

    if "matches" not in output:
        logger.error("Pipeline output does not contain matches")
        return

    success, result = save_match_summary(save_dir, save_file, output["matches"])
    tqdm.write(f"[Callback] [on_pipeline_complete] Pipeline is complete. Saved: {success} File: {result}")

    # Handle test instrumentation if enabled
    handle_test_instrumentation_complete(ctx, output, all_results, save_dir, save_file, test_collector)

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
            print(
                f"[Callback] [on_metrics] {chr(9) if not metric['name'].startswith('pipeline') else ''}{metric['name']} took {metric['duration']:.2f} seconds"
            )

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

                # If any remain, emit "Others:"
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

def main():
    multiprocessing.freeze_support()

    start_time = time.time()

    p = argparse.ArgumentParser()
    p.add_argument("--config", dest="config_file", default="~/.sister_sto/config/config.yaml", help="Path to a custom config file. Will be merged with default config and ~/.sister_sto/config/config.yaml.")
    p.add_argument("--data-dir", default="~/.sister_sto", help="Directory containing STO data. Defaults to '.sister_sto' in user home directory.")
    p.add_argument("--log-dir", default="log", help="Directory to write logfile to. Defaults to 'log' in data-dir directory.")
    p.add_argument("--icon-dir", default="icons", help="Directory containing downloaded icons. Defaults to 'icons' in data-dir directory.")
    p.add_argument("--overlay-dir", default="overlays", help="Directory containing icon overlay images. Defaults to 'overlays' in data-dir directory.")
    p.add_argument("--output-dir", default="./", help="Directory to store output summaries. Defaults to current directory.")
    p.add_argument("--log-level", default="WARNING", help="Log level: DEBUG, VERBOSE, INFO, WARNING, ERROR")
    p.add_argument("--download", action="store_true", help="Download icon data from STO Wiki. Exit after.")
    p.add_argument("--build-hash-cache", action="store_true", help="Build a hash (phash, dhash) cache for all icons.")
    p.add_argument("--gpu", action="store_true", help="Enable GPU usage for OCR.")
    p.add_argument("--no-resize", action="store_true", help="Disable image downscaling to 1920x1080. Downscales only if screenshot is greater than 1920x1080.")
    p.add_argument("--screenshot", "-s", nargs="+", help="Path to screenshot")
    p.add_argument("--output", "-o", help="Output file prefix to save match summary to. Defaults to stem of the first screenshot.")
    p.add_argument("--write-test-data", action="store_true", help="Write pipeline test data to {output_prefix}_test_data.json")

    args = p.parse_args()

    # Set up console logging with the specified log level
    setup_console_logging(args.log_level)

    # Base config with CLI-specific settings
    config = {
        "debug": True,
        "locate_labels": {
            "gpu": args.gpu
        },
        "crop_label_regions": {
            "participate_learning_data_acquisition": True,
            "label_output_dir": str(Path(args.output_dir) / "label_output" / args.output if args.output else Path(args.output_dir) / "label_output")
        },
        "data_dir": args.data_dir,
        "log_level": args.log_level  # CLI log level will override config file if specified
    }

    # Add config file path if specified
    if args.config_file:
        config["config_file"] = args.config_file

    # Add any explicitly set directory paths from command line
    path_args = [
        "log_dir",
        "icon_dir",
        "overlay_dir",
        "cache_dir",
        "cargo_dir",
        "output_dir",
    ]

    args_dict = vars(args)
    for path_arg in path_args:
        if path_arg not in args_dict:
            continue
        
        if args_dict[path_arg] != p.get_default(path_arg):
            config[path_arg] = args_dict[path_arg]

    # if args.output is not specifed, take the stem of the first screenshot
    if args.output is None and args.screenshot and len(args.screenshot) > 0:
        args.output = Path(args.screenshot[0]).stem

    # Initialize test instrumentation if enabled
    test_collector = None
    if args.write_test_data:
        from sister_sto.utils.test_instrumentation import TestInstrumentationCollector
        test_collector = TestInstrumentationCollector()
        test_collector.record_input(args.screenshot, config)

    # bind callbacks with their arguments and test collector
    bound_on_stage_complete = partial(on_stage_complete, test_collector=test_collector)
    bound_on_pipeline_complete = partial(
        on_pipeline_complete, 
        save_dir=args.output_dir, 
        save_file=args.output,
        test_collector=test_collector
    )

    try:
        import sys

        pipeline = build_default_pipeline(
            on_progress, 
            on_interactive, 
            on_error, 
            config=config, 
            on_metrics_complete=on_metrics_complete, 
            on_stage_start=on_stage_start, 
            on_stage_complete=bound_on_stage_complete, 
            on_task_start=on_task_start, 
            on_task_complete=on_task_complete, 
            on_pipeline_complete=bound_on_pipeline_complete
        )

        if args.download or args.build_hash_cache:
            if args.download:
                print("Downloading icon data from STO Wiki...")
                result: PipelineState = pipeline.execute_task("download_all_icons")

            if args.build_hash_cache:
                print("Building Hash cache...")
                result: PipelineState = pipeline.execute_task("build_hash_cache")

            sys.exit(0)
        
        if args.screenshot is None:
            p.print_help()
            sys.exit(1)

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
    #print(f"[sister-cli.py] Python dependencies load time: {start_time - load_start_time}")
    print(f"[sister-cli.py] Total time: {end_time - start_time}")

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    else:
        # Fallback for older versions
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        
    main()
