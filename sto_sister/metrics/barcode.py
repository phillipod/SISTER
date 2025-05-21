import cv2
import numpy as np
# def find_off_segments(bin_vals, ignore_top_frac=0.1, ignore_top_rows=0):
#     """
#     Identify runs of 0s in a 1-D binary array, but ignore any segments
#     that start in the top ignored region (first ignore_top_frac of rows).
#     """
#     H = bin_vals.shape[0]

#     # find all zero runs
#     segments = []
#     in_zero = False
#     start = None
#     for i, v in enumerate(bin_vals):
#         if not in_zero and v == 0:
#             in_zero = True
#             start = i
#         elif in_zero and v == 1:
#             segments.append((start, i - 1))
#             in_zero = False
#     if in_zero:
#         segments.append((start, H - 1))

#     # compute top margin (rows to ignore at start of array)
#     margin = ignore_top_rows if ignore_top_rows > 0 else int(H * ignore_top_frac)
#     min_valid_start = margin

#     # filter out those that begin in the ignored zone
#     #return [(s, e) for (s, e) in segments if s >= min_valid_start]
#     #return [(s,e) for (s,e) in segments if e >= margin]
#     return [(s, e) for (s, e) in segments
#         if s >= margin and e >= margin]

# def find_common_off_segments(bin2d,
#                             ignore_top_frac=0.1,
#                             ignore_top_rows=0,
#                             tolerance_rows=1):
#     """
#     Find zero-runs (within tolerance) in EVERY column of a 2-D binary map—
#     but only in the leftmost 3 columns where the stripes live.
#     """
#     # — binarize if needed —
#     if bin2d.ndim == 3:
#         gray = cv2.cvtColor(bin2d, cv2.COLOR_BGR2GRAY)
#         # _, bmap = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
#         bin2d = cv2.adaptiveThreshold(
#             gray,
#             maxValue=1,
#             adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#             thresholdType=cv2.THRESH_BINARY,
#             blockSize=11,
#             C=2
#         )

#     elif bin2d.ndim != 2:
#         raise ValueError(f"Expected 2D or 3D input, got shape {bin2d.shape!r}")

#     # restrict to the leftmost 3 columns
#     H, W = bin2d.shape
#     stripe_roi = bin2d[:, :3]

#     # get zero-runs per column
#     col_segs = [
#         find_off_segments(stripe_roi[:, j], ignore_top_frac, ignore_top_rows)
#         for j in range(3)
#     ]

#     # find common overlaps
#     common = []
#     for s0, e0 in col_segs[0]:
#         if all(
#             any((e + tolerance_rows >= s0) and (s - tolerance_rows <= e0)
#                 for s, e in segs_j)
#             for segs_j in col_segs[1:]
#         ):
#             common.append((s0, e0))
#     return common

def find_off_strips(strip_bgr, ignore_top_frac=0.3, min_off_cols=3):
    """
    strip_bgr: H×3×3 BGR image.
    Returns a list of (start_row, end_row) for each run where
    at least min_off_cols columns are black (0) in that row,
    ignoring any runs that start or end above ignore_top_frac*H.
    """
    # 1) BGR → gray → 0/1 map
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
        # if abs(s1 - s2) > tolerance_rows or abs(e1 - e2) > tolerance_rows or abs((e1 - s1) - (e2 - s2)) > len_tol:
        #    return False, segs1, segs2

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

# def compare_barcodes(img_a,
#                         img_b,
#                         box_width=3,
#                         ignore_top_frac=0.3,
#                         ignore_top_rows=0,
#                         tolerance_rows=1,
#                         pos_tol=2,
#                         len_tol=2):
#     """
#     Compare the barcode stripes of img_a and img_b for:
#     1) same number of stripes,
#     2) each stripe starting and ending in about the same row,
#     3) each stripe having about the same length.

#     Returns:
#     match:        True if all stripes match within tolerances.
#     stripes_a:    list of (start,end) for img_a
#     stripes_b:    list of (start,end) for img_b
#     """
#     # Crop to the leftmost barcode region
#     roi_a = img_a[:, :box_width]
#     roi_b = img_b[:, :box_width]

#     # Reuse your existing find_common_off_segments
#     segs_a = find_common_off_segments(roi_a,
#                                     ignore_top_frac=ignore_top_frac,
#                                     ignore_top_rows=ignore_top_rows,
#                                     tolerance_rows=tolerance_rows)
#     segs_b = find_common_off_segments(roi_b,
#                                     ignore_top_frac=ignore_top_frac,
#                                     ignore_top_rows=ignore_top_rows,
#                                     tolerance_rows=tolerance_rows)

#     if len(segs_a) != len(segs_b):
#         return False, segs_a, segs_b

#     for (s1, e1), (s2, e2) in zip(segs_a, segs_b):
#         # check that start‐rows line up
#         if abs(s1 - s2) > pos_tol:
#             return False, segs_a, segs_b
#         # check that end‐rows line up
#         if abs(e1 - e2) > pos_tol:
#             return False, segs_a, segs_b
#         # check that stripe‐lengths are similar
#         if abs((e1 - s1) - (e2 - s2)) > len_tol:
#             return False, segs_a, segs_b

#     return True, segs_a, segs_b