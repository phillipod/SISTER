import warnings

# suppress only the “pin_memory” UserWarning from torch.utils.data
warnings.filterwarnings(
    "ignore",
    message=".*pin_memory.*no accelerator is found.*",
    category=UserWarning,
    module="torch.utils.data.dataloader"
)

import cv2
import easyocr
import os
import numpy as np
from difflib import SequenceMatcher
from typing import Dict, Tuple, Optional, List

import logging

logger = logging.getLogger(__name__)


class LabelLocator:
    """
    Pipeline-aware label locator: detects allowed labels in a pre-loaded image array.
    Returns a simple mapping from label→bbox tuples.
    """

    def __init__(self, gpu: bool = False, scale_x: float = 1.25, debug: bool = False):
        """
        Initialize the Locator.

        Args:
            gpu (bool): Whether to use GPU for OCR.
            debug (bool): Whether to enable debug output.
        """
        self.debug = debug
        self.reader = easyocr.Reader(["en"], gpu=gpu)
        self.scale_x = scale_x
        self.allowed_labels = self._build_allowed_labels()

    def _build_allowed_labels(self) -> list:
        """
        Build the list of allowed labels for matching.

        Returns:
            list: List of dictionaries with label configurations.
        """
        return [
            {
                "label": ("Shield", "Deflector", "Impulse", "Warp", "Hangar"),
                "split_words": True,
            },
            {"label": ("Shield", "Deflector", "Impulse", "Warp"), "split_words": True},
            {"label": ("Body", ("EV", "Suit")), "split_words": True},
            {"label": "Kit Modules"},
            {"label": "Kit"},
            {"label": "Kit Frame"},
            {"label": "Body"},
            {"label": "EV Suit"},
            {"label": "Weapon"},
            {"label": "Shield"},
            {"label": "Devices"},
            {"label": "Fore Weapon"},
            {"label": "Aft Weapon"},
            {"label": "Experimental Weapon"},
            {"label": "Secondary Deflector"},
            {"label": "Deflector"},
            {"label": "Impulse"},
            {"label": "Warp"},
            {"label": "Singularity"},
            {"label": "Hangar"},
            {"label": "Universal Console"},
            {"label": "Engineering Console"},
            {"label": "Tactical Console"},
            {"label": "Science Console"},
            {"label": "Experimental Traits"},
            {"label": "Starship Traits"},
            {"label": "Personal Ground Traits"},
            {"label": "Active Ground Reputation"},
            {"label": "Ground Reputation"},
            {"label": "Personal Space Traits"},
            {"label": "Active Space Reputation"},
            {"label": "Space Reputation"},
            {"label": "Other"},
            # SETS special cases
            {"label": "Warp Core", "real_label": "Warp"},
            {"label": "Engines", "real_label": "Impulse"},
            {"label": "Sec-Def", "real_label": "Secondary Deflector"},
            {"label": "Sec Def", "real_label": "Secondary Deflector"},
            {
                "label": "Personal Traits",
                "real_label": "SETS - Personal Traits",
            },  # Distinguish so we have a way to filter SETS builds
            {
                "label": "Reputation Traits",
                "real_label": "SETS - Reputation Traits",
            },  # Distinguish so we have a way to filter SETS builds
            {
                "label": "Active Reputation Traits",
                "real_label": "SETS - Active Reputation Traits",
            },  # Distinguish so we have a way to filter SETS builds
        ]

    @staticmethod
    def is_single_char_off(str1: str, str2: str) -> bool:
        """
        Determine if two strings differ by at most one character.

        Args:
            str1 (str): First string.
            str2 (str): Second string.

        Returns:
            bool: True if strings are close enough, False otherwise.
        """
        if abs(len(str1) - len(str2)) > 1:
            return False
        return SequenceMatcher(None, str1, str2).ratio() >= 0.86

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalize text by lowercasing and collapsing whitespace.

        Args:
            text (str): Input text.

        Returns:
            str: Normalized text.
        """
        return " ".join(text.lower().split())

    def reocr_split_words(
        self,
        image: np.ndarray,
        rect: Tuple[int, int, int, int],
        expected_parts: Optional[List[str]] = None,
    ) -> Dict[Tuple[int, int, int, int], str]:
        """
        Perform secondary OCR on a cropped region to split words.

        Args:
            image (np.array): Upscaled image.
            rect (tuple): (x1, y1, x2, y2) rectangle coordinates.
            expected_parts (list, optional): Expected split words.

        Returns:
            dict: Mapping of new bounding boxes to split text.
        """
        x1, y1, x2, y2 = rect
        x1_scaled = int(x1 * self.scale_x)
        x2_scaled = int(x2 * self.scale_x)
        roi = image[y1:y2, x1_scaled:x2_scaled]

        logger.debug(
            f"Re-OCR on ROI: ({x1_scaled}, {y1}, {x2_scaled}, {y2}) from original ({x1}, {y1}, {x2}, {y2})"
        )

        if self.debug:
            os.makedirs("output/debug_reocr", exist_ok=True)
            debug_roi_path = f"output/debug_reocr/roi_{x1}_{y1}_{x2}_{y2}.png"
            cv2.imwrite(debug_roi_path, roi)
            logger.debug(f"Saved ROI debug image to {debug_roi_path}")

        results = self.reader.readtext(roi, paragraph=False, width_ths=0.0)
        split_results = {}

        for bbox, text, _ in results:
            (sx, sy) = bbox[0]
            (ex, ey) = bbox[2]
            sx = int(sx / self.scale_x) + x1
            ex = int(ex / self.scale_x) + x1
            sy += y1
            ey += y1
            split_results[(sx, sy, ex, ey)] = text.strip()
            logger.debug(
                f"Re-OCR Split Word: '{text.strip()}' at ({sx}, {sy}, {ex}, {ey})"
            )

        if expected_parts and len(split_results) > len(expected_parts):
            logger.debug("Too many parts, merging extras into last expected part")

            merged = []
            for i in range(len(expected_parts)):
                if i < len(expected_parts) - 1:
                    merged.append(list(split_results.items())[i])
                else:
                    remaining = list(split_results.items())[i:]
                    texts = [text for _, text in remaining]
                    coords = [rect for rect, _ in remaining]
                    min_x1 = min(c[0] for c in coords)
                    min_y1 = min(c[1] for c in coords)
                    max_x2 = max(c[2] for c in coords)
                    max_y2 = max(c[3] for c in coords)
                    merged_text = " ".join(texts)
                    merged.append(((min_x1, min_y1, max_x2, max_y2), merged_text))
            split_results = dict(merged)

        return split_results

    def filter_recognized_text(
        self,
        recognized_texts: Dict[Tuple[int, int, int, int], str],
        full_image: np.ndarray,
    ) -> Dict[Tuple[int, int, int, int], str]:
        """
        Filter OCR recognized texts to match against allowed labels.

        Args:
            recognized_texts (dict): Bounding boxes and detected text.
            full_image (np.array): Upscaled full image.

        Returns:
            dict: Filtered recognized text regions.
        """
        filtered = {}
        keyword_matches = {}
        additional_recognized = {}

        def normalize_label(label_entry):
            if isinstance(label_entry, tuple):
                return " ".join(
                    [" ".join(p) if isinstance(p, tuple) else p for p in label_entry]
                )
            return label_entry

        label_info = sorted(
            self.allowed_labels, key=lambda x: -len(normalize_label(x["label"]))
        )
        normalized_label_pairs = [
            (self.normalize_text(normalize_label(li["label"])), li) for li in label_info
        ]

        for rect, text in recognized_texts.items():
            if len(text.strip()) > 64:
                logger.debug(f"DROPPED: '{text}' (too long)")
                continue

            normalized_text = self.normalize_text(text)
            logger.debug(f"OCR detected: '{text}' -> Normalized: '{normalized_text}'")

            matched_label = None
            label_config = None

            for label_norm, info in normalized_label_pairs:
                if normalized_text == label_norm:
                    matched_label = info.get("real_label", info["label"])
                    label_config = info
                    logger.debug(f"Exact match found: '{matched_label}'")
                    break

            if not matched_label:
                for label_norm, info in normalized_label_pairs:
                    if normalized_text.startswith(label_norm):
                        matched_label = info.get("real_label", info["label"])
                        label_config = info
                        logger.debug("Startswith match found: '{matched_label}'")
                        break
                    elif self.is_single_char_off(
                        normalized_text[: len(label_norm)], label_norm
                    ):
                        matched_label = info.get("real_label", info["label"])
                        label_config = info
                        logger.debug(
                            "Fuzzy Startswith match found (1-char off): '{matched_label}'"
                        )
                        break

            if matched_label and label_config.get("split_words"):
                logger.debug("Splitting label: '{matched_label}' for box {rect}")
                expected_parts = []
                if isinstance(matched_label, tuple):
                    for p in matched_label:
                        if isinstance(p, tuple):
                            expected_parts.append(" ".join(p))
                        else:
                            expected_parts.append(p)
                else:
                    expected_parts = [matched_label]

                split = self.reocr_split_words(
                    full_image, rect, expected_parts=expected_parts
                )
                additional_recognized.update(split)
                continue

            if matched_label:
                keyword_matches.setdefault(matched_label, []).append(
                    (rect, text, matched_label)
                )
            else:
                logger.debug("No match found for: '{text}'")

        if additional_recognized:
            logger.debug(
                "Recursively processing {len(additional_recognized)} split results..."
            )
            filtered.update(
                self.filter_recognized_text(additional_recognized, full_image)
            )

        for label, matches in keyword_matches.items():
            rect, _, label_text = max(
                matches, key=lambda m: (m[0][2] - m[0][0]) * (m[0][3] - m[0][1])
            )
            filtered[rect] = label_text

        return filtered

    def locate_labels(self, image: np.ndarray, on_progress=None) -> Dict[str, Tuple[int, int, int, int]]:
        """
        Locate allowed labels within an image array.

        Args:
            image: np.ndarray (BGR screenshot)

        Returns:
            dict: {label_str: (x1, y1, x2, y2)}
        """
        self.on_progress = on_progress

        self.on_progress("Processing image", 1.0)
        # Preprocess
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_upscaled = cv2.resize(
            gray, None, fx=self.scale_x, fy=1.0, interpolation=cv2.INTER_LINEAR
        )
        
        self.on_progress("Running OCR", 6.0)
        results = self.reader.readtext(gray_upscaled, paragraph=True, height_ths=0.0)
        
        self.on_progress("Processing OCR results", 80.0)
        recognized = {}
        for bbox, text in results:
            x1, y1 = bbox[0]
            x3, y3 = bbox[2]
            x1, y1 = int(x1 / self.scale_x), int(y1)
            x3, y3 = int(x3 / self.scale_x), int(y3)
            recognized[(x1, y1, x3, y3)] = text.strip()

        self.on_progress("Filtering OCR results", 87.0)
        filtered = self.filter_recognized_text(recognized, gray_upscaled)

        # if self.debug:
        #    if self.output_debug_path:
        #        self.draw_debug_output(image, filtered, self.output_debug_path)

        self.on_progress("Building output", 95.0)
        # Build formatted return structure
        label_dict = {}
        for (x1, y1, x2, y2), label in filtered.items():
            label_dict[label] = {
                "top_left": [int(x1), int(y1)],
                "top_right": [int(x2), int(y1)],
                "bottom_left": [int(x1), int(y2)],
                "bottom_right": [int(x2), int(y2)],
            }

        self.on_progress("Completed", 100.0)
        
        return label_dict

    def draw_debug_output(
        self,
        image: np.ndarray,
        recognized_texts: Dict[Tuple[int, int, int, int], str],
        output_path: str,
    ) -> None:
        """
        Draw debug output by overlaying detected labels on the image.

        Args:
            image (np.array): Original image.
            recognized_texts (dict): Detected labels and bounding boxes.
            output_path (str): Path to save output image.
        """
        debug_image = image.copy()

        for (startX, startY, endX, endY), text in recognized_texts.items():
            cv2.rectangle(debug_image, (startX, startY), (endX, endY), (0, 255, 0), 2)
            cv2.putText(
                debug_image,
                text,
                (startX, max(0, startY - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
            )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, debug_image)

        logger.info(f"Debug output saved to {output_path}")
