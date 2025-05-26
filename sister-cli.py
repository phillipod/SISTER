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

from sto_sister.utils.cargo import CargoDownloader
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

    if stage == 'start_executor_pool':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Started executor pool ({ctx.executor_pool_total} workers)")
        return
    elif stage == 'stop_executor_pool':
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Stopped executor pool")
        return
    elif stage == 'locate_labels':
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
    elif stage == 'output_transformation':
        #tqdm.write(f"[Callback] [on_stage_complete] [{stage}]")
        return
    else:
        tqdm.write(f"[Callback] [on_stage_complete] [{stage}] complete") 
    
    #print(f"[Callback] [on_stage_complete] [{stage}] Output: {output}")
    tqdm.write(f"[Callback] [on_stage_complete] [{stage}] Pretty output: ")
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
            print(f"[Callback] [on_metrics] {"\t" if metric['name'] != 'pipeline' else ""}{metric['name']} took {metric['duration']:.2f} seconds")


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
        ('personal_trait', {'environment': 'ground', 'type': '!reputation,!activereputation', 'chartype': 'char'}, 'ground/traits/personal'),
        ('personal_trait', {'environment': 'ground', 'type': 'reputation', 'chartype': 'char'}, 'ground/traits/reputation'),
        ('personal_trait', {'environment': 'ground', 'type': 'activereputation', 'chartype': 'char'}, 'ground/traits/active_reputation'),
        ('personal_trait', {'environment': 'space', 'type': '!reputation,!activereputation', 'chartype': 'char'}, 'space/traits/personal'),
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

def save_match_summary(output_dir, output_prefix, matches):
    """
    Save the match results to a text file.

    The match results are grouped by icon group and slot, and the best match is
    highlighted along with its score and scale. If there are multiple good matches,
    they are also listed.

    Args:
        output_dir (Path): Directory to save the output file.
        screenshot_path (str): Path to the screenshot file.
        matches (list[dict]): List of match results, each containing the keys
            "icon_group", "top_left", "name", "method", "score", "scale", and
            "overlay_scale".

    Returns:
        None
    """
    output_file = Path(output_dir) / f"{output_prefix}_matches.txt"

    with open(output_file, "w") as f:
        for icon_group, slots in sorted(matches.items()):
            f.write(f"=== Icon Group: {icon_group} ===\n")
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

                # helper to pull out a overlay_scale, even from detected_overlay
                def get_overlay_scale(m):
                    if "detected_overlay" in m and isinstance(m["detected_overlay"], (list, tuple)):
                        return m["detected_overlay"][0]["scale"]
                    elif "overlay_scale" in m:
                        return m["overlay_scale"]
                    return 0.0

                # helper to pull out a overlay, even from detected_overlay
                def get_overlay_name(m):
                    if "detected_overlay" in m and isinstance(m["detected_overlay"], (list, tuple)):
                        return m["detected_overlay"][0]["overlay"]
                    elif "overlay" in m:
                        return m["overlay"]
                    return "unknown"

                best = sorted_matches[0]
                best_overlay = get_overlay_name(best)
                best_qs = get_overlay_scale(best)
                best_scale = best.get("scale", 0.0)
                f.write(
                    f"    BEST: {best.get('name','<unknown>')} ({best_overlay}) "
                    f"using {best.get('method','')} "
                    f"(score {best.get('score',0):.2f}, scale {best_scale:.2f}, "
                    f"overlay scale {best_qs:.2f})\n"
                )

                # if there are any runners-up, list them
                if len(sorted_matches) > 1:
                    f.write("    Others:\n")
                    for m in sorted_matches[1:]:
                        overlay = get_overlay_name(best)
                        qs = get_overlay_scale(m)
                        sc = m.get("scale", 0.0)
                        f.write(
                            f"      - {m.get('name','<unknown>')} ({overlay}) using {m.get('method','')} "
                            f"(score {m.get('score',0):.2f}, scale {sc:.2f}, overlay scale {qs:.2f})\n"
                        )

            f.write("\n")

    return True, output_file #(f"Saved match summary to {output_file}")

if __name__ == "__main__":
    start_time = time.time()

    p = argparse.ArgumentParser()
    p.add_argument("--screenshot", "-s", nargs="+", help="Path to screenshot")
    p.add_argument("--icons", default="images", help="Directory containing downloaded icons. Defaults to 'images' in current directory.")
    p.add_argument("--overlays", default="overlays", help="Directory containing icon overlay images. Defaults to 'overlays' in current directory.")
    p.add_argument("--log-level", default="WARNING", help="Log level: DEBUG, VERBOSE, INFO, WARNING, ERROR")
    p.add_argument("--no-resize", action="store_true", help="Disable image downscaling to 1920x1080. Downscales only if screenshot is greater than 1920x1080.")
    p.add_argument("--download", action="store_true", help="Download icon data from STO Wiki. Exit after.")
    p.add_argument("--build-phash-cache", action="store_true", help="Build a perceptual hash (phash) cache for all icons.")
    p.add_argument("--output_dir", default="output", help="Directory to store output summaries. Defaults to 'output' in current directory.")
    p.add_argument("--output", "-o", help="Output file prefix to save match summary to. Must be specified if more than one screenshot is provided.")
    p.add_argument("--gpu", action="store_true", help="Enable GPU usage for OCR.")

    args = p.parse_args()

    if args.log_level:
        setup_logging(log_level=args.log_level)

    if args.download or args.build_phash_cache:
        if args.download:
            print("Downloading icon data from STO Wiki...")
            download_icons(args.icons)

        if args.build_phash_cache:
            print("Building PHash cache...")
            
            icon_root = Path(args.icons)
            hash_index = HashIndex(icon_root, "phash", match_size=(16, 16))
            overlays = load_overlays(args.overlays)  # Must return dict of overlay -> RGBA overlay np.array
            hash_index.build_with_overlays(overlays)

            print(f"[DONE] Built PHash index with {len(hash_index.hashes)} entries.")

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


    #icon_root = Path(args.icons)
    #hash_index = HashIndex(icon_root, "phash", match_size=(16, 16))
    
    
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
        pipeline = build_default_pipeline(on_progress, on_interactive, on_error, config=config, on_metrics_complete=on_metrics_complete, on_stage_start=on_stage_start, on_stage_complete=on_stage_complete, on_pipeline_complete=bound_on_pipeline_complete)
        result: PipelineState = pipeline.run(images)
        # save_match_summary(args.output_dir, args.output, result[1]["detect_icons"])
    except SISTERError as e:
        print(e)
        import sys
        sys.exit(1)

    end_time = time.time()
#    print(f"[sister-cli.py] Python dependencies load time: {start_time - load_start_time}")
    print(f"[sister-cli.py] Total time: {end_time - start_time}")


    # 4. dump
    #for slot, match in result.icon_matches.items():
    #    print(f"{slot.icon_group_label}[{slot.index}] -> {match}")
