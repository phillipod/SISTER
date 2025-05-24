import cv2
import numpy as np
import os
import random


from typing import Dict, Tuple

import logging

from ..exceptions import (
    IconGroupLocatorError,
    IconGroupLocatorComputeIconGroupError,
    IconGroupLocatorExpressionParseError,
    IconGroupLocatorExpressionEvaluationError,
)

logger = logging.getLogger(__name__)

"""
Icon Group Locator Rule DSL Documentation

This DSL allows declarative definition of how icon group locations are computed
for icon slots in build screenshots.

The top level of ICON_GROUP_LOCATION_RULES is a dictionary where each key must match the 
computed build type returned by the BuildClassifier. For example, if the LayoutClassifier 
detects "PC Ship Build", rules must be defined under that exact key.

Top-Level Keys:
- variables:     Named constants or expressions used in other expressions.
- icon_group_loops: List of loop blocks that compute icon groups for multiple labels.
- icon_groups:       List of explicit icon group definitions. These run after icon_group_loops so they can 
                 reference looped icon group boxes.

Each icon group definition must define:
- x1: Left X coordinate
- x2: Right X coordinate
- y1: Top Y coordinate
- height: Height in pixels

The output box is structured as:
    {
        "top_left": [x1, y1],
        "bottom_right": [x2, y1 + height]
    }

Expression Types:
- Literal numbers:     5, "2.5"
- Named variables:     any string defined in `variables`
- Label references:    "label:Deflector.mid_y" - for referencing label boxes identified by 
                        the LabelLocator
- Icon group references:   "icon_group:Impulse.right"
- Loop references:     "label:.mid_y" — resolves to current label inside a loop

Supported Operations (used as dictionaries):
- "add":        Adds values. Example: { "add": [a, b] }
- "subtract":   Subtracts second and later from the first
- "divide":     Divides a by b
- "multiply":   Multiplies values together
- "distance":   Absolute difference between two values
- "midpoint":   Midpoint between two coordinates
- "first_of":   Tries each expression in order, returns the first that works
- "contour_right_of": Finds the far-right contour right of a label at given Y
- "minimum_of":  Returns the minimum of each expression
- "maximum_of":  Returns the maximum of each expression

Icon Group Loop Example:
    {
        "labels": ["Label1", "Label2"],
        "loop": {
            "x1": ...,
            "x2": ...,
            "y1": ...,
            "height": ...
        }
    }

"""

ICON_GROUP_LOCATION_RULES = {
    # Icon groups for PC Ship Builds based on relative label geometry and right-side contours.
    #
    # Icon groups are calculated by extending horizontally from the right edge of known labels to the nearest
    # right-side contours, and vertically between the midpoints of labels directly above and below.
    "PC Ship Build": {
        "variables": {
            "padding": 5,
            "deflector_y": "label:Deflector.mid_y",
            "foreweapon_y": "label:Fore Weapon.mid_y",
            "lower_y": {
                "first_of": ["label:Secondary Deflector.mid_y", "label:Impulse.mid_y"]
            },
            "half_upper": {
                "divide": [{"distance": ["deflector_y", "foreweapon_y"]}, 2]
            },
            "half_lower": {"divide": [{"distance": ["lower_y", "deflector_y"]}, 2]},
            "box_height": {"add": ["half_upper", "half_lower"]},
            "deflector_right_x": "label:Deflector.right",
            "max_box_width": {
                "multiply": [
                    {"distance": ["label:Deflector.right", "label:Deflector.left"]},
                    4.5,
                ]
            },
            "max_right_bound": {"add": ["label:Deflector.left", "max_box_width"]},
            "max_right_x": {
                "minimum_of": [
                    {"contour_right_of": ["Deflector", "deflector_y"]},
                    "max_right_bound",
                ]
            },
        },
        # Standard icon groups
        "icon_group_loops": [
            {
                "labels": [
                    "Fore Weapon",
                    "Aft Weapon",
                    "Experimental Weapon",
                    "Shield",
                    "Secondary Deflector",
                    "Deflector",
                    "Impulse",
                    "Warp",
                    "Singularity",
                    "Hangar",
                    "Devices",
                    "Universal Console",
                    "Engineering Console",
                    "Tactical Console",
                    "Science Console",
                ],
                "loop": {
                    "x1": {"add": ["deflector_right_x", 1]},
                    "x2": "max_right_x",
                    "y1": {"subtract": ["label:.mid_y", {"divide": ["box_height", 2]}]},
                    "height": "box_height",
                },
            }
        ],
    },
    # Icon groups for PC Ground Builds based on relative label geometry.
    #
    # Icon rows are typically aligned beneath the label. Padding is derived from horizontal spacing
    # between the "Body" and "EV Suit" labels. Line height is estimated from vertical spacing
    # between "Body" and "Shield" labels.
    "PC Ground Build": {
        "variables": {
            "padding": {
                "divide": [
                    {"subtract": ["label:EV Suit.left", "label:Body.right"]},
                    "3",
                ]
            },
            "line_height": {
                "subtract": ["label:Shield.top", "label:Body.bottom", "padding"]
            },
            "body_left": {"subtract": ["label:Body.left", "padding"]},
            "body_right": {"add": ["label:Body.right", "padding"]},
            "body_top": {"subtract": ["label:Body.bottom", "padding"]},
            "body_bottom": {"add": ["body_top", "line_height"]},
            "icon_width": {"subtract": ["body_right", "body_left"]},
        },
        # Standard icon groups - these run before special case icon groups
        "icon_group_loops": [
            {
                "labels": ["Body", "EV Suit", "Shield", "Kit"],
                "loop": {
                    "x1": {"subtract": ["label:.left", "padding"]},
                    "x2": {"add": ["label:.left", "icon_width"]},
                    "y1": {"subtract": ["label:.bottom", "padding"]},
                    "height": "line_height",
                },
            }
        ],
        # Special case icon groups - these run after standard icon groups
        "icon_groups": [
            {
                "Kit Modules": {
                    "x1": {"subtract": ["label:Kit Modules.left", "padding"]},
                    "x2": "icon_group:Kit.right",  # Use the right edge of the Kit icon group as we have no other good anchor
                    "y1": "label:Kit Modules.bottom",
                    "height": "line_height",
                },
            },
            {
                "Weapon": {
                    "x1": {"subtract": ["label:Weapon.left", "padding"]},
                    "x2": {"add": ["label:Weapon.left", "icon_width"]},
                    "y1": {"subtract": ["label:Weapon.bottom", "padding"]},
                    "height": {"multiply": ["line_height", 2]},
                },
            },
            {
                "Devices": {
                    "x1": {"subtract": ["label:Devices.left", "padding"]},
                    "x2": {
                        "add": ["label:Devices.left", {"multiply": ["icon_width", 2]}]
                    },
                    "y1": {"subtract": ["label:Devices.bottom", "padding"]},
                    "height": {"multiply": ["line_height", 3]},
                }
            },
        ],
    },
    # Icon groups for Console Ship Builds based on relative label geometry.
    #
    # This layout has three columns:
    #     - Column 1 (Left): Stacked vertically: Fore Weapon, Aft Weapon, Experimental Weapon (optional), Devices
    #     - Column 2 (Center): Horizontal row: Shields, Deflector, Impulse, Warp/Singularity, Hangar (optional)
    #     - Column 3 (Right): Stacked vertically: Engineering Console, Tactical Console, Science Console, Universal Console (optional)
    #
    # Icon groups are placed *below* each label.
    "Console Ship Build": {
        "variables": {
            "padding": 20,
            "vertical_padding": 5,
            "col1_left": {"subtract": ["label:Fore Weapon.left", "padding"]},
            "col3_right": {"add": ["label:Engineering Console.right", "padding"]},
            "col2_left": {"subtract": ["label:Shield.left", "padding"]},
            "col2_right": {
                "add": [
                    {
                        "first_of": [
                            "label:Hangar.right",
                            "label:Warp.right",
                            "label:Singularity.right",
                        ]
                    },
                    "padding",
                ]
            },
            "col1_right": {"subtract": ["col2_left", "padding"]},
            "col3_left": {"add": ["col2_right", "padding"]},
            "line_height": {
                "add": [
                    {"subtract": ["label:Aft Weapon.top", "Fore Weapon.bottom"]},
                    "vertical_padding",
                ]
            },
            "shield_deflector_mid": {
                "midpoint": ["label:Shield.right", "label:Deflector.left"]
            },
            "deflector_impulse_mid": {
                "midpoint": ["label:Deflector.right", "label:Impulse.left"]
            },
            "impulse_warp_mid": {
                "midpoint": [
                    {"first_of": ["label:Impulse.right"]},
                    {"first_of": ["label:Warp.left", "label:Singularity.left"]},
                ]
            },
            "warp_right": {"first_of": ["label:Warp.right", "label:Singularity.right"]},
        },
        # Standard icon groups - these run before special case icon groups
        "icon_group_loops": [
            {
                "labels": [
                    "Fore Weapon",
                    "Aft Weapon",
                    "Experimental Weapon",
                    "Devices",
                ],
                "loop": {
                    "x1": "col1_left",
                    "x2": "col1_right",
                    "y1": {"subtract": ["label:.bottom", "vertical_padding"]},
                    "height": "line_height",
                },
            },
            {
                "labels": [
                    "Engineering Console",
                    "Tactical Console",
                    "Science Console",
                    "Universal Console",
                ],
                "loop": {
                    "x1": "col3_left",
                    "x2": "col3_right",
                    "y1": {"subtract": ["label:.bottom", "vertical_padding"]},
                    "height": "line_height",
                },
            },
            {
                "labels": ["Warp", "Singularity"],
                "loop": {
                    "x1": "impulse_warp_mid",
                    "x2": "warp_right",  # Use the right edge of the col2 icon group as we have no other good anchor"]"first_of": ["icon_group:Hangar.left", "col2_right"]}, # Use the right edge of the col2 icon group as we have no other good anchor"}"col2_right",
                    "y1": {"subtract": ["label:.bottom", "vertical_padding"]},
                    "height": "line_height",
                },
            },
        ],
        # Special case icon groups - these run after standard icon groups
        "icon_groups": [
            {
                "Shield": {
                    "x1": "col2_left",
                    "x2": "shield_deflector_mid",
                    "y1": {"subtract": ["label:Shield.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Deflector": {
                    "x1": "shield_deflector_mid",
                    "x2": "deflector_impulse_mid",
                    "y1": {"subtract": ["label:Deflector.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Impulse": {
                    "x1": "deflector_impulse_mid",
                    "x2": "impulse_warp_mid",
                    "y1": {"subtract": ["label:Impulse.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Hangar": {
                    "x1": {"add": ["warp_right", {"divide": ["padding", "4"]}]},
                    "x2": "col2_right",
                    "y1": {"subtract": ["label:Hangar.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
        ],
    },
    "Console Ground Build": {
        "variables": {
            "padding": 20,
            "vertical_padding": 5,
            "line_height": {
                "add": [
                    {"subtract": ["label:Body.top", "label:Weapon.bottom"]},
                    "vertical_padding",
                ]
            },
            "weapon_devices_mid": {
                "midpoint": ["label:Weapon.right", "label:Devices.left"]
            },
            "body_evsuit_mid": {"midpoint": ["label:Body.right", "label:EV Suit.left"]},
            "evsuit_shield_mid": {
                "midpoint": ["label:EV Suit.right", "label:Shield.left"]
            },
            "shield_kitframe_mid": {
                "midpoint": ["label:Shield.right", "label:Kit Frame.left"]
            },
            "kit_right": "label:Kit Frame.right",
        },
        "icon_groups": [
            {
                "Weapon": {
                    "x1": {"subtract": ["label:Weapon.left", "padding"]},
                    "x2": "weapon_devices_mid",
                    "y1": {"subtract": ["label:Weapon.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Devices": {
                    "x1": {"subtract": ["label:Devices.left", "padding"]},
                    "x2": "kit_right",
                    "y1": {"subtract": ["label:Devices.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Body": {
                    "x1": "label:Body.left",
                    "x2": "body_evsuit_mid",
                    "y1": {"subtract": ["label:Body.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "EV Suit": {
                    "x1": "body_evsuit_mid",
                    "x2": "evsuit_shield_mid",
                    "y1": {"subtract": ["label:EV Suit.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Shield": {
                    "x1": "evsuit_shield_mid",
                    "x2": "shield_kitframe_mid",
                    "y1": {"subtract": ["label:Shield.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Kit Frame": {
                    "x1": "shield_kitframe_mid",
                    "x2": "kit_right",
                    "y1": {"subtract": ["label:Kit Frame.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
            {
                "Kit": {
                    "x1": "label:Kit.left",
                    "x2": "kit_right",
                    "y1": {"subtract": ["label:Kit.bottom", "vertical_padding"]},
                    "height": "line_height",
                }
            },
        ],
    },
}


class IconGroupLocator:
    """
    Pipeline aware icon group locator. Detects groups of Regions of Interest (ROIs) in Star Trek Online screenshots based on detected label positions
    and classified build types. Primarily focuses on narrowing search areas for icon detection.

    Attributes:
        debug (bool): If True, enables diagnostic image output.
    """

    def __init__(self, debug: bool = False):
        """
        Initialize the IconGroupLocator.

        Args:
            debug (bool): Whether to enable debug output.
        """
        self.debug = debug

    def locate_icon_groups(
        self,
        image: np.ndarray,
        labels: Dict[str, Tuple[int, int, int, int]],
        build_info: any = None,
    ) -> Dict[str, Tuple[int, int, int, int]]:
        """
        Main detection entry point. Based on build type, routes to appropriate detection logic.

        Args:
            screenshot_color (np.array): Original BGR screenshot.
            build_info (dict): Output from BuildClassifier, includes build_type and score.
            label_positions (dict): Output from LabelLocator with bounding boxes.
            debug_output_path (str, optional): If set, draws debug output to this file.

        Returns:
            dict: Mapping of label name to {'Label': <bbox>, 'IconGroup': <roi bbox>}.
        """
        # ensure we have a list of build dicts
        builds = build_info if isinstance(build_info, list) else [build_info]

        gray = self._preprocess_grayscale(image)
        dilated = self._apply_dilation(gray)
        contours = self._find_contours(dilated)

        merged: Dict[str, Dict[str, Any]] = {}
        for info in builds:
            bt = info.get("build_type", "Unknown")
            print(f"locating icon groups for build: {bt}")

            if bt not in ICON_GROUP_LOCATION_RULES:
                logger.warning(f"Unsupported build type: {bt}")
                continue

            # get raw icon‐group boxes for this build
            icon_boxes = self.compute_icon_groups(bt, labels, contours)

            # convert each into your merged format
            for label, icon_group in icon_boxes.items():
                label_box = labels[label]
                merged[label] = {
                    "Label": {key: [int(v[0]), int(v[1])] for key, v in label_box.items()},
                    "IconGroup": {
                        "top_left":     [int(icon_group["top_left"][0]),     int(icon_group["top_left"][1])],
                        "bottom_right": [int(icon_group["bottom_right"][0]), int(icon_group["bottom_right"][1])]
                    },
                }

        return merged

#         print(f"build_info: {build_info}")
#         build_type = build_info.get("build_type", "Unknown")
#         icon_group_boxes = {}

#         if build_type in ICON_GROUP_LOCATION_RULES:
#             icon_group_boxes = self.compute_icon_groups(build_type, labels, contours)
#         else:
#             logger.warning(f"Unsupported build type: {build_type}")
# #            raise IconGroupLocatorError(f"Unsupported build type: {build_type}")
#             return {}

#         merged = {}
#         for label, icon_group in icon_group_boxes.items():
#             label_box = labels[label]
#             merged[label] = {
#                 "Label": {key: [int(v[0]), int(v[1])] for key, v in label_box.items()},
#                 "IconGroup": {
#                     "top_left": [
#                         int(icon_group["top_left"][0]),
#                         int(icon_group["top_left"][1]),
#                     ],
#                     "bottom_right": [
#                         int(icon_group["bottom_right"][0]),
#                         int(icon_group["bottom_right"][1]),
#                     ],
#                 },
#             }

        # if self.debug and debug_output_path:
        #    self._draw_debug_icon_groups(image, merged, debug_output_path)

        return merged

    def _preprocess_grayscale(self, image):
        """
        Convert a color image to grayscale.

        Args:
            image (np.array): Input BGR image.

        Returns:
            np.array: Grayscale image.
        """
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def _apply_dilation(self, gray):
        """
        Apply Gaussian blur and morphological dilation to emphasize contours.

        Args:
            gray (np.array): Grayscale image.

        Returns:
            np.array: Edge-detected and dilated image.
        """
        blurred = cv2.GaussianBlur(gray, (3, 3), 0.65)
        edges = cv2.Canny(blurred, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
        return cv2.dilate(edges, kernel, iterations=2)

    def _find_contours(self, edge_img):
        """
        Detect contours in a binary edge map.

        Args:
            edge_img (np.array): Input binary image from Canny + dilation.

        Returns:
            list: List of contours (OpenCV format).
        """
        contours, _ = cv2.findContours(
            edge_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return contours

    def evaluate_expression(
        self, expr, labels, context, contours=None, current_label=None, icon_groups=None
    ):
        """
        Evaluate an expression in the context of detected labels and icon groups.

        The expression can be a string (resolved as a label or icon group property), a number (used as-is),
        or a dictionary (with supported operations).

        Args:
            expr (str or dict): Expression to evaluate.
            labels (dict): Mapping of label names to bounding boxes.
            context (dict): Additional context variables.
            contours (list, optional): List of contours (OpenCV format).
            current_label (str, optional): Current label being processed.
            icon_groups (dict, optional): Mapping of icon group names to bounding boxes.

        Returns:
            Any: Result of the evaluation.
        """
        try:
            # self.debug = True

            # if self.debug:
            logger.debug(
                f"Evaluating expression: {expr} (current_label={current_label})"
            )

            if isinstance(expr, (int, float)):
                return expr
            if isinstance(expr, str):
                if expr in context:
                    # print(f"expr: {expr}, context: {context}")
                    val = context[expr]
                    if self.debug:
                        logger.debug(f"Resolved variable '{expr}' to {val}")
                    return val
                if expr.isdigit():
                    return int(expr)
                try:
                    return float(expr)
                except ValueError:
                    pass

                # Explicit source (label: or icon_group:)
                if ":" in expr:
                    source, key = expr.split(":", 1)
                    if key.startswith(".") and current_label:
                        key = f"{current_label}.{key[1:]}"
                    label, prop = key.rsplit(".", 1)
                    if source == "label":
                        box = labels.get(label)
                        # print(f"label: {label}, box: {box}")
                        if not box:
                            raise ValueError(f"Unknown label reference: {label}")
                    elif source == "icon_group":
                        box = context.get("icon_groups", {}).get(label)
                        if not box:
                            raise ValueError(f"Unknown icon_group reference: {label}")
                    else:
                        raise ValueError(f"Unknown source prefix: {source}")
                else:
                    # Implicit, default to labels then icon_groups
                    if expr.startswith(".") and current_label:
                        expr = f"{current_label}{expr}"
                    label, prop = expr.rsplit(".", 1)
                    box = labels.get(label)
                    # print(f"label: {label}, box: {box}")
                    if not box and icon_groups:
                        box = icon_groups.get(label)
                    if not box:
                        raise ValueError(f"Unknown reference: {expr}")

                val = None
                if prop == "left":
                    val = box["top_left"][0]
                elif prop == "right":
                    val = box["bottom_right"][0]
                elif prop == "top":
                    val = box["top_left"][1]
                elif prop == "bottom":
                    val = box["bottom_left"][1]
                elif prop == "mid_y":
                    val = (box["top_left"][1] + box["bottom_right"][1]) // 2
                else:
                    raise ValueError(f"Unsupported property: {prop}")

                if self.debug:
                    logger.debug(f"Resolved '{expr}' to {val}")
                return val

            if isinstance(expr, dict):
                if "add" in expr:
                    values = [
                        self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        for v in expr["add"]
                    ]
                    result = sum(values)
                    if self.debug:
                        logger.debug(f"add {values} = {result}")
                    return result
                if "subtract" in expr:
                    values = [
                        self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        for v in expr["subtract"]
                    ]
                    result = values[0] - sum(values[1:])
                    if self.debug:
                        logger.debug(f"subtract {values} = {result}")
                    return result
                if "divide" in expr:
                    a, b = [
                        self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        for v in expr["divide"]
                    ]
                    result = (
                        a // b if isinstance(a, int) and isinstance(b, int) else a / b
                    )
                    if self.debug:
                        logger.debug(f"divide {a} / {b} = {result}")
                    return result
                if "multiply" in expr:
                    result = 1
                    values = []
                    for v in expr["multiply"]:
                        val = self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        values.append(val)
                        result *= val
                    if self.debug:
                        logger.debug(f"multiply {values} = {result}")
                    return result
                if "midpoint" in expr:
                    a, b = [
                        self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        for v in expr["midpoint"]
                    ]
                    result = (a + b) // 2
                    if self.debug:
                        logger.debug(f"midpoint of {a} and {b} = {result}")
                    return result
                if "distance" in expr:
                    a, b = [
                        self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        for v in expr["distance"]
                    ]
                    result = abs(a - b)
                    if self.debug:
                        logger.debug(f"distance between {a} and {b} = {result}")
                    return result
                if "first_of" in expr:
                    for key in expr["first_of"]:
                        try:
                            result = self.evaluate_expression(
                                key,
                                labels,
                                context,
                                contours,
                                current_label,
                                icon_groups,
                            )
                            if self.debug:
                                logger.debug(f"first_of picked {key} = {result}")
                            return result
                        except Exception:
                            continue
                    raise ValueError(
                        f"No valid option found in first_of: {expr['first_of']}"
                    )
                if "contour_right_of" in expr and contours is not None:
                    label, y_ref = expr["contour_right_of"]
                    y_value = self.evaluate_expression(
                        y_ref, labels, context, contours, current_label, icon_groups
                    )
                    label_box = labels[label]
                    base_right = label_box["top_right"][0]
                    max_right = base_right
                    for cnt in contours:
                        x, y, w, h = cv2.boundingRect(cnt)
                        if y <= y_value <= y + h and x > base_right:
                            max_right = max(max_right, x + w)
                    if self.debug:
                        logger.debug(
                            f"contour_right_of for {label} at y={y_value} = {max_right}"
                        )
                    return max_right
                if "maximum_of" in expr:
                    values = [
                        self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        for v in expr["maximum_of"]
                    ]
                    result = max(values)
                    if self.debug:
                        logger.debug(f"maximum_of {values} = {result}")
                    return result
                if "minimum_of" in expr:
                    values = [
                        self.evaluate_expression(
                            v, labels, context, contours, current_label, icon_groups
                        )
                        for v in expr["minimum_of"]
                    ]
                    result = min(values)
                    if self.debug:
                        logger.debug(f"minimum_of {values} = {result}")
                    return result

                raise ValueError(f"Unsupported expression: {expr}")

            raise TypeError(f"Unsupported type: {type(expr)}")
        except ValueError as e:
            raise IconGroupLocatorExpressionParseError(
                f"Parsing error in expression '{expr}': {e}"
            ) from e
        except Exception as e:
            raise IconGroupLocatorExpressionEvaluationError(
                f"Evaluation error in expression '{expr}': {e}"
            ) from e

    def compute_icon_groups(self, build_type, labels, contours=None):
        """
        Compute icon groups based on the build type rules and label positions.

        This function evaluates expressions defined in the icon group detection rule set for
        a given build type to locate icon groups. It processes both
        looped icon group definitions and explicit icon group definitions according to the specified
        rules.

        Args:
            build_type (str): The type of build, used to select the appropriate rule set from
                            ICON_GROUP_LOCATION_RULES.
            labels (dict): A dictionary mapping label names to their bounding box coordinates.
            contours (list, optional): A list of contours that may be used in some icon group
                                    calculations, typically obtained from image preprocessing.

        Returns:
            dict: A dictionary mapping label names to their computed icon group bounding boxes. Each
                bounding box is represented as a dictionary with 'top_left' and 'bottom_right'
                coordinates.
        """
        rule = ICON_GROUP_LOCATION_RULES.get(build_type)
        if not rule:
            logger.warning(f"No icon group rules found for build type: {build_type}")
            return {}

        context = {}
        context["icon_groups"] = {}

        # print(f"labels: {labels}")
        for var, expr in rule.get("variables", {}).items():
            # print(f"Computing variable '{var}'")
            try:
                context[var] = self.evaluate_expression(expr, labels, context, contours)
            except Exception as e:
                # logger.warning(f"Failed to compute variable '{var}': {e}")
                raise IconGroupLocatorComputeIconGroupError(
                    f"Failed to compute variable [{build_type}]::'{var}': {e}"
                ) from e

        icon_groups = {}

        if "icon_group_loops" in rule:
            for loop_cfg in rule["icon_group_loops"]:
                for label in loop_cfg["labels"]:
                    if label not in labels:
                        continue
                    logger.debug(f"Computing looped icon group for {label}")
                    # print(f"Computing looped icon_group for {label}")
                    try:
                        defn = loop_cfg["loop"]

                        x1 = self.evaluate_expression(
                            defn["x1"],
                            labels,
                            context,
                            contours,
                            current_label=label,
                            icon_groups=context["icon_groups"],
                        )
                        x2 = self.evaluate_expression(
                            defn["x2"],
                            labels,
                            context,
                            contours,
                            current_label=label,
                            icon_groups=context["icon_groups"],
                        )
                        y1 = self.evaluate_expression(
                            defn["y1"],
                            labels,
                            context,
                            contours,
                            current_label=label,
                            icon_groups=context["icon_groups"],
                        )

                        h = self.evaluate_expression(
                            defn["height"],
                            labels,
                            context,
                            contours,
                            current_label=label,
                            icon_groups=context["icon_groups"],
                        )
                        icon_group_box = {
                            "top_left": [int(x1), int(y1)],
                            "bottom_right": [int(x2), int(y1 + h)],
                        }
                        context["icon_groups"][label] = icon_group_box
                        icon_groups[label] = icon_group_box
                    except Exception as e:
                        # logger.warning(f"Failed to compute looped icon group for {label}: {e}")
                        raise IconGroupLocatorComputeIconGroupError(
                            f"Failed to compute looped icon group [{build_type}]::'{label}': {e}"
                        ) from e

        if "icon_groups" in rule:
            for entry in rule["icon_groups"]:
                if not isinstance(entry, dict) or len(entry) != 1:
                    logger.warning(f"Malformed icon group entry: {entry}")
                    continue
                label, defn = next(iter(entry.items()))
                if label not in labels:
                    continue
                try:
                    x1 = self.evaluate_expression(defn["x1"], labels, context, contours)
                    x2 = self.evaluate_expression(defn["x2"], labels, context, contours)
                    y1 = self.evaluate_expression(defn["y1"], labels, context, contours)
                    h = self.evaluate_expression(
                        defn["height"], labels, context, contours
                    )
                    context["icon_groups"][label] = {
                        "top_left": [int(x1), int(y1)],
                        "bottom_right": [int(x2), int(y1 + h)],
                    }
                except Exception as e:
                    # logger.warning(f"Failed to compute icon group for {label}: {e}")
                    raise IconGroupLocatorComputeIconGroupError(
                        f"Failed to compute icon group [{build_type}]::'{label}': {e}"
                    ) from e

        return context["icon_groups"]

    def _draw_debug_icon_groups(self, image, icon_groups, output_path):
        """
        Draw labeled icon group rectangles on a copy of the original image and save as a debug visualization.

        Each icon group is drawn with a randomly colored bounding box and annotated with the label name.
        Used for visual verification of icon group detection accuracy.

        Args:
            image (np.array): Original BGR screenshot.
            icon_groups (dict): Dictionary of label names to icon group and label bounding boxes.
            output_path (str): Path to save the annotated debug image.
        """
        debug_image = image.copy()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        print(f"Drawing {len(icon_groups)} icon_groups")
        print(f"image.shape: {image.shape}")
        print(f"IconGroups: {icon_groups}")
        for label, entry in icon_groups.items():
            print(f"Label: {label}")
            print(f"Entry: {entry}")
            x1, y1 = entry["IconGroup"]["top_left"]
            x2, y2 = entry["IconGroup"]["bottom_right"]
            color = [random.randint(0, 255) for _ in range(3)]
            cv2.rectangle(debug_image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                debug_image,
                label,
                (x1 + 5, y1 + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

        cv2.imwrite(output_path, debug_image)
        logger.info(f"Wrote debug image to {output_path}")
