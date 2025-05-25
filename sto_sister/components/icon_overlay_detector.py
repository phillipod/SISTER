import cv2
import numpy as np
import logging
import traceback

from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import shared_memory
from skimage.metrics import structural_similarity as ssim

from imagehash import hex_to_hash
import imagehash
from PIL import Image


from ..utils.image import apply_mask, show_image
from ..metrics.barcode import find_off_strips, compare_barcodes
from ..metrics.mean_hue import classify_overlay_by_patch

logger = logging.getLogger(__name__)


class IconOverlayDetector:
    def __init__(
        self, debug=False, icon_loader=None, overlay_loader=None, hash_index=None, on_progress=None, executor_pool=None
    ):
        """
        Initialize the IconOverlayDetector.
        """
        self.debug = debug
        self.load_icons = icon_loader
        self.load_overlays = overlay_loader
        self.hash_index = hash_index
        self.on_progress = on_progress
        self.executor_pool = executor_pool

    def detect(
        self,
        icon_slots,
        overlays,
        threshold=0.8,
    ):
        """
        Run icon detector using the selected engine.
        """
        self.on_progress("Detecting overlays", 10.0)

        matches = []

        args_list = []
        icon_group_slot_index = []

        for icon_group_label in icon_slots:
            for slot in icon_slots[icon_group_label]:
                idx = slot["Slot"]
                box = slot["Box"]
                roi = slot["ROI"]

                # if icon_group_label != "Hangar":
                #     continue

                logger.debug(
                    f"Running overlay detection for icon group '{icon_group_label}', slot {idx}"
                )

                args_list.append((roi, overlays))
                icon_group_slot_index.append((icon_group_label, idx))


        start_pct = 10.0
        end_pct   = 65.0

        self.on_progress("Detecting overlays", start_pct)

        args_total     = len(args_list)
        args_completed = 0

        detected_overlays_by_icon_group = {}
        
        # unzip your args into four parallel lists
        rois,      overlays_list = zip(*args_list)
        labels,    idxs          = zip(*icon_group_slot_index)

        with self.executor_pool as executor:
            # executor.map will yield results in the same order as the inputs
            results_iter = executor.map(
                identify_overlay,   # the worker function
                rois,                    # 1st arg sequence
                overlays_list,           # 2nd arg sequence
                labels,                  # 3rd arg sequence
                idxs,                    # 4th arg sequence
                chunksize=10,            # process 100 tasks per worker batch
            )

            # now zip labels, idxs and results back together
            for label, idx, result in zip(labels, idxs, results_iter):
                try:
                    detected_overlays_by_icon_group.setdefault(label, {})[idx] = result
                except Exception as e:
                    logger.warning(
                        f"Overlay detection failed for icon group '{label}', slot {idx}: {e}"
                    )
                    traceback.print_exc()
                args_completed += 1
                
                if args_completed % 10 == 0 or args_completed == args_total:
                    frac       = args_completed / args_total
                    scaled_pct = start_pct + frac * (end_pct - start_pct)

                    sub = f"{args_completed}/{args_total}"
                    self.on_progress(f"Detecting overlays -> {sub}", scaled_pct)

        # detected_overlays_by_icon_group = {}
        # with ProcessPoolExecutor() as executor:
        #     futures = {
        #         executor.submit(
        #             self.identify_overlay, roi, overlays, icon_group_label, idx
        #         ): (
        #             icon_group_label,
        #             idx,
        #         )
        #         for (roi, overlays), (icon_group_label, idx) in zip(
        #             args_list, icon_group_slot_index
        #         )
        #     }

        #     for future in as_completed(futures):
        #         icon_group_label, idx = futures[future]
        #         try:
        #             # overlay, scale, method = future.result()
        #             detected_overlays_by_icon_group.setdefault(icon_group_label, {})[
        #                 idx
        #             ] = future.result()
        #         except Exception as e:
        #             logger.warning(
        #                 f"Overlay detection failed for icon group '{icon_group_label}', slot {idx}: {e}"
        #             )
        #             traceback.print_exc()

        logger.debug("Overlay detection complete.")

        # print(detected_overlays_by_icon_group)
        # import sys
        # sys.exit()
        return detected_overlays_by_icon_group

def identify_overlay(
    #self,
    region_crop,
    overlays,
    icon_group_label=None,
    slot=None,
    step=1,
    scales=np.linspace(0.6, 0.7, 11),
):
    debug = True

    def overlay_mask(overlay_type, shape, box_width=8):
        """
        Returns an H×W float mask that is 1 inside the bottom-left box
        (half the image height, box_width columns) and 0 elsewhere.
        """
        H, W = shape
        half_h = H // 6
        start_row = H - (half_h * 5)
        bulge_row = H - (half_h * 3)
        mask = np.zeros((H, W), dtype=np.float32)
        mask[0:H, 0 : (box_width // 2)] = 1.0

        return mask

    def roi_crop(roi, box_width=3):
        H, W = roi.shape[:2]
        return roi[0:H, 0:(box_width)]

    # print(f"Identifying overlay for {icon_group_label}#{slot}")

    best_score = -np.inf
    best_overlay = "common"
    best_scale = 1.0
    best_method = "fallback"

    show_image_list = []
    best_masked_region = None
    best_masked_overlay = None

    barcode_width = 3

    def must_inspect(inspection_list, icon_group_label, slot):
        if icon_group_label in inspection_list:
            # check if inspection_list[icon_group_label] is a dict or a bool
            if isinstance(inspection_list[icon_group_label], dict):
                if "_all" in inspection_list[icon_group_label]:
                    return inspection_list[icon_group_label]["_all"]

                slot_key = str(slot)

                if slot_key in inspection_list[icon_group_label]:
                    return inspection_list[icon_group_label][slot_key]
            elif isinstance(inspection_list[icon_group_label], bool):
                return inspection_list[icon_group_label]
            else:
                raise ValueError(
                    f"inspection_list[{icon_group_label}] must be a dict or a bool"
                )

        return False

    inspection_list = {
        # "Fore Weapon": {
        #     "0": True
        # },
        # "Hangar": True,
        # "Body": True,
        # "Universal Console": {
        #     "2": True
        # },
        # "Tactical Console": {
        #    "2": True
        # },
        # "Engineering Console": {
        #     "1": True,
        #     "2": True,
        # },
        # "Deflector": True,
        # "Kit Modules": {
        #    "0": True
        # },
        # "Devices": {
        #    "2": True
        # }
    }

    original_region_crop_shape = region_crop.shape
    # if region_crop.shape[0] > (43 * 1.1) or region_crop.shape[1] > (33*1.1):
    # if region_crop.shape[0] > (43 * 1.1) or region_crop.shape[1] > (33*1.1):
    if region_crop.shape[0] != 47 or region_crop.shape[1] != 36:
        scale_factor = min(47 / region_crop.shape[0], 36 / region_crop.shape[1])
        region_crop = cv2.resize(
            region_crop.copy(),
            None,
            fx=scale_factor,
            fy=scale_factor,
            interpolation=cv2.INTER_AREA,
        )

    overlay_detections = []

    for overlay_name, overlay in reversed(list(overlays.items())):
        if overlay_name == "common":
            continue

        # logger.debug(f"Trying overlay {overlay_name}")
        if must_inspect(inspection_list, icon_group_label, slot):
            print(
                f"{icon_group_label}#{slot}: {overlay_name}: Begin: overlay=[{overlay.shape}] region=[{region_crop.shape}]"
            )

        overlay_rgb = overlay[:, :, :3]
        overlay_alpha = overlay[:, :, 3] / 255.0

        # Barcode Overlay setup
        barcode_overlay = roi_crop(overlay_rgb.copy(), barcode_width)

        # barcode_overlay_common_segments = find_common_off_segments(barcode_overlay,
        #                                   ignore_top_frac=0.1,
        #                                   ignore_top_rows=0,
        #                                   tolerance_rows=1)
        (
            barcode_overlay_detected_overlay_by_patch,
            h_deg,
        ) = classify_overlay_by_patch(barcode_overlay)

        # Barcode Region setup
        barcode_region = roi_crop(region_crop.copy(), barcode_width)

        # barcode_region_common_segments = find_common_off_segments(barcode_region,
        #                                   ignore_top_frac=0.1,
        #                                   ignore_top_rows=0,
        #                                   tolerance_rows=1)

        # barcode_match, barcode_overlay_common_segments, barcode_region_common_segments = compare_barcodes_simple(barcode_overlay, barcode_region)
        (
            barcode_match,
            barcode_overlay_common_segments,
            barcode_region_common_segments,
        ) = compare_barcodes(barcode_overlay, barcode_region)
        barcode_overlay_stripes = len(barcode_overlay_common_segments)
        barcode_region_stripes = len(barcode_region_common_segments)

        # diff = compare_patches(barcode_region, barcode_overlay)

        if must_inspect(inspection_list, icon_group_label, slot):
            print(
                f"{icon_group_label}#{slot}: {overlay_name}: Scale: Barcode spatial match: {barcode_match}"
            )
            print(
                f"{icon_group_label}#{slot}: {overlay_name}: Scale: Barcode stripe match: overlay={barcode_overlay_stripes} region={barcode_overlay_stripes}"
            )
            print(
                f"{icon_group_label}#{slot}: {overlay_name}: Scale: Overlay detected by patch: {barcode_overlay_detected_overlay_by_patch} - {h_deg}°"
            )

        orig_mask = overlay_mask(overlay_name, overlay_alpha.shape)

        for scale in scales:
            # logger.debug(f"Trying scale {scale}")
            # print(f"{icon_group_label}#{slot}: Trying scale {scale}")
            resized_rgb = cv2.resize(
                overlay_rgb,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_LINEAR,
            )
            resized_alpha = cv2.resize(
                orig_mask,
                (resized_rgb.shape[1], resized_rgb.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )

            resized_mask = cv2.resize(
                orig_mask,
                (resized_rgb.shape[1], resized_rgb.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )
            final_alpha = resized_alpha * resized_mask

            h, w = resized_rgb.shape[:2]
            H, W = region_crop.shape[:2]

            if must_inspect(inspection_list, icon_group_label, slot):
                print(
                    f"{icon_group_label}#{slot}: {overlay_name}: Scale: Begin : scale=[{scale}], overlay=[{resized_rgb.shape}], region=[{region_crop.shape}], original_region=[{original_region_crop_shape}]"
                )

            if h > H or w > W:
                if must_inspect(inspection_list, icon_group_label, slot):
                    print(
                        f"{icon_group_label}#{slot}: {overlay_name}: Scale: Skipping: scale=[{scale}], overlay=[{resized_rgb.shape}], region=[{region_crop.shape}]"
                    )
                continue

            step_limit = 5

            step_count_y = 0
            for y in range(0, H - h, step):
                step_count_y += 1
                if step_count_y > step_limit:
                    break

                step_count_x = 0
                for x in range(0, W - w, step):
                    step_count_x += 1
                    if step_count_x > step_limit:
                        break
                    # print(f"{icon_group_label}#{slot}: {overlay_name}: {step_count_y}/{step_limit} {step_count_x}/{step_limit}")
                    roi = region_crop[y : y + h, x : x + w]

                    masked_region = (roi * final_alpha[..., np.newaxis]).astype(
                        np.uint8
                    )
                    masked_overlay = (
                        resized_rgb * final_alpha[..., np.newaxis]
                    ).astype(np.uint8)

                    # print(f"Shapes: region_crop: {region_crop.shape}, roi: {roi.shape}, masked_region: {masked_region.shape}, masked_overlay: {masked_overlay.shape}")
                    barcode_region = roi_crop(
                        cv2.resize(
                            masked_region.copy(),
                            (overlay_rgb.shape[1], overlay_rgb.shape[0]),
                        ),
                        barcode_width,
                    )

                    # Barcode Region setup

                    # Check colour and intensity patch
                    # barcode_diff = compare_patches(barcode_region, barcode_overlay)

                    (
                        barcode_region_detected_overlay_by_patch,
                        _,
                    ) = classify_overlay_by_patch(barcode_region)

                    # barcode_match, barcode_overlay_common_segments, barcode_region_common_segments = compare_barcodes_simple(barcode_overlay, barcode_region)
                    (
                        barcode_match,
                        barcode_overlay_common_segments,
                        barcode_region_common_segments,
                    ) = compare_barcodes(barcode_overlay, barcode_region)
                    barcode_overlay_stripes = len(barcode_overlay_common_segments)
                    barcode_region_stripes = len(barcode_region_common_segments)

                    if not barcode_match and not must_inspect(
                        inspection_list, icon_group_label, slot
                    ):
                        # print(f"{icon_group_label}#{slot}: Skipping due to mismatched barcodes: {overlay_name}: {barcode_overlay_stripes} vs {barcode_region_stripes}")
                        continue
                    # else:
                    #     print(f"{icon_group_label}#{slot}: {overlay_name}: {barcode_overlay_stripes} vs {barcode_region_stripes}")

                    if (
                        barcode_region_detected_overlay_by_patch != overlay_name
                    ):  #  and not must_inspect(inspection_list, icon_group_label, slot):
                        continue

                    # Binarise regions for SSIM
                    barcode_region_binarized = cv2.adaptiveThreshold(
                        cv2.cvtColor(barcode_region, cv2.COLOR_BGR2GRAY),
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        11,
                        2,
                    )
                    barcode_overlay_binarized = cv2.adaptiveThreshold(
                        cv2.cvtColor(barcode_overlay, cv2.COLOR_BGR2GRAY),
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        11,
                        2,
                    )

                    try:
                        barcode_region_ssim = cv2.copyMakeBorder(
                            barcode_region_binarized,
                            top=0,
                            bottom=0,
                            left=0,
                            right=7,
                            borderType=cv2.BORDER_CONSTANT,
                            value=0,
                        )
                        barcode_overlay_ssim = cv2.copyMakeBorder(
                            barcode_overlay_binarized,
                            top=0,
                            bottom=0,
                            left=0,
                            right=7,
                            borderType=cv2.BORDER_CONSTANT,
                            value=0,
                        )

                        # if must_inspect(inspection_list, icon_group_label, slot):
                        #     show_image([barcode_region_ssim, barcode_overlay_ssim])

                        score = ssim(barcode_region_ssim, barcode_overlay_ssim)
                        # score = ssim(masked_region[:, :10], masked_overlay[:, :10], channel_axis=-1)
                        # score = ssim(masked_region, masked_overlay, channel_axis=-1)
                        # score = ssim(gray_region, gray_overlay)
                    except ValueError:
                        print(
                            f"{icon_group_label}#{slot}: Skipping due to ValueError: {overlay_name}"
                        )
                        continue

                    if must_inspect(inspection_list, icon_group_label, slot):
                        barcode_region_binarized = cv2.adaptiveThreshold(
                            cv2.cvtColor(barcode_region, cv2.COLOR_BGR2GRAY),
                            255,
                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY,
                            11,
                            2,
                        )
                        barcode_overlay_binarized = cv2.adaptiveThreshold(
                            cv2.cvtColor(barcode_overlay, cv2.COLOR_BGR2GRAY),
                            255,
                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY,
                            11,
                            2,
                        )

                        print(
                            f"{icon_group_label}#{slot}: {overlay_name}: Scale: After SSIM: scale=[{scale}] score=[{score:.4f}]"
                        )
                        print(
                            f"{icon_group_label}#{slot}: {overlay_name}: Scale: Is best score? [{"Yes" if score > best_score else f"No - best score: {best_score:.4f}"}]"
                        )
                        print(
                            f"{icon_group_label}#{slot}: {overlay_name}: Scale: Barcode spatial match: {barcode_match}"
                        )
                        print(
                            f"{icon_group_label}#{slot}: {overlay_name}: Scale: Barcode stripe match: overlay={barcode_overlay_stripes} region={barcode_overlay_stripes}"
                        )
                        print(
                            f"{icon_group_label}#{slot}: {overlay_name}: Scale: Region by patch: {classify_overlay_by_patch(barcode_region)}"
                        )
                        print(
                            f"{icon_group_label}#{slot}: {overlay_name}: Scale: Overlay by patch: {classify_overlay_by_patch(barcode_overlay)}"
                        )
                        show_image(
                            [
                                region_crop,
                                roi,
                                masked_region,
                                masked_overlay,
                                barcode_region,
                                barcode_overlay,
                                barcode_region_binarized,
                                barcode_overlay_binarized,
                            ]
                        )
                        print()

                    if score > 0.75 and score > best_score:
                        if must_inspect(inspection_list, icon_group_label, slot):
                            if not barcode_match:
                                continue
                            if (
                                barcode_region_detected_overlay_by_patch
                                != overlay_name
                            ):
                                continue

                        best_score = score
                        best_overlay = overlay_name
                        best_scale = scale
                        best_method = "ssim"

                        best_masked_region = masked_region
                        best_masked_overlay = masked_overlay

                        overlay_detections.append(
                            {
                                "overlay": best_overlay,
                                "scale": best_scale,
                                "method": best_method,
                                "ssim_score": best_score,
                                "region": icon_group_label,
                                "slot": slot,
                                "step_x": x,
                                "step_y": y,
                            }
                        )

    # print(f"{icon_group_label}#{slot}: Detected overlays: {overlay_detections.get(icon_group_label, {})}")
    # print(f"{icon_group_label}#{slot}: Best matched overlay: {best_overlay} with score {best_score:.4f} at scale {best_scale:.4f} using {best_method}")
    # show_image([region_crop, overlays[best_overlay], best_masked_region, best_masked_overlay])

    # return overlay_detections inline sorted on ssim_score descending
    if len(overlay_detections) == 0:
        return [
            {
                "overlay": "common",
                "scale": 0.6,
                "method": "fallback",
                "step_x": None,
                "step_y": None,
            }
        ]

    return [
        (sorted(overlay_detections, key=lambda x: x["ssim_score"], reverse=True))[0]
    ]
    # return overlay_detections
