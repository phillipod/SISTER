import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim
from collections import Counter
from ..utils.image import apply_overlay, apply_mask

def dynamic_hamming_cutoff(scores, best_score, max_next_ranks=2, max_allowed_gap=4):
    from collections import Counter
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

def identify_overlay(region_crop, overlays, step=1, scales=np.linspace(0.6, 1.0, 40)):
    if "common" in overlays:
        base_overlay = overlays["common"]
        oh, ow = base_overlay.shape[:2]
        rh, rw = region_crop.shape[:2]
        if rh > 43 * 1.1 or rw > 33 * 1.1:
            scale_factor = min(43 / rh, 33 / rw)
            region_crop = cv2.resize(region_crop, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
            #logger.debug(f"Resized region_crop to {region_crop.shape[:2]} using scale factor {scale_factor:.2f}")


    best_score = -np.inf
    best_quality = None
    best_scale = None
    best_method = None
    for quality_name, overlay in reversed(list(overlays.items())):
        if quality_name == "common" and best_score > 0.6: 
            continue
        #logger.debug(f"Trying quality overlay {quality_name}")

        overlay_rgb = overlay[:, :, :3]
        overlay_alpha = overlay[:, :, 3] / 255.0

        for scale in scales:
            #logger.debug(f"Trying scale {scale}")
            resized_rgb = cv2.resize(overlay_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            resized_alpha = cv2.resize(overlay_alpha, (resized_rgb.shape[1], resized_rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

            h, w = resized_rgb.shape[:2]
            H, W = region_crop.shape[:2]

            if h > H or w > W:
                continue

            for y in range(0, H - h + 1, step):
                for x in range(0, W - w + 1, step):
                    roi = region_crop[y:y+h, x:x+w]

                    masked_region = (roi * resized_alpha[..., np.newaxis]).astype(np.uint8)
                    masked_overlay = (resized_rgb * resized_alpha[..., np.newaxis]).astype(np.uint8)

                    try:
                        score = ssim(masked_region, masked_overlay, channel_axis=-1)
                    except ValueError:
                        continue

                    #print(f"Score for overlay {quality_name}: {score:.4f} at scale {scale:.2f}")
                    if score > best_score:
                        best_score = score
                        best_quality = quality_name
                        best_scale = scale
                        best_method = 'ssim'

    #print(f"Best matched overlay: {best_quality} with score {best_score:.4f} at scale {best_score if best_score is not None else 'N/A'} using {best_method}")
    return best_quality, best_scale, best_method

def multi_scale_match(region_color, template_color, scales=np.linspace(0.6, 0.8, 20), threshold=0.7):
    best_val = -np.inf
    best_match = None
    best_loc = None
    best_scale = 1.0

    region_color = apply_mask(cv2.GaussianBlur(region_color, (3, 3), 0))
    template_color = apply_mask(cv2.GaussianBlur(template_color, (3, 3), 0))

    for scale in scales:
        resized_template = cv2.resize(template_color, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        th, tw = resized_template.shape[:2]
        if th > region_color.shape[0] or tw > region_color.shape[1]:
            continue

        for y in range(0, region_color.shape[0] - th + 1, 1):
            for x in range(0, region_color.shape[1] - tw + 1, 1):
                roi = region_color[y:y+th, x:x+tw]
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
