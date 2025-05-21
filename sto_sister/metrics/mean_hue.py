import cv2
import numpy as np

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
    h = hsv[..., 0].astype(np.float32) / 179.0 * 360.0
    s = hsv[..., 1].astype(np.float32) / 255.0
    v = hsv[..., 2].astype(np.float32) / 255.0

    # Mask out non-colorful pixels
    mask = (s >= min_sat) & (v >= min_val)
    frac_colorful = mask.sum() / mask.size
    if frac_colorful < frac_thresh:
        return (
            f"common",
            f"({frac_colorful:.2f}) (s: {s.mean():.2f}, v: {v.mean():.2f})",
        )

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
        return "epic", h_deg  # ({h_deg:.1f}°)"
    elif 100 <= h_deg < 115:
        return "uncommon", h_deg  # ({h_deg:.1f}°)"
    elif 205 <= h_deg < 220:
        return "rare", h_deg  # ({h_deg:.1f}°)"
    elif 240 <= h_deg < 263:
        return "very rare", h_deg  # ({h_deg:.1f}°)"
    elif 263 <= h_deg < 290:
        return "ultra rare", h_deg  # ({h_deg:.1f}°)"
    else:
        return "unknown", h_deg