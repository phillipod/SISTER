import cv2
import numpy as np
import os
import random

import json

from typing import Any, Callable, Dict, List, Tuple, Optional

import logging

logger = logging.getLogger(__name__)

"""
Region Detection Rule DSL Documentation

This DSL allows declarative definition of how bounding boxes (regions) are computed
for icon slots in build screenshots.

The top level of ROI_DETECTION_RULES is a dictionary where each key must match the 
computed build type returned by the BuildClassifier. For example, if the BuildClassifier 
detects "PC Ship Build", rules must be defined under that exact key.

Top-Level Keys:
- variables:     Named constants or expressions used in other expressions.
- regions_loops: List of loop blocks that compute region boxes for multiple labels.
- regions:       List of explicit region definitions. These run after region_loops so they can 
                 reference looped region boxes.

Each region definition must define:
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
- Region references:   "region:Impulse.right"
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

Region Loop Example:
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

ROI_DETECTION_RULES = {
    # ROI regions for PC Ship Builds based on relative label geometry and right-side contours.
    #
    # ROIs are calculated by extending horizontally from the right edge of known labels to the nearest 
    # right-side contours, and vertically between the midpoints of labels directly above and below. 
    "PC Ship Build": {
        "variables": {
            "padding": 5,
            "deflector_y": "label:Deflector.mid_y",
            "foreweapon_y": "label:Fore Weapon.mid_y",
            "lower_y": {"first_of": ["label:Secondary Deflector.mid_y", "label:Impulse.mid_y"]},
            "half_upper": {"divide": [{"distance": ["deflector_y", "foreweapon_y"]}, 2]},
            "half_lower": {"divide": [{"distance": ["lower_y", "deflector_y"]}, 2]},
            "box_height": {"add": ["half_upper", "half_lower"]},
            "deflector_right_x": "label:Deflector.right",
            "max_box_width": {"multiply": [{"distance": ["label:Deflector.right", "label:Deflector.left"]}, 4.5]},
            "max_right_bound": {"add": ["label:Deflector.left", "max_box_width"]},
            "max_right_x": {
                "minimum_of": [
                    {"contour_right_of": ["Deflector", "deflector_y"]},
                    "max_right_bound"
                ]
            }
        },

        # Standard regions
        "regions_loops": [
            {
                "labels": [
                    "Fore Weapon", "Aft Weapon", "Experimental Weapon", "Shield", "Secondary Deflector",
                    "Deflector", "Impulse", "Warp", "Singularity", "Hangar", "Devices",
                    "Universal Console", "Engineering Console", "Tactical Console", "Science Console"
                ],
                "loop": {
                    "x1": {"add": ["deflector_right_x", 1]},
                    "x2": "max_right_x",
                    "y1": {"subtract": ["label:.mid_y", {"divide": ["box_height", 2]}]},
                    "height": "box_height"
                }
            }
        ]
    },

    # ROI regions for PC Ground Builds based on relative label geometry.
    #
    # Icon rows are typically aligned beneath the label. Padding is derived from horizontal spacing
    # between the "Body" and "EV Suit" labels. Line height is estimated from vertical spacing 
    # between "Body" and "Shield" labels.
    "PC Ground Build": {
        "variables": {
            "padding": {"divide": [ {"subtract": ["label:EV Suit.left", "label:Body.right"]}, "3" ]},
            "line_height": {"subtract": ["label:Shield.top", "label:Body.bottom", "padding"]},
            "body_left": {"subtract": ["label:Body.left", "padding"]},
            "body_right": {"add": ["label:Body.right", "padding"]},
            "body_top": {"subtract": ["label:Body.bottom", "padding"]},
            "body_bottom": {"add": ["body_top", "line_height"]},
            "icon_width": {"subtract": ["body_right", "body_left"]}
        },

        # Standard regions - these run before special case regions
        "regions_loops": [
            {
                "labels": [ "Body", "EV Suit", "Shield", "Kit" ],
                "loop": {
                    "x1": {"subtract": ["label:.left", "padding"]},
                    "x2": {"add": ["label:.left", "icon_width"]},
                    "y1": {"subtract": ["label:.bottom", "padding"]},
                    "height": "line_height"
                }
            }
        ],

        # Special case regions - these run after standard regions
        "regions": [
            {
                "Kit Modules": {
                    "x1": {"subtract": ["label:Kit Modules.left", "padding"]},
                    "x2": "region:Kit.right", # Use the right edge of the Kit region as we have no other good anchor
                    "y1": "label:Kit Modules.bottom",
                    "height": "line_height"
                },
            },
            {
                "Weapon": {
                    "x1": {"subtract": ["label:Weapon.left", "padding"]},
                    "x2": {"add": ["label:Weapon.left", "icon_width"]},
                    "y1": {"subtract": ["label:Weapon.bottom", "padding"]},
                    "height": {"multiply": ["line_height", 2]}
                },
            },
            {
                "Devices": {
                    "x1": {"subtract": ["label:Devices.left", "padding"]},
                    "x2": {"add": ["label:Devices.left", {"multiply": ["icon_width", 2]}]},
                    "y1": {"subtract": ["label:Devices.bottom", "padding"]},
                    "height": {"multiply": ["line_height", 3]}
                }
            }
        ]
    },

    # ROI regions for Console Ship Builds based on relative label geometry.
    #
    # This layout has three columns:
    #     - Column 1 (Left): Stacked vertically: Fore Weapon, Aft Weapon, Experimental Weapon (optional), Devices
    #     - Column 2 (Center): Horizontal row: Shields, Deflector, Impulse, Warp/Singularity, Hangar (optional)
    #     - Column 3 (Right): Stacked vertically: Engineering Console, Tactical Console, Science Console, Universal Console (optional)
    #
    # Icon regions are placed *below* each label.
    "Console Ship Build": {
       

        "variables": {
            "padding": 20,
            "vertical_padding": 5,

            "col1_left": {"subtract": ["label:Fore Weapon.left", "padding"]},
            "col3_right": {"add": ["label:Engineering Console.right", "padding"]},
            "col2_left": {"subtract": ["label:Shield.left", "padding"]},
            "col2_right": {"add": [{"first_of": ["label:Hangar.right", "label:Warp.right", "label:Singularity.right"]} , "padding"]},
            "col1_right": {"subtract": ["col2_left", "padding"]},
            "col3_left": {"add": ["col2_right" , "padding"]},

            "line_height": {"add": [
                {"subtract": ["label:Aft Weapon.top", "Fore Weapon.bottom"]},
                "vertical_padding"
            ]},

            "shield_deflector_mid": {"midpoint": ["label:Shield.right", "label:Deflector.left"]},
            "deflector_impulse_mid": {"midpoint": ["label:Deflector.right", "label:Impulse.left"]},
            "impulse_warp_mid": {"midpoint": [
                {"first_of": ["label:Impulse.right"]},
                {"first_of": ["label:Warp.left", "label:Singularity.left"]}
            ]},
            "warp_right": {"first_of": ["label:Warp.right", "label:Singularity.right"]}

        },

        # Standard regions - these run before special case regions
        "regions_loops": [
            {
                "labels": [ "Fore Weapon", "Aft Weapon", "Experimental Weapon", "Devices" ],
                "loop": {
                    "x1": "col1_left",
                    "x2": "col1_right",
                    "y1": {"subtract": ["label:.bottom", "vertical_padding"]},
                    "height": "line_height"
                }
            },
            {
                "labels": ["Engineering Console", "Tactical Console", "Science Console", "Universal Console"],
                "loop": {
                    "x1": "col3_left",
                    "x2": "col3_right",
                    "y1": {"subtract": ["label:.bottom", "vertical_padding"]},
                    "height": "line_height"
                }
            },
            {
                "labels": ["Warp", "Singularity"],
                "loop": {
                    "x1": "impulse_warp_mid",
                    "x2": "warp_right", # Use the right edge of the col2 region as we have no other good anchor"]"first_of": ["region:Hangar.left", "col2_right"]}, # Use the right edge of the col2 region as we have no other good anchor"}"col2_right",
                    "y1": {"subtract": ["label:.bottom", "vertical_padding"]},
                    "height": "line_height"
                }
            }
        ],

        # Special case regions - these run after standard regions
        "regions": [
            { "Shield":      {"x1": "col2_left", "x2": "shield_deflector_mid", "y1": {"subtract": ["label:Shield.bottom", "vertical_padding"]}, "height": "line_height"} },
            { "Deflector":   {"x1": "shield_deflector_mid", "x2": "deflector_impulse_mid", "y1": {"subtract": ["label:Deflector.bottom", "vertical_padding"]}, "height": "line_height"} },
            { "Impulse":     {"x1": "deflector_impulse_mid", "x2": "impulse_warp_mid", "y1": {"subtract": ["label:Impulse.bottom", "vertical_padding"]}, "height": "line_height"} },
            { "Hangar":      {"x1": {"add": ["warp_right", {"divide": ["padding", "4"]}]}, "x2": "col2_right", "y1": {"subtract": ["label:Hangar.bottom", "vertical_padding"]}, "height": "line_height"} }
        ]
    },

    "Console Ground Build": {
        "variables": {
            "padding": 20,
            "vertical_padding": 5,
            "line_height": {
                "add": [
                    {"subtract": ["label:Body.top", "label:Weapon.bottom"]},
                    "vertical_padding"
                ]
            },
            "weapon_devices_mid": {"midpoint": ["label:Weapon.right", "label:Devices.left"]},
            "body_evsuit_mid": {"midpoint": ["label:Body.right", "label:EV Suit.left"]},
            "evsuit_shield_mid": {"midpoint": ["label:EV Suit.right", "label:Shield.left"]},
            "shield_kitframe_mid": {"midpoint": ["label:Shield.right", "label:Kit Frame.left"]},
            "kit_right": "label:Kit Frame.right"
        },
        "regions": [
            { "Weapon": {
                "x1": {"subtract": ["label:Weapon.left", "padding"]}, 
                "x2": "weapon_devices_mid",
                "y1": {"subtract": ["label:Weapon.bottom", "vertical_padding"]},
                "height": "line_height"
            }},
            { "Devices": {
                "x1": {"subtract": ["label:Devices.left", "padding"]},
                "x2": "kit_right",
                "y1": {"subtract": ["label:Devices.bottom", "vertical_padding"]},
                "height": "line_height"
            }},
            { "Body": {
                "x1": "label:Body.left",
                "x2": "body_evsuit_mid",
                "y1": {"subtract": ["label:Body.bottom", "vertical_padding"]},
                "height": "line_height"
            }},
            { "EV Suit": {
                "x1": "body_evsuit_mid",
                "x2": "evsuit_shield_mid",
                "y1": {"subtract": ["label:EV Suit.bottom", "vertical_padding"]},
                "height": "line_height"
            }},
            { "Shield": {
                "x1": "evsuit_shield_mid",
                "x2": "shield_kitframe_mid",
                "y1": {"subtract": ["label:Shield.bottom", "vertical_padding"]},
                "height": "line_height"
            }},
            { "Kit Frame": {
                "x1": "shield_kitframe_mid",
                "x2": "kit_right",
                "y1": {"subtract": ["label:Kit Frame.bottom", "vertical_padding"]},
                "height": "line_height"
            }},
            { "Kit": {
                "x1": "label:Kit.left",
                "x2": "kit_right",
                "y1": {"subtract": ["label:Kit.bottom", "vertical_padding"]},
                "height": "line_height"
            }}
        ]
    }


}

class RegionDetector:
    """
    Pipeline aware region detector. Detects Regions of Interest (ROIs) in Star Trek Online screenshots based on detected label positions
    and classified build types. Primarily focuses on narrowing search areas for icon detection.

    Attributes:
        debug (bool): If True, enables diagnostic image output.
    """

    def __init__(self, debug: bool = False):
        """
        Initialize the RegionDetector.

        Args:
            debug (bool): Whether to enable debug output.
        """
        self.debug = debug

    def detect_regions(
        self,
        image: np.ndarray,
        labels: Dict[str, Tuple[int, int, int, int]],
        build_info: any = None
    ) -> Dict[str, Tuple[int, int, int, int]]:
        """
        Main detection entry point. Based on build type, routes to appropriate detection logic.

        Args:
            screenshot_color (np.array): Original BGR screenshot.
            build_info (dict): Output from BuildClassifier, includes build_type and score.
            label_positions (dict): Output from LabelLocator with bounding boxes.
            debug_output_path (str, optional): If set, draws debug output to this file.

        Returns:
            dict: Mapping of label name to {'Label': <bbox>, 'Region': <roi bbox>}.
        """
        gray = self._preprocess_grayscale(image)
        dilated = self._apply_dilation(gray)
        contours = self._find_contours(dilated)

        if self.debug and debug_output_path:
            base, _ = os.path.splitext(debug_output_path)
            os.makedirs(os.path.dirname(base), exist_ok=True)
            cv2.imwrite(f"{base}_gray.png", gray)
            cv2.imwrite(f"{base}_dilated.png", dilated)
            debug_contours = cv2.cvtColor(dilated.copy(), cv2.COLOR_GRAY2BGR)
            cv2.drawContours(debug_contours, contours, -1, (0, 255, 0), 1)
            cv2.imwrite(f"{base}_contours.png", debug_contours)

        build_type = build_info.get("build_type", "Unknown")
        region_boxes = {}

        # if build_type == "PC Ship Build":
        #     #region_boxes = self._detect_pc_ship_rois(label_positions, contours)
        #     region_boxes = self.compute_regions(build_type, label_positions, contours)
        # elif build_type == "PC Ground Build":
        #     #region_boxes = self._detect_pc_ground_rois(label_positions)
        #     region_boxes = self.compute_regions(build_type, label_positions)
        # elif build_type == "Console Ship Build":
        #     #region_boxes = self._detect_console_ship_rois(label_positions)
        #     region_boxes = self.compute_regions(build_type, label_positions)
        # else:
        #     logger.warning(f"Unsupported build type: {build_type}")
        #     return {}

        if build_type in ROI_DETECTION_RULES:
            region_boxes = self.compute_regions(build_type, labels, contours)
        else:
            logger.warning(f"Unsupported build type: {build_type}")
            return {}


        merged = {}
        for label, region in region_boxes.items():
            label_box = labels[label]
            merged[label] = {
                "Label": {
                    key: [int(v[0]), int(v[1])] for key, v in label_box.items()
                },
                "Region": {
                    "top_left": [int(region["top_left"][0]), int(region["top_left"][1])],
                    "bottom_right": [int(region["bottom_right"][0]), int(region["bottom_right"][1])]
                }
            }

        #if self.debug and debug_output_path:
        #    self._draw_debug_regions(image, merged, debug_output_path)

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
        contours, _ = cv2.findContours(edge_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return contours

    def evaluate_expression(self, expr, labels, context, contours=None, current_label=None, regions=None):
        """
        Evaluate an expression in the context of detected labels and regions.

        The expression can be a string (resolved as a label or region property), a number (used as-is),
        or a dictionary (with supported operations).

        Args:
            expr (str or dict): Expression to evaluate.
            labels (dict): Mapping of label names to bounding boxes.
            context (dict): Additional context variables.
            contours (list, optional): List of contours (OpenCV format).
            current_label (str, optional): Current label being processed.
            regions (dict, optional): Mapping of region names to bounding boxes.

        Returns:
            Any: Result of the evaluation.
        """
        #self.debug = True

        #if self.debug:
        logger.debug(f"Evaluating expression: {expr} (current_label={current_label})")

        if isinstance(expr, (int, float)):
            return expr
        if isinstance(expr, str):
            if expr in context:
                #print(f"expr: {expr}, context: {context}")
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

            # Explicit source (label: or region:)
            if ':' in expr:
                source, key = expr.split(':', 1)
                if key.startswith(".") and current_label:
                    key = f"{current_label}.{key[1:]}"
                label, prop = key.rsplit('.', 1)
                if source == "label":
                    box = labels.get(label)
                    #print(f"label: {label}, box: {box}") 
                    if not box:
                        raise ValueError(f"Unknown label reference: {label}")
                elif source == "region":
                    box = context.get('regions', {}).get(label)
                    if not box:
                        raise ValueError(f"Unknown region reference: {label}")
                else:
                    raise ValueError(f"Unknown source prefix: {source}")
            else:
                # Implicit, default to labels then regions
                if expr.startswith(".") and current_label:
                    expr = f"{current_label}{expr}"
                label, prop = expr.rsplit('.', 1)
                box = labels.get(label)
                #print(f"label: {label}, box: {box}") 
                if not box and regions:
                    box = regions.get(label)
                if not box:
                    raise ValueError(f"Unknown reference: {expr}")

            val = None
            if prop == 'left': val = box['top_left'][0]
            elif prop == 'right': val = box['bottom_right'][0]
            elif prop == 'top': val = box['top_left'][1]
            elif prop == 'bottom': val = box['bottom_left'][1]
            elif prop == 'mid_y': val = (box['top_left'][1] + box['bottom_left'][1]) // 2
            else: raise ValueError(f"Unsupported property: {prop}")

            if self.debug:
                logger.debug(f"Resolved '{expr}' to {val}")
            return val

        if isinstance(expr, dict):
            if 'add' in expr:
                values = [self.evaluate_expression(v, labels, context, contours, current_label, regions) for v in expr['add']]
                result = sum(values)
                if self.debug:
                    logger.debug(f"add {values} = {result}")
                return result
            if 'subtract' in expr:
                values = [self.evaluate_expression(v, labels, context, contours, current_label, regions) for v in expr['subtract']]
                result = values[0] - sum(values[1:])
                if self.debug:
                    logger.debug(f"subtract {values} = {result}")
                return result
            if 'divide' in expr:
                a, b = [self.evaluate_expression(v, labels, context, contours, current_label, regions) for v in expr['divide']]
                result = a // b if isinstance(a, int) and isinstance(b, int) else a / b
                if self.debug:
                    logger.debug(f"divide {a} / {b} = {result}")
                return result
            if 'multiply' in expr:
                result = 1
                values = []
                for v in expr['multiply']:
                    val = self.evaluate_expression(v, labels, context, contours, current_label, regions)
                    values.append(val)
                    result *= val
                if self.debug:
                    logger.debug(f"multiply {values} = {result}")
                return result
            if 'midpoint' in expr:
                a, b = [self.evaluate_expression(v, labels, context, contours, current_label, regions) for v in expr['midpoint']]
                result = (a + b) // 2
                if self.debug:
                    logger.debug(f"midpoint of {a} and {b} = {result}")
                return result
            if 'distance' in expr:
                a, b = [self.evaluate_expression(v, labels, context, contours, current_label, regions) for v in expr['distance']]
                result = abs(a - b)
                if self.debug:
                    logger.debug(f"distance between {a} and {b} = {result}")
                return result
            if 'first_of' in expr:
                for key in expr['first_of']:
                    try:
                        result = self.evaluate_expression(key, labels, context, contours, current_label, regions)
                        if self.debug:
                            logger.debug(f"first_of picked {key} = {result}")
                        return result
                    except Exception:
                        continue
                raise ValueError(f"No valid option found in first_of: {expr['first_of']}")
            if 'contour_right_of' in expr and contours is not None:
                label, y_ref = expr['contour_right_of']
                y_value = self.evaluate_expression(y_ref, labels, context, contours, current_label, regions)
                label_box = labels[label]
                base_right = label_box['top_right'][0]
                max_right = base_right
                for cnt in contours:
                    x, y, w, h = cv2.boundingRect(cnt)
                    if y <= y_value <= y + h and x > base_right:
                        max_right = max(max_right, x + w)
                if self.debug:
                    logger.debug(f"contour_right_of for {label} at y={y_value} = {max_right}")
                return max_right
            if 'maximum_of' in expr:
                values = [self.evaluate_expression(v, labels, context, contours, current_label, regions) for v in expr['maximum_of']]
                result = max(values)
                if self.debug:
                    logger.debug(f"maximum_of {values} = {result}")
                return result
            if 'minimum_of' in expr:
                values = [self.evaluate_expression(v, labels, context, contours, current_label, regions) for v in expr['minimum_of']]
                result = min(values)
                if self.debug:
                    logger.debug(f"minimum_of {values} = {result}")
                return result

            raise ValueError(f"Unsupported expression: {expr}")

        raise TypeError(f"Unsupported type: {type(expr)}")


    def compute_regions(self, build_type, labels, contours=None):
        """
        Compute region bounding boxes based on the build type rules and label positions.

        This function evaluates expressions defined in the region detection rule set for
        a given build type to calculate the bounding boxes of regions. It processes both
        looped region definitions and explicit region definitions according to the specified
        rules.

        Args:
            build_type (str): The type of build, used to select the appropriate rule set from
                            ROI_DETECTION_RULES.
            labels (dict): A dictionary mapping label names to their bounding box coordinates.
            contours (list, optional): A list of contours that may be used in some region
                                    calculations, typically obtained from image preprocessing.

        Returns:
            dict: A dictionary mapping label names to their computed region bounding boxes. Each
                bounding box is represented as a dictionary with 'top_left' and 'bottom_right'
                coordinates.
        """
        rule = ROI_DETECTION_RULES.get(build_type)
        if not rule:
            logger.warning(f"No region rule found for build type: {build_type}")
            return {}

        context = {}
        context['regions'] = {}
        
        #print(f"labels: {labels}")  
        for var, expr in rule.get("variables", {}).items():
            #print(f"Computing variable '{var}'")
            try:
                context[var] = self.evaluate_expression(expr, labels, context, contours)
            except Exception as e:
                logger.warning(f"Failed to compute variable '{var}': {e}")

        regions = {}

        if 'regions_loops' in rule:
            for loop_cfg in rule['regions_loops']:
                for label in loop_cfg['labels']:
                    if label not in labels:
                        continue
                    logger.debug(f"Computing looped region for {label}")
                    #print(f"Computing looped region for {label}")
                    try:
                        defn = loop_cfg['loop']
                        
                        x1 = self.evaluate_expression(defn['x1'], labels, context, contours, current_label=label, regions=context['regions'])
                        x2 = self.evaluate_expression(defn['x2'], labels, context, contours, current_label=label, regions=context['regions'])
                        y1 = self.evaluate_expression(defn['y1'], labels, context, contours, current_label=label, regions=context['regions'])

                        h  = self.evaluate_expression(defn['height'], labels, context, contours, current_label=label, regions=context['regions'])
                        region_box = {
                            "top_left": [int(x1), int(y1)],
                            "bottom_right": [int(x2), int(y1 + h)]
                        }
                        context['regions'][label] = region_box
                        regions[label] = region_box
                    except Exception as e:
                        logger.warning(f"Failed to compute looped region for {label}: {e}")

        if 'regions' in rule:
            for entry in rule['regions']:
                if not isinstance(entry, dict) or len(entry) != 1:
                    logger.warning(f"Malformed region entry: {entry}")
                    continue
                label, defn = next(iter(entry.items()))
                if label not in labels:
                    continue
                try:
                    x1 = self.evaluate_expression(defn['x1'], labels, context, contours)
                    x2 = self.evaluate_expression(defn['x2'], labels, context, contours)
                    y1 = self.evaluate_expression(defn['y1'], labels, context, contours)
                    h  = self.evaluate_expression(defn['height'], labels, context, contours)
                    context['regions'][label] = {
                        "top_left": [int(x1), int(y1)],
                        "bottom_right": [int(x2), int(y1 + h)]
                    }
                except Exception as e:
                    logger.warning(f"Failed to compute region for {label}: {e}")

        return context['regions']

    def _draw_debug_regions(self, image, regions, output_path):
        """
        Draw labeled region rectangles on a copy of the original image and save as a debug visualization.

        Each region is drawn with a randomly colored bounding box and annotated with the label name.
        Used for visual verification of region detection accuracy.

        Args:
            image (np.array): Original BGR screenshot.
            regions (dict): Dictionary of label names to region and label bounding boxes.
            output_path (str): Path to save the annotated debug image.
        """
        debug_image = image.copy()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        for label, entry in regions.items():
            x1, y1 = entry["Region"]["top_left"]
            x2, y2 = entry["Region"]["bottom_right"]
            color = [random.randint(0, 255) for _ in range(3)]
            cv2.rectangle(debug_image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(debug_image, label, (x1 + 5, y1 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.imwrite(output_path, debug_image)
        logger.info(f"Wrote debug image to {output_path}")

 