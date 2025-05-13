import os
import cv2
import numpy as np
import logging
from skimage.measure import shannon_entropy

from typing import List, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class IconSlotDetector:
    """
    Pipeline aware icon slot detector. Detects icon slot candidates globally, then tags them into known regions based on region_data.

    Attributes:
        debug (bool): If True, enables debug output and writes annotated images.
    """

    def __init__(self, hash_index=None, debug=False):
        """
        Initialize the IconSlotDetector.

        Args:
            debug (bool): If True, enables debug output and writes annotated images.
        """

        self.debug = debug
        self.hash_index = hash_index

    # def detect_inventory(self, screenshot_color, debug_output_path=None):
    def detect_inventory(
        self, image: np.ndarray, region_bbox: Tuple[int, int, int, int]
    ) -> List[Tuple[int, int, int, int]]:
        """
        Detect icon slot candidates globally.

        Args:
            screenshot_color (np.array): Full BGR screenshot.
            debug_output_path (str): If set, saves debug images.

        Returns:
            list: List of (x, y, w, h) tuples.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 63, 255, cv2.THRESH_BINARY)

        candidates = self._find_slot_candidates(binary, image)

        region_candidates = {"Inventory": []}

        for x, y, w, h in candidates:
            region_candidates["Inventory"].append((x, y, w, h))

        # Convert all box values to native Python int to avoid JSON serialization issues
        region_candidates = {
            label: [tuple(int(v) for v in box) for box in boxes]
            for label, boxes in region_candidates.items()
        }

        for label in region_candidates:
            region_candidates[label] = self._sort_boxes_grid_order(
                region_candidates[label]
            )

        return region_candidates

    def detect_slots(
        self, image: np.ndarray, region_bbox: Dict[str, Any]
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        Detect icon slot candidates globally and assign them to labeled regions, including ROI data.

        Args:
            image (np.ndarray): Full BGR screenshot.
            region_bbox (Dict[str, Any]): Mapping of region labels to region metadata.

        Returns:
            Dict[str, Dict[str, List[Dict[str, Any]]]]: Mapping of region label to dict with key "Slots",
            containing a list of dicts with keys "Slot" (index within region), "Box" (x, y, w, h), and "ROI" (cropped image).
        """
        # Convert to grayscale and threshold
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 63, 255, cv2.THRESH_BINARY)

        # Find slot candidates and their corresponding ROIs
        candidates, candidate_rois = self._find_slot_candidates(binary, image)

        # Initialize region slots
        region_candidates: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
            label: [] for label in region_bbox
        }

        # Assign each candidate to its region
        for idx, (x, y, w, h) in enumerate(candidates):
            cx, cy = x + w // 2, y + h // 2
            for label, entry in region_bbox.items():
                x1, y1 = entry["Region"]["top_left"]
                x2, y2 = entry["Region"]["bottom_right"]
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    slot_info = {
                        # Temporarily store global index; will renumber per region later
                        "GlobalIdx": idx,
                        "Box": (int(x), int(y), int(w), int(h)),
                        "ROI": candidate_rois[(x, y, w, h)],
                        "Hash": self.hash_index.get_hash(candidate_rois[(x, y, w, h)]),
                    }
                    region_candidates[label].append(slot_info)
                    break

        # print(f"region_candidates: {region_candidates}")

        # Sort slots and renumber per region
        for label, slots in region_candidates.items():
            if not slots:
                continue
            boxes = [slot["Box"] for slot in slots]
            sorted_boxes = self._sort_boxes_grid_order(boxes)

            # Map original slots by box for quick lookup
            slot_map = {slot["Box"]: slot for slot in slots}
            # print (f"slot_map: {slot_map}")
            sorted_slots: List[Dict[str, Any]] = []
            for local_idx, box in enumerate(sorted_boxes):
                info = slot_map.get(sorted_boxes[box], None)

                if info is not None:
                    sorted_slots.append(
                        {
                            "Slot": local_idx,
                            "Box": info["Box"],
                            "ROI": info["ROI"],
                            "Hash": info["Hash"],
                        }
                    )
            region_candidates[label] = sorted_slots

        # print(f"region_candidates: {region_candidates}")

        return region_candidates

    def _find_slot_candidates(
        self,
        binary,
        color_image,
        debug_dir=None,
        min_area=200,
        aspect_ratio=49 / 64,
        aspect_tolerance=0.2,
        min_stddev=30,
        min_entropy=6,
    ):
        """
        Identify and filter potential icon slot candidates from a binary image.

        This function processes a binary image to identify contours that match specified criteria
        for potential icon slots. It applies filters based on area, aspect ratio, standard deviation,
        and entropy to refine the candidate list. Optionally, it saves intermediate debug images
        to a specified directory. Non-max suppression is used to remove overlapping candidates.

        Args:
            binary (np.array): Input binary image for slot detection.
            color_image (np.array): Original color image used for additional analysis.
            debug_dir (str, optional): Directory path to save debug images.
            min_area (int, optional): Minimum area threshold for a valid contour.
            aspect_ratio (float, optional): Expected aspect ratio for valid slots.
            aspect_tolerance (float, optional): Tolerance for the aspect ratio check.
            min_stddev (float, optional): Minimum standard deviation for intensity check.
            min_entropy (float, optional): Minimum entropy threshold for texture check.

        Returns:
            list: List of bounding boxes (x, y, w, h) for identified slot candidates.
        """

        os.makedirs(os.path.dirname(debug_dir), exist_ok=True) if debug_dir else None

        denoised = cv2.fastNlMeansDenoising(binary, h=30)
        if debug_dir:
            cv2.imwrite(f"{debug_dir}_denoised.png", denoised)

        contours, _ = cv2.findContours(
            denoised, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        candidates = []
        candidate_rois = {}
        debug_img = cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)

        for i, cnt in enumerate(contours):
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            aspect = w / float(h)  # Calculate aspect ratio
            if area < min_area or not (abs(aspect - aspect_ratio) <= aspect_tolerance):
                continue

            roi = color_image[y : y + h, x : x + w]
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            stddev = np.std(roi_gray)
            entropy = shannon_entropy(roi_gray)

            if stddev < min_stddev or entropy < min_entropy:
                continue

            candidates.append((x, y, w, h))
            candidate_rois[(x, y, w, h)] = roi.copy()

            if debug_dir:
                cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 1)

        # Apply Non-Max Suppression
        candidates = self._non_max_suppression(candidates, overlapThresh=0.3)

        if debug_dir:
            cv2.imwrite(f"{debug_dir}_slot_candidates.png", debug_img)

        return candidates, candidate_rois

    def _non_max_suppression(self, boxes, overlapThresh=0.3):
        """
        Apply Non-Maximum Suppression to a list of bounding boxes.

        Args:
            boxes (list): List of bounding boxes as (x, y, w, h) tuples.
            overlapThresh (float): Maximum overlap threshold.

        Returns:
            list: List of non-overlapping bounding boxes.
        """
        if len(boxes) == 0:
            return []

        boxes = np.array(boxes).astype("float")
        pick = []
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 0] + boxes[:, 2]
        y2 = boxes[:, 1] + boxes[:, 3]
        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        idxs = np.argsort(y2)

        while len(idxs) > 0:
            last = idxs[-1]
            pick.append(last)
            xx1 = np.maximum(x1[last], x1[idxs[:-1]])
            yy1 = np.maximum(y1[last], y1[idxs[:-1]])
            xx2 = np.minimum(x2[last], x2[idxs[:-1]])
            yy2 = np.minimum(y2[last], y2[idxs[:-1]])
            w = np.maximum(0, xx2 - xx1 + 1)
            h = np.maximum(0, yy2 - yy1 + 1)
            overlap = (w * h) / area[idxs[:-1]]
            idxs = np.delete(
                idxs,
                np.concatenate(([len(idxs) - 1], np.where(overlap > overlapThresh)[0])),
            )

        return boxes[pick].astype("int")

    def _sort_boxes_grid_order(self, boxes, row_thresh=10):
        """
        Sort (x, y, w, h) boxes in visual grid order: top-to-bottom, then left-to-right.

        Args:
            boxes (list): List of (x, y, w, h) tuples.
            row_thresh (int): Max Y difference to consider boxes part of the same row.

        Returns:
            list: Sorted list of boxes in visual grid order.
        """
        if not boxes:
            return []

        # Sort all boxes by Y
        boxes = sorted(boxes, key=lambda b: b[1])
        rows = []
        current_row = [boxes[0]]
        current_y = boxes[0][1]

        for box in boxes[1:]:
            y = box[1]
            if abs(y - current_y) <= row_thresh:
                current_row.append(box)
            else:
                rows.append(sorted(current_row, key=lambda b: b[0]))  # sort X in row
                current_row = [box]
                current_y = y

        if current_row:
            rows.append(sorted(current_row, key=lambda b: b[0]))

        return {i: box for row in rows for i, box in enumerate(row)}
