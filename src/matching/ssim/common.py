import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim
from collections import Counter
from ...utils.image import apply_mask

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

def show_img(
    imgs, window_name='Images', bg_color=(0,0,0)
):
    if not imgs:
        raise ValueError("No images to display")

    def ensure_uint8(img):
        if img.dtype == np.uint8:
            return img
        mn, mx = float(img.min()), float(img.max())
        if mx == mn:
            return np.zeros(img.shape, dtype=np.uint8)
        norm = (img - mn) * (255.0 / (mx - mn))
        return norm.astype(np.uint8)

    def to_bgr8(img):
        img8 = ensure_uint8(img)
        if img8.ndim == 2:
            return cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR)
        if img8.shape[2] == 4:
            return cv2.cvtColor(img8, cv2.COLOR_BGRA2BGR)
        return img8

    # preprocess all to 3-channel uint8
    processed = [to_bgr8(img) for img in imgs]

    # compute full canvas size
    heights = [im.shape[0] for im in processed]
    widths  = [im.shape[1] for im in processed]
    H, W = max(heights), sum(widths)

    # build the canvas
    canvas = np.full((H, W, 3), bg_color, dtype=np.uint8)
    x = 0
    for im in processed:
        h, w = im.shape[:2]
        canvas[0:h, x:x+w] = im
        x += w

    # create a resizable window that keeps aspect ratio
    flags = cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO
    cv2.namedWindow(window_name, flags)
    cv2.resizeWindow(window_name, W, H)
    cv2.setWindowProperty(
        window_name,
        cv2.WND_PROP_ASPECT_RATIO,
        cv2.WINDOW_KEEPRATIO
    )

    cv2.imshow(window_name, canvas)
    # block until user closes window (X) or presses 'x'
    while True:
        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
            break
        if cv2.waitKey(100) & 0xFF == ord('x'):
            break

    cv2.destroyWindow(window_name)

def identify_overlay(region_crop, overlays, region_label=None, slot=None, step=1, scales=np.linspace(0.6, 0.8, 20)):
    debug = True
    def luminance_bgr(col_arr):
        return 0.2126 * col_arr[...,2] + 0.7152 * col_arr[...,1] + 0.0722 * col_arr[...,0]
    
    # def find_off_segments(bright_vals):
    #     thr = bright_vals.mean()
    #     state, segments, start = 1, [], None
    #     for i, v in enumerate(bright_vals):
    #         if state == 1 and v < thr:
    #             state, start = 0, i
    #         elif state == 0 and v >= thr:
    #             segments.append((start, i-1))
    #             state, start = 1, None
    #     if state == 0 and start is not None:
    #         segments.append((start, len(bright_vals)-1))
    #     return [(s, e) for (s, e) in segments if e < len(bright_vals)-1]

    def find_off_segments(bright_vals, ignore_top_frac=0.1, ignore_top_rows=0):
        """
        Identify "off" segments (values below the mean threshold) in a 1-D brightness profile,
        but ignore any segments whose end falls within the top part of the profile.

        Parameters:
        - bright_vals: 1-D array of brightness values.
        - ignore_top_frac: float in [0,1], fraction of the profile height to ignore at the top.
        - ignore_top_rows: int, exact number of rows to ignore at the top (overrides ignore_top_frac if > 0).

        Returns:
        - List of (start, end) tuples for each valid off-segment.
        """
        thr = bright_vals.mean()
        state = 1
        segments = []
        start = None

        # Identify all off-segments
        for i, v in enumerate(bright_vals):
            if state == 1 and v < thr:
                state, start = 0, i
            elif state == 0 and v >= thr:
                segments.append((start, i - 1))
                state, start = 1, None
        # Close final segment if it runs to the end
        if state == 0 and start is not None:
            segments.append((start, len(bright_vals) - 1))

        # Determine how many rows to exclude at the top
        H = len(bright_vals)
        if ignore_top_rows > 0:
            margin = ignore_top_rows
        else:
            margin = int(H * ignore_top_frac)

        # Filter out segments ending within the excluded top region
        max_valid_end = H - 1 - margin
        valid_segments = [(s, e) for (s, e) in segments if e <= max_valid_end]

        return valid_segments

    def find_common_off_segments(bright2d, ignore_top_frac=0.1, ignore_top_rows=0, tolerance_rows=1):
        """
        Identify off-segments that appear across **all** columns of a 2-D brightness map,
        allowing for slight misalignment in row indices.

        Parameters:
        - bright2d: 2-D array of shape (H, W), brightness values for each column.
        - ignore_top_frac: fraction of rows at the top to ignore (per column).
        - ignore_top_rows: exact rows at the top to ignore (overrides fraction if > 0).
        - tolerance_rows: allowable vertical shift (in rows) when matching segments across columns.

        Returns:
        - List of (start, end) tuples of common segments (based on column 0's coordinates).
        """
        H, W = bright2d.shape
        # Find per-column segments
        per_col_segments = [
            find_off_segments(bright2d[:, j], ignore_top_frac, ignore_top_rows)
            for j in range(W)
        ]

        common = []
        # For each segment in the first column, check for overlap in all others
        for s0, e0 in per_col_segments[0]:
            match = True
            for segs in per_col_segments[1:]:
                # requires at least one segment in this column overlapping within tolerance
                if not any((e + tolerance_rows >= s0) and (s - tolerance_rows <= e0) for s, e in segs):
                    match = False
                    break
            if match:
                common.append((s0, e0))
        return common
        
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


    def extract_bottom_left_patch(arr, patch_size=3):
        """
        Extract a bottom-left square patch of size patch_size from a HxW(xC) array.
        """
        H, W = arr.shape[:2]
        # rows H-patch_size to H-1, columns 0 to patch_size-1
        return arr[H-patch_size:H, 0:patch_size]


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


    def hsv_profile(patch):
        """
        Compute circular mean and std of hue and mean/std of saturation & value for a BGR patch.
        Returns (mean_hue_deg, std_hue_deg, mean_sat, std_sat, mean_val, std_val).
        """
        hsv = cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_BGR2HSV)
        h = hsv[...,0].astype(np.float32)  # 0-179 in OpenCV
        s = hsv[...,1].astype(np.float32) / 255.0
        v = hsv[...,2].astype(np.float32) / 255.0
        # convert to degrees
        hue_deg = h / 179.0 * 360.0
        # circular mean
        rad = np.deg2rad(hue_deg)
        sin_mean = np.mean(np.sin(rad))
        cos_mean = np.mean(np.cos(rad))
        mean_angle = np.arctan2(sin_mean, cos_mean)
        mean_hue = (np.rad2deg(mean_angle) + 360) % 360
        R = np.sqrt(sin_mean**2 + cos_mean**2)
        std_hue = np.sqrt(-2 * np.log(max(R, 1e-8))) * (180/np.pi)
        mean_sat = np.mean(s)
        std_sat = np.std(s)
        mean_val = np.mean(v)
        std_val = np.std(v)
        return mean_hue, std_hue, mean_sat, std_sat, mean_val, std_val

    def compare_patches(region_arr, overlay_arr, patch_size=3):
        """
        Compare bottom-left patches of two images in BGR, luminance, and HSV profiles.

        Returns a dict with:
        - reg_mean_hue, ovl_mean_hue: mean hues in degrees,
        - hue_diff_deg: minimal angular difference in mean hue,
        - sat_diff: abs difference in mean saturation,
        - val_diff: abs difference in mean value,
        - diff_mean_bgr: abs differences of channel means,
        - diff_std_bgr: abs differences of channel stds,
        - diff_mean_lum: abs difference of mean luminance,
        - diff_std_lum: abs difference of luminance std.
        """
        region_rgb = region_arr[..., :3]
        overlay_rgb = overlay_arr[..., :3]
        reg_patch = extract_bottom_left_patch(region_rgb, patch_size)
        ovl_patch = extract_bottom_left_patch(overlay_rgb, patch_size)

        reg_mean, reg_std, reg_lum_mean, reg_lum_std = patch_profile(reg_patch)
        ovl_mean, ovl_std, ovl_lum_mean, ovl_lum_std = patch_profile(ovl_patch)

        reg_hue, _, reg_sat, _, reg_val, _ = hsv_profile(reg_patch)
        ovl_hue, _, ovl_sat, _, ovl_val, _ = hsv_profile(ovl_patch)
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


    HUE_DIFF_THRESHOLD = 30  # degrees: typical threshold to consider hues distinct

    def is_significant_hue_diff(hue_diff, threshold=HUE_DIFF_THRESHOLD):
        """Return True if hue difference exceeds threshold."""
        return hue_diff >= threshold


    def classify_hue(mean_hue):
        """
        Bucket a hue angle into a general color category.
        """
        if 30 <= mean_hue < 90:
            return "yellow/gold"
        elif 90 <= mean_hue < 150:
            return "green"
        elif 150 <= mean_hue < 210:
            return "blue"
        elif 210 <= mean_hue < 270:
            return "purple"
        elif 270 <= mean_hue < 330:
            return "pink"
        else:
            return "red"

    #print(f"Identifying overlay for {region_label}#{slot}")
   
    best_score = -np.inf
    best_quality = "common"
    best_scale = 1.0
    best_method = "fallback"

    show_img_list = []
    best_masked_region = None
    best_masked_overlay = None 

    barcode_width = 3
    for quality_name, overlay in reversed(list(overlays.items())):
        if quality_name == "common" and best_score > 0.96:
            continue
        # logger.debug(f"Trying quality overlay {quality_name}")

        #overlay = cv2.resize(overlay, None, fx=2, fy=2, interpolation=cv2.INTER_AREA)

        overlay_rgb = overlay[:, :, :3]
        overlay_alpha = overlay[:, :, 3] / 255.0


        # Barcode Overlay setup
        barcode_overlay = roi_crop(overlay_rgb.copy(), barcode_width)
        barcode_overlay_bright_ref = luminance_bgr(barcode_overlay[::-1, :barcode_width])
        barcode_overlay_common_segments = find_common_off_segments(barcode_overlay_bright_ref,
                                           ignore_top_frac=0.1,
                                           ignore_top_rows=0,
                                           tolerance_rows=1)
        barcode_overlay_stripes_expected = len(barcode_overlay_common_segments)

   
        # Barcode Region setup
        barcode_region = roi_crop(region_crop.copy(), barcode_width)
        barcode_region_bright_ref = luminance_bgr(barcode_region[::-1, :barcode_width])

        barcode_region_common_segments = find_common_off_segments(barcode_region_bright_ref,
                                           ignore_top_frac=0.05,
                                           ignore_top_rows=0,
                                           tolerance_rows=1)
        barcode_region_stripes_expected = len(barcode_region_common_segments)

        #print(f"{region_label}#{slot}: Begin matching quality {quality_name}")  


        diff = compare_patches(barcode_region, barcode_overlay)
        #print(f"{region_label}#{slot}: Diff for overlay {quality_name}: {diff}")
        #if (region_label in ["Hangar"]) or ((region_label in ["Devices"] and slot == 5) and (quality_name == 'rare' or quality_name == 'very rare' or quality_name == 'common')): # or quality_name == 'very rare'): # or region_label in ["Hangar"]:
            #print(f"{region_label}#{slot}: Barcodes for overlay {quality_name}: {barcode_overlay_stripes_expected}, region {barcode_region_stripes_expected}")
        #    print(f"diff_mean_bgr: {barcode_diff['diff_mean_bgr']}, diff_std_bgr: {barcode_diff['diff_std_bgr']}, diff_mean_lum: {barcode_diff['diff_mean_lum']}, diff_std_lum: {barcode_diff['diff_std_lum']}")
            # print(f"barcode_overlay_stripes_expected: {barcode_overlay_stripes_expected}")
            # print(f"barcode_region_stripes_expected: {barcode_region_stripes_expected}")
         #   show_img([region_crop, overlay_rgb, barcode_region, barcode_overlay])


        orig_mask = overlay_mask(quality_name, overlay_alpha.shape)

        for scale in scales:
            # logger.debug(f"Trying scale {scale}")
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

            if h > H or w > W:
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
                    roi = region_crop[y : y + h, x : x + w]

                    masked_region = (roi * final_alpha[..., np.newaxis]).astype(np.uint8)
                    masked_overlay = (resized_rgb * final_alpha[..., np.newaxis]).astype(np.uint8)

                    barcode_region = roi_crop(masked_region.copy(), barcode_width)
                    barcode_region = cv2.resize(barcode_region, (barcode_overlay.shape[1], barcode_overlay.shape[0]), interpolation=cv2.INTER_LINEAR)   
                    
                    # Convert to grayscale before SSIM calculation      
                    gray_region  = cv2.cvtColor(masked_region,  cv2.COLOR_BGR2GRAY)
                    gray_overlay = cv2.cvtColor(masked_overlay, cv2.COLOR_BGR2GRAY)

                    # Barcode Region setup
                    barcode_region_bright_ref = luminance_bgr(barcode_region[::-1, :barcode_width])

                    # Check colour and intensity patch
                    barcode_diff = compare_patches(barcode_region, barcode_overlay, patch_size=3)
                    #print(f"{region_label}#{slot}: diff_mean_bgr: {barcode_diff['diff_mean_bgr']}, diff_std_bgr: {barcode_diff['diff_std_bgr']}, diff_mean_lum: {barcode_diff['diff_mean_lum']}, diff_std_lum: {barcode_diff['diff_std_lum']}")
                    #print(f"{region_label}#{slot}: {barcode_diff} ")
                    #if (barcode_diff['diff_mean_bgr'] > 0.1) or (barcode_diff['diff_std_bgr'] > 0.1) or (barcode_diff['diff_mean_lum'] > 0.1) or (barcode_diff['diff_std_lum'] > 0.1):
                        #continue
                    #    print(f"{region_label}#{slot}: Skipping due to mismatched barcodes: {barcode_diff['diff_mean_bgr']}, {barcode_diff['diff_std_bgr']}, {barcode_diff['diff_mean_lum']}, {barcode_diff['diff_std_lum']}")

                    barcode_region_common_segments = find_common_off_segments(barcode_region_bright_ref,
                                           ignore_top_frac=0.05,
                                           ignore_top_rows=0,
                                           tolerance_rows=1)
                    barcode_region_stripes_found = len(barcode_region_common_segments)

                    if barcode_overlay_stripes_expected != barcode_region_stripes_found:
                        #print(f"{region_label}#{slot}: Skipping due to mismatched barcodes: {barcode_overlay_stripes_expected} vs {barcode_region_stripes_found}")
                        continue

                    try:
                        score = ssim(masked_region, masked_overlay, channel_axis=-1)
                        # score = ssim(gray_region, gray_overlay, window_size=3)
                    except ValueError:
                        continue

                    #print(f"{region_label}#{slot}: Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")

                    # if (region_label in ["Hangar"]) or ((region_label in ["Devices"] and slot == 5) and (quality_name == 'rare' or quality_name == 'very rare' or quality_name == 'common')): # or region_label in ["Hangar"]:
                        # print (f"Classify hue {quality_name} {region_label}#{slot}")
                        # print("Region color:", classify_hue(barcode_diff["reg_mean_hue"]))
                        # print("Overlay color:", classify_hue(barcode_diff["ovl_mean_hue"]))
                        # print("Significant hue difference?", is_significant_hue_diff(barcode_diff["hue_diff_deg"]))
                        #print(f"{region_label}#{slot}: [show_img] Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")
                        #print(f"barcode_overlay_stripes_expected: {barcode_overlay_stripes_expected}")
                        #print(f"barcode_region_stripes_found: {barcode_region_stripes_found}")
                        # show_img([roi, masked_region, masked_overlay, barcode_region, barcode_overlay])


                    if score > 0.96 and score > best_score:
                        best_score = score
                        best_quality = quality_name
                        best_scale = scale
                        best_method = "ssim"

                        best_masked_region = gray_region #masked_region
                        best_masked_overlay = gray_overlay #masked_overlay

    # print(f"{region_label}#{slot}: Best matched overlay: {best_quality} with score {best_score:.4f} at scale {best_scale:.4f} using {best_method}")
    #show_img([region_crop, overlays[best_quality], best_masked_region, best_masked_overlay])
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
