import cv2
import numpy as np
import os
import random

import json

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
                    "x2": "col2_right",
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
            { "Hangar":      {"x1": {"add": ["warp_right", {"divide": ["padding", "2"]}]}, "x2": "col2_right", "y1": {"subtract": ["label:Hangar.bottom", "vertical_padding"]}, "height": "line_height"} }
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
    Detects Regions of Interest (ROIs) in Star Trek Online screenshots based on detected label positions
    and classified build types. Primarily focuses on narrowing search areas for icon detection.

    Attributes:
        debug (bool): If True, enables diagnostic image output.
    """

    def __init__(self, debug=False):
        """
        Initialize the RegionDetector.

        Args:
            debug (bool): Whether to enable debug output.
        """
        self.debug = debug

    def detect(self, screenshot_color, build_info, label_positions, debug_output_path=None):
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
        gray = self._preprocess_grayscale(screenshot_color)
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
            region_boxes = self.compute_regions(build_type, label_positions, contours)
        else:
            logger.warning(f"Unsupported build type: {build_type}")
            return {}


        merged = {}
        for label, region in region_boxes.items():
            label_box = label_positions[label]
            merged[label] = {
                "Label": {
                    key: [int(v[0]), int(v[1])] for key, v in label_box.items()
                },
                "Region": {
                    "top_left": [int(region["top_left"][0]), int(region["top_left"][1])],
                    "bottom_right": [int(region["bottom_right"][0]), int(region["bottom_right"][1])]
                }
            }

        if self.debug and debug_output_path:
            self._draw_debug_regions(screenshot_color, merged, debug_output_path)

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
        if self.debug:
            logger.debug(f"Evaluating expression: {expr} (current_label={current_label})")

        if isinstance(expr, (int, float)):
            return expr
        if isinstance(expr, str):
            if expr in context:
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
        
        for var, expr in rule.get("variables", {}).items():
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

    # Legacy methods - do not use, retained for correctness comparison, to be removed

    def _detect_pc_ship_rois(self, label_positions, contours):
        """
        Generate ROI regions for PC Ship Builds based on relative label geometry and right-side contours.

        For the "PC Ship Build" type, ROIs are calculated by extending horizontally from the right edge of known
        labels to the nearest right-side contours, and vertically between the midpoints of labels directly
        above and below. This reduces search space and focuses processing on expected component zones.

        Args:
            label_positions (dict): Output from LabelLocator.
            contours (list): Contours found in the preprocessed image.

        Returns:
            list: List of dictionaries with 'label' and 'rect': (x1, y1, x2, y2)
        """
        labels_to_find = [
            "Fore Weapon", "Aft Weapon", "Experimental Weapon", "Shield", "Secondary Deflector",
            "Deflector", "Impulse", "Warp", "Singularity", "Hangar", "Devices",
            "Universal Console", "Engineering Console", "Tactical Console", "Science Console"
        ]
        def midpoint_y(box):
            return (box["top_left"][1] + box["bottom_left"][1]) // 2

        for label in ["Deflector", "Fore Weapon"]:
            if label not in label_positions:
                logger.error("PC Ship Build requires {label} label for orientation calculation")
                return []

        def_y = midpoint_y(label_positions["Deflector"])
        fore_y = midpoint_y(label_positions["Fore Weapon"])

        lower_y = None
        for alt in ["Secondary Deflector", "Impulse"]:
            if alt in label_positions:
                lower_y = midpoint_y(label_positions[alt])
                break
        if lower_y is None:
            return []

        # Calculate bounding box height based on center spacing
        half_upper = abs(def_y - fore_y) // 2 - 1
        half_lower = abs(lower_y - def_y) // 2 - 1
        box_height = half_upper + half_lower
        
        # Use the Deflector box's right edge and the furthest contour to the right of it
        deflector_box = label_positions["Deflector"]
        def_right_x = deflector_box["top_right"][0]
        
        aligned_max_x = def_right_x + 1
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if y <= def_y <= y + h and x > def_right_x:
                aligned_max_x = max(aligned_max_x, x + w)

        region_boxes = {}

        for label in labels_to_find:
            if label not in label_positions:
                continue

            box = label_positions[label]
            mid_y = midpoint_y(box)
            top_y = mid_y - (box_height // 2)
            bottom_y = mid_y + (box_height // 2)

            region_boxes[label] = {
                "top_left": [int(def_right_x + 1), int(top_y)],
                "bottom_right": [int(aligned_max_x), int(bottom_y)]
            }

        return region_boxes

    def _detect_pc_ground_rois(self, label_positions):
        """
        Generate ROI regions for PC Ground Builds based on relative label geometry.

        Icon rows are typically aligned beneath the label. Padding is derived from horizontal spacing
        between the "Body" and "EV Suit" labels. Line height is estimated from vertical spacing 
        between "Body" and "Shield" labels.

        Args:
            label_positions (dict): Output from LabelLocator.

        Returns:
            dict: Mapping from component label to bounding box coordinates for region.
        """
        for label in ["Body", "EV Suit", "Shield"]:
            if label not in label_positions:
                logger.error(f"PC Ground Build requires {label} label for orientation calculation.")
                return {}

        body_box = label_positions["Body"]
        evsuit_box = label_positions["EV Suit"]
        shield_box = label_positions["Shield"]
        kit_box = label_positions["Kit"]
        kitmod_box = label_positions["Kit Modules"]
        weapon_box = label_positions["Weapon"]

        # Compute padding: 1/3 of the distance from Body right to EV Suit left
        padding = (evsuit_box["bottom_left"][0] - body_box["bottom_right"][0]) // 3

        # Compute line height: vertical spacing between Body bottom and Shields top minus padding
        line_height = (shield_box["top_left"][1] - body_box["bottom_left"][1]) - padding

        region_boxes = {}

        # Compute base icon row area under "Body"              
        body_top_y = body_box["bottom_left"][1] - padding
        body_bottom_y = body_top_y + line_height
        body_left_x = body_box["bottom_left"][0] - padding
        body_right_x = body_box["bottom_right"][0] + padding
        region_boxes["Body"] = {
            "top_left": [int(body_left_x), int(body_top_y)],
            "bottom_right": [int(body_right_x), int(body_bottom_y)]
        }

        # Now calculate an icon width
        icon_width = (body_right_x - body_left_x) #- padding
        
        # Generic handler for similar labels
        for label in ["EV Suit", "Shield", "Kit"]:
            if label not in label_positions:
                continue

            box = label_positions[label]
            top_y = box["bottom_left"][1] - padding
            bottom_y = top_y + line_height
            left_x = box["bottom_left"][0] - padding
            right_x = left_x + icon_width + padding  # additional padding rightwards

            region_boxes[label] = {
                "top_left": [int(left_x), int(top_y)],
                "bottom_right": [int(right_x), int(bottom_y)]
            }

        # Special case: Kit Modules
        if "Kit Modules" in label_positions and "Kit" in region_boxes:
            kit_region = region_boxes["Kit"]

            km_top_left = kitmod_box["bottom_left"]
            km_top_y = km_top_left[1] 
            km_left_x = km_top_left[0] - padding
            km_right_x = kit_region["bottom_right"][0]
            km_bottom_y = km_top_y + line_height

            region_boxes["Kit Modules"] = {
                "top_left": [int(km_left_x), int(km_top_y)],
                "bottom_right": [int(km_right_x), int(km_bottom_y)]
            }

        # Special case: Weapons (2 rows, stacked vertically with spacing)
        if "Weapon" in label_positions:
            top_y = weapon_box["bottom_left"][1] - padding
            left_x = weapon_box["bottom_left"][0] - padding
            right_x = left_x + icon_width
            total_height = (line_height * 2)

            region_boxes["Weapon"] = {
                "top_left": [int(left_x), int(top_y)],
                "bottom_right": [int(right_x), int(top_y + total_height)]
            }

        # Special case: Devices (2 columns × 3 rows grid)
        if "Devices" in label_positions:
            devices_box = label_positions["Devices"]
            top_y = devices_box["bottom_left"][1] - padding
            left_x = devices_box["bottom_left"][0] - padding
            right_x = left_x + (2 * icon_width) + padding
            bottom_y = top_y + (3 * line_height)

            region_boxes["Devices"] = {
                "top_left": [int(left_x), int(top_y)],
                "bottom_right": [int(right_x), int(bottom_y)]
            }
 
        return region_boxes

    def _detect_console_ship_rois(self, label_positions):
        """
        Generate ROI regions for Console Ship Builds based on relative label geometry.

        This layout has three columns:
        - Column 1 (Left): Stacked vertically: Fore Weapon, Aft Weapon, Experimental Weapon (optional), Devices
        - Column 2 (Center): Horizontal row: Shields, Deflector, Impulse, Warp/Singularity, Hangar (optional)
        - Column 3 (Right): Stacked vertically: Engineering Console, Tactical Console, Science Console, Universal Console (optional)

        Icon regions are placed *below* each label.

        Args:
            label_positions (dict): Label positions with bounding boxes.

        Returns:
            dict: Mapping from label to region bounding box.
        """
        for label in ["Fore Weapon", "Aft Weapon", "Engineering Console"]:
            if label not in label_positions:
                logger.error(f"Console Ship Build requires {label} label for orientation calculation.")
                return {}

        padding = 20
        vertical_padding = 5

        region_boxes = {}

        def bottom_y(label):
            return label_positions[label]["bottom_left"][1]

        def top_y(label):
            return label_positions[label]["top_left"][1]

        def left_x(label):
            return label_positions[label]["top_left"][0]

        def right_x(label):
            return label_positions[label]["top_right"][0]

        # Determine boundaries
        col1_left = left_x("Fore Weapon") - padding
        col3_right = right_x("Engineering Console") + padding

        col2_left = left_x("Shield") - padding if "Shield" in label_positions else None
        col2_right = None
        for fallback in ["Hangar", "Warp", "Singularity"]:
            if fallback in label_positions:
                col2_right = right_x(fallback) + padding
                break

        if col2_left is None or col2_right is None:
            logger.warning("Missing one or more central column bounds (Shield, Warp, Singularity, Hangar).")
            return {}

        col1_right = col2_left - padding
        col3_left = col2_right + padding

        # Calculate line height based on Fore/Aft Weapon
        line_height = top_y("Aft Weapon") - bottom_y("Fore Weapon") + vertical_padding

        # Column 1 labels
        col1_labels = ["Fore Weapon", "Aft Weapon", "Experimental Weapon", "Devices"]
        for i, label in enumerate(col1_labels):
            if label in label_positions:
                x1 = col1_left
                x2 = col1_right
                y1 = bottom_y(label) - vertical_padding
                y2 = y1 + line_height
                region_boxes[label] = {
                    "top_left": [int(x1), int(y1)],
                    "bottom_right": [int(x2), int(y2)]
                }

        # Column 3 labels
        col3_labels = ["Engineering Console", "Tactical Console", "Science Console", "Universal Console"]
        for i, label in enumerate(col3_labels):
            if label in label_positions:
                x2 = col3_right
                x1 = col3_left
                y1 = bottom_y(label) - vertical_padding
                y2 = y1 + line_height
                region_boxes[label] = {
                    "top_left": [int(x1), int(y1)],
                    "bottom_right": [int(x2), int(y2)]
                }

        # Column 2 labels (horizontal row, centered)
        if all(k in label_positions for k in ["Shield", "Deflector", "Impulse"]):
            shield_right = right_x("Shield")
            deflector_left = left_x("Deflector")
            deflector_right = right_x("Deflector")
            impulse_left = left_x("Impulse")
            impulse_right = right_x("Impulse")

            # Determine Warp/Singularity for Impulse to Warp/Singularity boundary
            warp_or_singularity = None
            for label in ["Warp", "Singularity"]:
                if label in label_positions:
                    warp_or_singularity = label
                    break

            if warp_or_singularity:
                warp_left = left_x(warp_or_singularity)
                warp_right = right_x(warp_or_singularity)

                # Shields
                x1 = col2_left
                x2 = (shield_right + deflector_left) // 2
                y1 = bottom_y("Shield") - vertical_padding
                y2 = y1 + line_height
                region_boxes["Shield"] = {
                    "top_left": [int(x1), int(y1)],
                    "bottom_right": [int(x2), int(y2)]
                }

                # Deflector
                x1 = (shield_right + deflector_left) // 2
                x2 = (deflector_right + left_x("Impulse")) // 2
                y1 = bottom_y("Deflector") - vertical_padding
                y2 = y1 + line_height
                region_boxes["Deflector"] = {
                    "top_left": [int(x1), int(y1)],
                    "bottom_right": [int(x2), int(y2)]
                }

                # Impulse
                x1 = (deflector_right + impulse_left) // 2
                x2 = (impulse_right + warp_left) // 2
                y1 = bottom_y("Impulse") - vertical_padding
                y2 = y1 + line_height
                region_boxes["Impulse"] = {
                    "top_left": [int(x1), int(y1)],
                    "bottom_right": [int(x2), int(y2)]
                }

                # Warp or Singularity
                x1 = (impulse_right + warp_left) // 2
                x2 = warp_right + (padding / 2)
                y1 = bottom_y(warp_or_singularity) - vertical_padding
                y2 = y1 + line_height
                region_boxes[warp_or_singularity] = {
                    "top_left": [int(x1), int(y1)],
                    "bottom_right": [int(x2), int(y2)]
                }

                # Hangar (optional)
                if "Hangar" in label_positions:
                    x2 = col2_right
                    x1 = warp_right + (padding / 2)
                    y1 = bottom_y("Hangar") - vertical_padding
                    y2 = y1 + line_height
                    region_boxes["Hangar"] = {
                        "top_left": [int(x1), int(y1)],
                        "bottom_right": [int(x2), int(y2)]
                    }
        return region_boxes
