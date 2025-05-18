import os
import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim
from collections import Counter
from ...utils.image import apply_mask, show_image

from imagehash import hex_to_hash
import imagehash
from PIL import Image

from ...hashers.phash import compute

def dynamic_hamming_cutoff(scores, best_score, max_next_ranks=2, max_allowed_gap=4):
    freqs = Counter(scores)
    sorted_scores = sorted(freqs.items())

    threshold = best_score
    previous = best_score

    rank_count = 0
    for score, count in sorted_scores:
        if score == best_score:
            continue

        # if this next tier is a massive jump from the best, break
        if score - previous > max_allowed_gap:
            break

        threshold = score
        previous = score
        rank_count += 1

        if rank_count >= max_next_ranks:
            break

    return threshold

# def show_image(
#     imgs, window_name='Images', bg_color=(0,0,0)
# ):
#     if not imgs:
#         raise ValueError("No images to display")

#     def ensure_uint8(img):
#         if img.dtype == np.uint8:
#             return img
#         mn, mx = float(img.min()), float(img.max())
#         if mx == mn:
#             return np.zeros(img.shape, dtype=np.uint8)
#         norm = (img - mn) * (255.0 / (mx - mn))
#         return norm.astype(np.uint8)

#     def to_bgr8(img):
#         img8 = ensure_uint8(img)
#         if img8.ndim == 2:
#             return cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR)
#         if img8.shape[2] == 4:
#             return cv2.cvtColor(img8, cv2.COLOR_BGRA2BGR)
#         return img8

#     # preprocess all to 3-channel uint8
#     processed = [to_bgr8(img) for img in imgs]

#     # compute full canvas size
#     heights = [im.shape[0] for im in processed]
#     widths  = [im.shape[1] for im in processed]
#     H, W = max(heights), sum(widths)

#     # build the canvas
#     canvas = np.full((H, W, 3), bg_color, dtype=np.uint8)
#     x = 0
#     for im in processed:
#         h, w = im.shape[:2]
#         canvas[0:h, x:x+w] = im
#         x += w

#     # create a resizable window that keeps aspect ratio
#     flags = cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO
#     cv2.namedWindow(window_name, flags)
#     cv2.resizeWindow(window_name, W, H)
#     cv2.setWindowProperty(
#         window_name,
#         cv2.WND_PROP_ASPECT_RATIO,
#         cv2.WINDOW_KEEPRATIO
#     )

#     cv2.imshow(window_name, canvas)
#     # block until user closes window (X) or presses 'x'
#     while True:
#         if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
#             break
#         if cv2.waitKey(100) & 0xFF == ord('x'):
#             break

#     cv2.destroyWindow(window_name)



def identify_overlay(region_crop, overlays, region_label=None, slot=None, step=1, scales=np.linspace(0.6, 0.8, 20)):
    debug = True

    def find_off_segments(bin_vals, ignore_top_frac=0.1, ignore_top_rows=0):
        """
        Identify runs of 0s in a 1-D binary array, but ignore any segments
        that start in the top ignored region (first ignore_top_frac of rows).
        """
        H = bin_vals.shape[0]

        # find all zero runs
        segments = []
        in_zero = False
        start = None
        for i, v in enumerate(bin_vals):
            if not in_zero and v == 0:
                in_zero = True
                start = i
            elif in_zero and v == 1:
                segments.append((start, i - 1))
                in_zero = False
        if in_zero:
            segments.append((start, H - 1))

        # compute top margin (rows to ignore at start of array)
        margin = ignore_top_rows if ignore_top_rows > 0 else int(H * ignore_top_frac)
        min_valid_start = margin

        # filter out those that begin in the ignored zone
        return [(s, e) for (s, e) in segments if s >= min_valid_start]


    def find_common_off_segments(bin2d,
                                ignore_top_frac=0.1,
                                ignore_top_rows=0,
                                tolerance_rows=1):
        """
        Find zero-runs (within tolerance) in EVERY column of a 2-D binary map—
        but only in the leftmost 3 columns where the stripes live.
        """
        # — binarize if needed —
        if bin2d.ndim == 3:
            gray = cv2.cvtColor(bin2d, cv2.COLOR_BGR2GRAY)
            if gray.dtype != np.uint8:
                gray = np.clip(gray, 0, 255).astype(np.uint8)
            _, bin2d = cv2.threshold(
                gray, 0, 1,
                cv2.THRESH_OTSU
            )
        elif bin2d.ndim != 2:
            raise ValueError(f"Expected 2D or 3D input, got shape {bin2d.shape!r}")

        # restrict to the leftmost 3 columns
        H, W = bin2d.shape
        stripe_roi = bin2d[:, :3]

        # get zero-runs per column
        col_segs = [
            find_off_segments(stripe_roi[:, j], ignore_top_frac, ignore_top_rows)
            for j in range(3)
        ]

        # find common overlaps
        common = []
        for s0, e0 in col_segs[0]:
            if all(
                any((e + tolerance_rows >= s0) and (s - tolerance_rows <= e0)
                    for s, e in segs_j)
                for segs_j in col_segs[1:]
            ):
                common.append((s0, e0))
        return common

    def luminance_bgr(col_arr):
        return 0.2126 * col_arr[...,2] + 0.7152 * col_arr[...,1] + 0.0722 * col_arr[...,0]
           
    def overlay_mask(overlay_type, shape, box_width=8):
        """
        Returns an H×W float mask that is 1 inside the bottom-left box
        (half the image height, box_width columns) and 0 elsewhere.
        """
        H, W = shape
        half_h = H // 6
        start_row = H - (half_h*5)
        bulge_row = H - (half_h*3)
        mask = np.zeros((H, W), dtype=np.float32)
        # mask[0:5, 0:W] = 1.0
        # mask[start_row:H, 0:(box_width//2)] = 1.0
        #mask[0:5, 0:W] = 1.0
        mask[0:H, 0:(box_width//2)] = 1.0
        #mask[bulge_row:H, 0:(box_width)] = 1.0


        #if overlay_type == "rare":
        #    print(f"overlay_type: {overlay_type}")
            #mask[bulge_row:10, 0:(box_width)] = 0.0
            
        return mask

    def roi_crop(roi, box_width=3):
        H, W = roi.shape[:2]
        return roi[0:H, 0:(box_width)]


    def extract_bottom_left_patch(img, patch_height=9, patch_width=3):
        """
        Extract a bottom-left patch of given height and width from an HxW(xC) array.
        """
        H, W = img.shape[:2]
        return img[H-patch_height:H, 0:patch_width]


    def patch_profile(patch):
        """
        Compute mean and std for BGR channels and luminance of a patch.
        Returns (mean_bgr, std_bgr, mean_lum, std_lum).
        """
        flat = patch.reshape(-1, patch.shape[-1])  # Nx3
        mean_bgr = flat.mean(axis=0)
        std_bgr = flat.std(axis=0)
        lum = luminance_bgr(patch)
        return mean_bgr, std_bgr, lum.mean(), lum.std()


    def hsv_profile(patch, min_sat=0.2, min_val=0.2):
        """
        Compute circular mean and std of hue and mean/std of saturation & value for a BGR patch,
        ignoring pixels below given saturation or value thresholds (i.e., dark or gray).
        Returns (mean_hue_deg, std_hue_deg, mean_sat, std_sat, mean_val, std_val),
        or (None, None, sat_mean, sat_std, val_mean, val_std) if no colorful pixels.
        """
        # Convert to HSV
        hsv = cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_BGR2HSV)
        h = hsv[...,0].astype(np.float32) / 179.0 * 360.0  # degrees
        s = hsv[...,1].astype(np.float32) / 255.0
        v = hsv[...,2].astype(np.float32) / 255.0

        # Mask colorful pixels only
        mask = (s >= min_sat) & (v >= min_val)
        if not np.any(mask):
            # No colorful pixels: fallback to stats on full patch luminance/saturation
            return None, None, s.mean(), s.std(), v.mean(), v.std()

        # Filtered channels
        h_f = h[mask]
        s_f = s[mask]
        v_f = v[mask]

        # Circular hue mean/std
        rad = np.deg2rad(h_f)
        sin_mean = np.mean(np.sin(rad))
        cos_mean = np.mean(np.cos(rad))
        mean_angle = np.arctan2(sin_mean, cos_mean)
        mean_hue = (np.rad2deg(mean_angle) + 360) % 360
        R = np.sqrt(sin_mean**2 + cos_mean**2)
        std_hue = np.sqrt(-2 * np.log(max(R, 1e-8))) * (180/np.pi)

        return mean_hue, std_hue, s_f.mean(), s_f.std(), v_f.mean(), v_f.std()


    def compare_patches(region_arr, overlay_arr, patch_height=9, patch_width=3, min_sat=0.2, min_val=0.2):
        """
        Compare bottom-left patches of two images in BGR, luminance, and HSV profiles,
        ignoring dark/gray pixels for hue calculations.

        Returns a dict with:
        - reg_mean_hue, ovl_mean_hue: mean hues in degrees or None,
        - hue_diff_deg: minimal angular diff or None,
        - sat_diff, val_diff: abs diff of mean saturation/value,
        - diff_mean_bgr, diff_std_bgr: abs diffs of BGR means/stds,
        - diff_mean_lum, diff_std_lum: abs diffs of luminance.
        """
        region_rgb = region_arr[..., :3]
        overlay_rgb = overlay_arr[..., :3]
        reg_patch = extract_bottom_left_patch(region_rgb, patch_height, patch_width)
        ovl_patch = extract_bottom_left_patch(overlay_rgb, patch_height, patch_width)

        # BGR + luminance stats
        reg_mean, reg_std, reg_lum_mean, reg_lum_std = patch_profile(reg_patch)
        ovl_mean, ovl_std, ovl_lum_mean, ovl_lum_std = patch_profile(ovl_patch)

        # HSV with colorful mask
        reg_hue, _, reg_sat, _, reg_val, _ = hsv_profile(reg_patch, min_sat, min_val)
        ovl_hue, _, ovl_sat, _, ovl_val, _ = hsv_profile(ovl_patch, min_sat, min_val)
        if reg_hue is None or ovl_hue is None:
            hue_diff = None
        else:
            dh = abs(reg_hue - ovl_hue)
            hue_diff = min(dh, 360 - dh)

        return {
            "reg_mean_hue":   reg_hue,
            "ovl_mean_hue":   ovl_hue,
            "hue_diff_deg":   hue_diff,
            "sat_diff":       abs(reg_sat - ovl_sat),
            "val_diff":       abs(reg_val - ovl_val),
            "diff_mean_bgr":  np.abs(reg_mean - ovl_mean),
            "diff_std_bgr":   np.abs(reg_std - ovl_std),
            "diff_mean_lum":  abs(reg_lum_mean - ovl_lum_mean),
            "diff_std_lum":   abs(reg_lum_std - ovl_lum_std),
        }

    # -- Color classification (more granular) --

    HUE_DIFF_THRESHOLD = 30  # degrees: typical threshold to consider hues distinct


    def is_significant_hue_diff(hue_diff, threshold=HUE_DIFF_THRESHOLD):
        """Return True if hue difference exceeds threshold and hue_diff is not None."""
        return hue_diff is not None and hue_diff >= threshold



    def classify_overlay_by_hue(mean_hue):
        """
        Map a mean hue (°) to overlay rarity:
        None             → 'common'
        45 ≤ hue < 75    → 'epic'
        75 ≤ hue < 150   → 'uncommon'
        195 ≤ hue < 225  → 'rare'
        225 ≤ hue < 270  → 'ultra rare'
        otherwise        → 'common'
        """
        if mean_hue is None:
            return 'unknown'
            
        h = mean_hue % 360
        if 50 <= h < 65:
            return 'epic'
        elif 100 <= h < 130:
            return 'uncommon'
        elif 200 <= h < 220:
            return 'rare'
        elif 230 <= h < 255:
            return 'ultra rare'
        elif 255 <= h < 300:
            return 'very rare'
        return 'unknown'

    def classify_overlay_by_patch(patch, min_sat=0.2, min_val=0.3, frac_thresh=0.3):
        """
        Classify an overlay based on its bottom-left patch's hue,
        ignoring grayscale/dark regions by requiring a minimum fraction of colorful pixels.

        Parameters:
        - patch: HxWx3 BGR image patch
        - min_sat: minimum saturation (0–1) to consider a pixel colorful
        - min_val: minimum value (0–1) to consider a pixel colorful
        - frac_thresh: minimum fraction (0–1) of patch pixels that must be colorful

        Returns one of: 'common', 'epic', 'uncommon', 'rare', 'ultra rare', 'very rare'
        """
        # Convert to HSV
        hsv = cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_BGR2HSV)
        h = hsv[...,0].astype(np.float32) / 179.0 * 360.0
        s = hsv[...,1].astype(np.float32) / 255.0
        v = hsv[...,2].astype(np.float32) / 255.0

        # Mask out non-colorful pixels
        mask = (s >= min_sat) & (v >= min_val)
        frac_colorful = mask.sum() / mask.size
        if frac_colorful < frac_thresh:
            return f"common", f"({frac_colorful:.2f}) (s: {s.mean():.2f}, v: {v.mean():.2f})"

        # Compute circular mean hue
        h_f = h[mask]
        rad = np.deg2rad(h_f)
        sin_mean = np.mean(np.sin(rad))
        cos_mean = np.mean(np.cos(rad))
        mean_angle = np.arctan2(sin_mean, cos_mean)
        mean_hue = (np.rad2deg(mean_angle) + 360) % 360

        # Classify by narrowed hue bands
        h_deg = mean_hue
        if 40 <= h_deg < 60:
            return "epic", h_deg # ({h_deg:.1f}°)"
        elif 100 <= h_deg < 115:
            return "uncommon", h_deg # ({h_deg:.1f}°)"
        elif 205 <= h_deg < 220:
            return "rare", h_deg # ({h_deg:.1f}°)"
        elif 230 <= h_deg < 250:
            return "ultra rare", h_deg # ({h_deg:.1f}°)"
        elif 245 <= h_deg < 263:
            return "very rare", h_deg # ({h_deg:.1f}°)"
        elif 263 <= h_deg < 290:
            return "ultra rare", h_deg # ({h_deg:.1f}°)"
        else:
            return "unknown", h_deg

    #print(f"Identifying overlay for {region_label}#{slot}")
   
    best_score = -np.inf
    best_quality = "common"
    best_scale = 1.0
    best_method = "fallback"

    show_image_list = []
    best_masked_region = None
    best_masked_overlay = None 

    barcode_width = 3

    def must_inspect(inspection_list, region_label, slot):
        if region_label in inspection_list:
            # check if inspection_list[region_label] is a dict or a bool
            if isinstance(inspection_list[region_label], dict):
                if "_all" in inspection_list[region_label]:
                    return inspection_list[region_label]["_all"]
                
                if slot in inspection_list[region_label]:
                    return inspection_list[region_label][slot]
            elif isinstance(inspection_list[region_label], bool):
                return inspection_list[region_label]
            else:
                raise ValueError("inspection_list[region_label] must be a dict or a bool")

        return False
    
    inspection_list = {
        "Fore Weapon": {
            "0": True
        },
        "Hangar": {
            "_all": True
        },
        "Body": {
            "_all": True
        },
    }
    for quality_name, overlay in reversed(list(overlays.items())):
        if quality_name == "common" and best_score > 0.96:
            continue
        # logger.debug(f"Trying quality overlay {quality_name}")
        if must_inspect(inspection_list, region_label, slot):
            print(f"{region_label}#{slot}: {quality_name}: Begin: overlay=[{overlay.shape}] region=[{region_crop.shape}]")

        overlay_rgb = overlay[:, :, :3]
        overlay_alpha = overlay[:, :, 3] / 255.0

        # Barcode Overlay setup
        barcode_overlay = roi_crop(overlay_rgb.copy(), barcode_width)

        barcode_overlay_common_segments = find_common_off_segments(barcode_overlay,
                                           ignore_top_frac=0.1,
                                           ignore_top_rows=0,
                                           tolerance_rows=1)
        barcode_overlay_detected_overlay_by_patch, h_deg = classify_overlay_by_patch(barcode_overlay)
        barcode_overlay_stripes = len(barcode_overlay_common_segments)
  
        # Barcode Region setup
        barcode_region = roi_crop(region_crop.copy(), barcode_width)

        barcode_region_common_segments = find_common_off_segments(barcode_region,
                                           ignore_top_frac=0.1,
                                           ignore_top_rows=0,
                                           tolerance_rows=1)
        barcode_region_stripes = len(barcode_region_common_segments)

        diff = compare_patches(barcode_region, barcode_overlay)
        
        if must_inspect(inspection_list, region_label, slot):
            print(f"{region_label}#{slot}: {quality_name} Barcode stripes: [{barcode_overlay_stripes} :: {barcode_region_stripes}]")  
            print(f"{region_label}#{slot}: {quality_name}: Significant hue difference? {is_significant_hue_diff(diff["hue_diff_deg"])}")
            print(f"{region_label}#{slot}: {quality_name}: Region color: {classify_overlay_by_hue(diff["reg_mean_hue"])}")
            print(f"{region_label}#{slot}: {quality_name}: Overlay color: {classify_overlay_by_hue(diff["ovl_mean_hue"])}")
            print(f"{region_label}#{slot}: {quality_name}: Overlay detected by patch: {barcode_overlay_detected_overlay_by_patch} - {h_deg}°")

        # print(f"{region_label}#{slot}: Diff for overlay {quality_name}: {diff}")
        # if (region_label in ["Devices"] and slot == 4): # and (quality_name == 'rare' or quality_name == 'very rare' or quality_name == 'common')): # or quality_name == 'very rare'): # or region_label in ["Hangar"]:
            # print (f"{region_label}#{slot}: BARCODE BEGIN: Barcodes for overlay {quality_name}: {barcode_overlay_stripes}, region {barcode_region_stripes}")
            # show_image([region_crop, overlay_rgb, barcode_region, barcode_overlay])

        # show_image([region_crop, overlay_rgb, barcode_region, barcode_overlay])    
        orig_mask = overlay_mask(quality_name, overlay_alpha.shape)

        for scale in scales:
            
            # logger.debug(f"Trying scale {scale}")
            #print(f"{region_label}#{slot}: Trying scale {scale}")
            resized_rgb = cv2.resize(
                overlay_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR
            )
            resized_alpha = cv2.resize(
                orig_mask,
                (resized_rgb.shape[1], resized_rgb.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )

            resized_mask = cv2.resize(
                orig_mask,
                (resized_rgb.shape[1], resized_rgb.shape[0]),
                interpolation=cv2.INTER_LINEAR
            )
            final_alpha = resized_alpha * resized_mask

            h, w = resized_rgb.shape[:2]
            H, W = region_crop.shape[:2]

            if must_inspect(inspection_list, region_label, slot):                
                print(f"{region_label}#{slot}: {quality_name}: Scale: Begin : scale=[{scale}], overlay=[{resized_rgb.shape}], region=[{region_crop.shape}]")

            if h > H or w > W:
                if must_inspect(inspection_list, region_label, slot):
                    print(f"{region_label}#{slot}: {quality_name}: Scale: Skipping: scale=[{scale}], overlay=[{resized_rgb.shape}], region=[{region_crop.shape}]")
                continue

            step_limit = 4

            step_count_y = 0
            for y in range(0, H - h + 1, step):
                step_count_y += 1
                if step_count_y > step_limit:
                    break
                
                step_count_x = 0
                for x in range(0, W - w + 1, step):
                    step_count_x += 1
                    if step_count_x > step_limit:
                        break
                    #print(f"{region_label}#{slot}: {quality_name}: {step_count_y}/{step_limit} {step_count_x}/{step_limit}")
                    roi = region_crop[y : y + h, x : x + w]

                    masked_region = (roi * final_alpha[..., np.newaxis]).astype(np.uint8)
                    masked_overlay = (resized_rgb * final_alpha[..., np.newaxis]).astype(np.uint8)

                    #print(f"Shapes: region_crop: {region_crop.shape}, roi: {roi.shape}, masked_region: {masked_region.shape}, masked_overlay: {masked_overlay.shape}")
                    #barcode_region = roi_crop(masked_region.copy(), barcode_width)
                    barcode_region = roi_crop(cv2.resize(masked_region.copy(), (overlay_rgb.shape[1], overlay_rgb.shape[0])), barcode_width)
                    #barcode_region = cv2.resize(barcode_region, (barcode_overlay.shape[1], barcode_overlay.shape[0]), interpolation=cv2.INTER_LINEAR)   
                    
                    # Convert to grayscale before SSIM calculation      
                    #gray_region  = cv2.cvtColor(masked_region,  cv2.COLOR_BGR2GRAY)
                    #gray_overlay = cv2.cvtColor(masked_overlay, cv2.COLOR_BGR2GRAY)

                    # Barcode Region setup

                    # Check colour and intensity patch
                    barcode_diff = compare_patches(barcode_region, barcode_overlay)

                    barcode_region_detected_overlay_by_patch, _ = classify_overlay_by_patch(barcode_region)

                    barcode_region_common_segments = find_common_off_segments(barcode_region,
                                           ignore_top_frac=0.1,
                                           ignore_top_rows=0,
                                           tolerance_rows=1)
                    barcode_region_stripes = len(barcode_region_common_segments)
                    
                    #print(f"{region_label}#{slot}: Classify hue {quality_name} {region_label}#{slot}")
                    #print(f"{region_label}#{slot}: Region color: {classify_hue(barcode_diff["reg_mean_hue"])}")
                    #print(f"{region_label}#{slot}: Overlay color: {classify_hue(barcode_diff["ovl_mean_hue"])}")


                    # if barcode_overlay_stripes != barcode_region_stripes:
                    #     # print(f"{region_label}#{slot}: Skipping due to mismatched barcodes: {quality_name}: {barcode_overlay_stripes} vs {barcode_region_stripes}")
                    #     #print(f"{region_label}#{slot}: Skipping due to mismatched barcodes: {quality_name}: {barcode_overlay_slanted_lines} vs {barcode_region_slanted_lines}")
                    #     continue
                    # else:
                    #     #print(f"{region_label}#{slot}: {quality_name}: {barcode_overlay_slanted_lines} vs {barcode_region_slanted_lines}")
                    #     print(f"{region_label}#{slot}: {quality_name}: {barcode_overlay_stripes} vs {barcode_region_stripes}")

                    #if classify_overlay_by_hue(barcode_diff["reg_mean_hue"]) != quality_name:
                        # print(f"{region_label}#{slot}: Skipping due to mismatched hue: {quality_name}: {classify_overlay_by_hue(barcode_diff['reg_mean_hue'])} vs {quality_name}")
                    #    continue

                    
                    # if barcode_region_detected_overlay_by_patch != quality_name:
                    #     continue

                    #if classify_overlay_by_patch(extract_bottom_left_patch(barcode_region)) != classify_overlay_by_hue(barcode_diff["reg_mean_hue"]):
                    #    continue

                    try:
                        score = ssim(masked_region, masked_overlay, channel_axis=-1)
                        #score = ssim(gray_region, gray_overlay)
                    except ValueError:
                        continue

                    #print(f"{region_label}#{slot}: Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")

            #        if (region_label in ["Fore Weapon"] and slot == 0): # or (region_label in ["Hangar"]): # and (quality_name == 'rare' or quality_name == 'very rare' or quality_name == 'common')): # or region_label in ["Hangar"]:
                    # #if (region_label in ["Kit Modules"] and slot == 1): # and (quality_name == 'rare' or quality_name == 'very rare' or quality_name == 'common')): # or region_label in ["Hangar"]:
                    #     # let's binarize barcode_region and barcode_overlay
                    if must_inspect(inspection_list, region_label, slot):

                        barcode_region_binarized = cv2.adaptiveThreshold(cv2.cvtColor(barcode_region, cv2.COLOR_BGR2GRAY), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
                        barcode_overlay_binarized = cv2.adaptiveThreshold(cv2.cvtColor(barcode_overlay, cv2.COLOR_BGR2GRAY), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

                        print(f"{region_label}#{slot}: {quality_name}: Scale: After SSIM: scale=[{scale}] score=[{score:.4f}]")
                        print (f"Classify hue {quality_name} {region_label}#{slot}")
                        print(f"Region by patch: {classify_overlay_by_patch(barcode_region)}")
                        print(f"Overlay by patch: {classify_overlay_by_patch(barcode_overlay)}")
                        print(f"Region mean hue: {barcode_diff['reg_mean_hue']}")
                        print(f"Overlay mean hue: {barcode_diff['ovl_mean_hue']}")
                        print("Region color:", classify_overlay_by_hue(barcode_diff["reg_mean_hue"]))
                        print("Overlay color:", classify_overlay_by_hue(barcode_diff["ovl_mean_hue"]))
                        print("Significant hue difference?", is_significant_hue_diff(barcode_diff["hue_diff_deg"]))
                        print(f"barcode_overlay_stripes: {barcode_overlay_stripes}")
                        print(f"barcode_region_stripes: {barcode_region_stripes}")
                        show_image([region_crop, roi, masked_region, masked_overlay, barcode_region, barcode_overlay, barcode_region_binarized, barcode_overlay_binarized])
                        print()
                        # print(f"barcode_overlay_slanted_lines: {barcode_overlay_slanted_lines}")
                        # print(f"barcode_region_slanted_lines: {barcode_region_slanted_lines}")
                        # show_image([roi, gray_region, gray_overlay, barcode_region, barcode_overlay])

                    if score > 0.96 and score > best_score:
                        best_score = score
                        best_quality = quality_name
                        best_scale = scale
                        best_method = "ssim"

                        best_masked_region = masked_region
                        best_masked_overlay = masked_overlay

    # print(f"{region_label}#{slot}: Best matched overlay: {best_quality} with score {best_score:.4f} at scale {best_scale:.4f} using {best_method}")
    #show_image([region_crop, overlays[best_quality], best_masked_region, best_masked_overlay])
    return best_quality, best_scale, best_method


# def identify_overlay(region_crop, overlays, step=1, scales=np.linspace(0.6, 0.8, 20)):
#     if "common" in overlays:
#         base_overlay = overlays["common"]
#         oh, ow = base_overlay.shape[:2]
#         rh, rw = region_crop.shape[:2]
#         if rh > 43 * 1.1 or rw > 33 * 1.1:
#             scale_factor = min(43 / rh, 33 / rw)
#             region_crop = cv2.resize(
#                 region_crop,
#                 None,
#                 fx=scale_factor,
#                 fy=scale_factor,
#                 interpolation=cv2.INTER_AREA,
#             )
#             # logger.debug(f"Resized region_crop to {region_crop.shape[:2]} using scale factor {scale_factor:.2f}")

#     best_score = -np.inf
#     best_quality = None
#     best_scale = None
#     best_method = None
#     for quality_name, overlay in reversed(list(overlays.items())):
#         if quality_name == "common" and best_score > 0.6:
#             continue
#         # logger.debug(f"Trying quality overlay {quality_name}")

#         overlay_rgb = overlay[:, :, :3]
#         overlay_alpha = overlay[:, :, 3] / 255.0

#         for scale in scales:
#             # logger.debug(f"Trying scale {scale}")
#             resized_rgb = cv2.resize(
#                 overlay_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR
#             )
#             resized_alpha = cv2.resize(
#                 overlay_alpha,
#                 (resized_rgb.shape[1], resized_rgb.shape[0]),
#                 interpolation=cv2.INTER_LINEAR,
#             )

#             h, w = resized_rgb.shape[:2]
#             H, W = region_crop.shape[:2]

#             if h > H or w > W:
#                 continue

#             for y in range(0, H - h + 1, step):
#                 for x in range(0, W - w + 1, step):
#                     roi = region_crop[y : y + h, x : x + w]

#                     masked_region = (roi * resized_alpha[..., np.newaxis]).astype(
#                         np.uint8
#                     )
#                     masked_overlay = (
#                         resized_rgb * resized_alpha[..., np.newaxis]
#                     ).astype(np.uint8)

#                     try:
#                         score = ssim(masked_region, masked_overlay, channel_axis=-1)
#                     except ValueError:
#                         continue

#                     # print(f"Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")
#                     if score > best_score:
#                         best_score = score
#                         best_quality = quality_name
#                         best_scale = scale
#                         best_method = "ssim"

#     # print(f"Best matched overlay: {best_quality} with score {best_score:.4f} at scale {best_score if best_score is not None else 'N/A'} using {best_method}")
#     return best_quality, best_scale, best_method


def multi_scale_match(
    region_color, template_color, scales=np.linspace(0.6, 0.8, 20), threshold=0.7
):
    best_val = -np.inf
    best_match = None
    best_loc = None
    best_scale = 1.0

    # print(f"Region shape: {region_color.shape}, template shape: {template_color.shape}, scales: {scales}, threshold: {threshold}")
    region_color = apply_mask(cv2.GaussianBlur(region_color, (3, 3), 0))
    template_color = apply_mask(cv2.GaussianBlur(template_color, (3, 3), 0))

    for scale in scales:
        resized_template = cv2.resize(
            template_color, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR
        )
        th, tw = resized_template.shape[:2]
        if th > region_color.shape[0] or tw > region_color.shape[1]:
            continue

        for y in range(0, region_color.shape[0] - th + 1, 1):
            for x in range(0, region_color.shape[1] - tw + 1, 1):
                roi = region_color[y : y + th, x : x + tw]
                try:
                    s = ssim(roi, resized_template, channel_axis=-1)
                except ValueError:
                    continue
                if s > best_val:
                    best_val = s
                    best_loc = (x, y)
                    best_match = (tw, th)
                    best_scale = scale
    if best_val >= threshold:
        return best_loc, best_match, best_val, best_scale
    else:
        return None
