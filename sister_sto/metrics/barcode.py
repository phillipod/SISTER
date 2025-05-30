import cv2
import numpy as np

def find_off_strips(strip_bgr, ignore_top_frac=0.3, min_off_cols=3):
    """
    strip_bgr: Hx3x3 BGR image.
    Returns a list of (start_row, end_row) for each run where
    at least min_off_cols columns are black (0) in that row,
    ignoring any runs that start or end above ignore_top_frac*H.
    """
    # 1) BGR -> gray -> 0/1 map
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY)
    # _, bmap = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bmap = cv2.adaptiveThreshold(
        gray,
        maxValue=1,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=11,
        C=2,
    )

    # 2) count how many of the 3 cols are off in each row
    off_rows = (bmap == 0).sum(axis=1) >= min_off_cols

    # 3) one-pass run finder
    H = off_rows.shape[0]
    margin = int(H * ignore_top_frac)
    segments = []
    in_run = False
    for i, is_off in enumerate(off_rows):
        if not in_run and is_off:
            start = i
            in_run = True
        elif in_run and not is_off:
            # close run at i-1
            if start >= margin and (i - 1) >= margin:
                segments.append((start, i - 1))
            in_run = False
    # if last run goes to bottom
    if in_run and start >= margin:
        segments.append((start, H - 1))

    return segments


def compare_barcodes(
    strip1_bgr,
    strip2_bgr,
    ignore_top_frac=0.3,
    min_off_cols=3,
    tolerance_rows=1,
    pos_tol=2,
    len_tol=2,
):
    """
    Compare two BGR barcode strips by their black/off segments.
    Returns True if they have the same number of runs and each
    corresponding run aligns within tolerance_rows.
    """
    segs1 = find_off_strips(
        strip1_bgr, ignore_top_frac=ignore_top_frac, min_off_cols=min_off_cols
    )
    segs2 = find_off_strips(
        strip2_bgr, ignore_top_frac=ignore_top_frac, min_off_cols=min_off_cols
    )

    # 1) same count?
    if len(segs1) != len(segs2):
        return False, segs1, segs2

    # 2) each run lines up within tolerance
    for (s1, e1), (s2, e2) in zip(segs1, segs2):
        # check that start‐rows line up
        if abs(s1 - s2) > pos_tol:
            return False, segs1, segs2
        # check that end‐rows line up
        if abs(e1 - e2) > pos_tol:
            return False, segs1, segs2
        # check that stripe‐lengths are similar
        if abs((e1 - s1) - (e2 - s2)) > len_tol:
            return False, segs1, segs2

    return True, segs1, segs2
