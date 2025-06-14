import logging
import numpy as np
from typing import Any, Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

SCORING_RULES = {
    "PC Ship Build": {
        "excluded": ["Kit"],
        "presence": {
            "labels": [
                "Fore Weapon",
                "Deflector",
                "Impulse",
                "Warp",
                "Shield",
                "Aft Weapon",
                "Engineering Console",
                "Science Console",
                "Tactical Console",
            ],
            "score": 10,
        },
        "conditions": [
            {
                "type": "vertical_stack",
                "labels": ["Fore Weapon", "Deflector", "Impulse"],
                "align": "right",
                "score": 50,
            },
            {
                "type": "labels_vertically_between",
                "label1": "Fore Weapon",
                "label2": "Aft Weapon",
                "group": ["Deflector", "Impulse", "Warp"],
                "score": 70,
            },
            {
                "type": "horizontal_alignment",
                "labels": [
                    "Engineering Console",
                    "Science Console",
                    "Tactical Console",
                ],
                "score": 20,
            },
            {
                "type": "is_left_of",
                "left": "Fore Weapon",
                "right": "Aft Weapon",
                "score": 10,
            },
        ],
    },
    "PC Ground Build": {
        "excluded": ["Kit Frame", "Deflector"],
        "presence": {"labels": ["Kit", "Body", "Shield", "Weapon"], "score": 10},
        "bonuses": [{"label": "Kit Module", "score": 20}],
        "conditions": [
            {
                "type": "vertical_stack",
                "labels": ["Kit", "Body", "Shield", "Weapon"],
                "align": "left",
                "score": 50,
            },
            {
                "type": "horizontal_alignment",
                "labels": ["Body", "Shield", "Weapon"],
                "score": 10,
            },
        ],
    },
    "Console Ground Build": {
        "required": ["Kit Frame"],
        "presence": {"labels": ["Kit Frame", "Body", "Shield", "Weapon"], "score": 10},
        "conditions": [
            {
                "type": "vertical_stack",
                "labels": ["Kit Frame", "Body", "Shield", "Weapon"],
                "align": "left",
                "score": 50,
            },
            {"type": "is_left_of", "left": "Weapon", "right": "Devices", "score": 30},
            {
                "type": "horizontal_alignment",
                "labels": ["Body", "Shield", "Weapon"],
                "score": 30,
            },
        ],
    },
    "Console Ship Build": {
        "excluded": ["Kit"],
        "presence": {
            "labels": [
                "Fore Weapon",
                "Aft Weapon",
                "Devices",
                "Engineering Console",
                "Science Console",
                "Tactical Console",
            ],
            "score": 10,
        },
        "conditions": [
            {
                "type": "vertical_stack",
                "labels": ["Fore Weapon", "Aft Weapon", "Devices"],
                "align": "left",
                "score": 50,
            },
            {
                "type": "vertical_stack",
                "labels": [
                    "Engineering Console",
                    "Science Console",
                    "Tactical Console",
                ],
                "align": "right",
                "score": 50,
            },
            {
                "type": "is_left_of",
                "left": "Fore Weapon",
                "right": "Engineering Console",
                "score": 10,
            },
            {
                "type": "labels_vertically_between",
                "label1": "Fore Weapon",
                "label2": "Aft Weapon",
                "group": [
                    "Devices",
                    "Engineering Console",
                    "Science Console",
                    "Tactical Console",
                ],
                "score": -70,
            },
        ],
    },

    "Personal Ground Traits": {
        "presence": {"labels": ["Personal Ground Traits"], "score": 10},
        "trait_box": True,
    },

    "Personal Space Traits": {
        "presence": {"labels": ["Personal Space Traits"], "score": 10},
        "trait_box": True,
    },

    "Starship Traits": {
        "presence": {"labels": ["Starship Traits"], "score": 10},
        "trait_box": True,
    },

    "Space Reputation": {
        "presence": {"labels": ["Space Reputation"], "score": 10},
        "trait_box": True,
    },

    "Ground Reputation": {
        "presence": {"labels": ["Ground Reputation"], "score": 10},
        "trait_box": True,
    },

    "Active Space Reputation": {
        "presence": {"labels": ["Active Space Reputation"], "score": 10},
        "trait_box": True,
    },

    "Active Ground Reputation": {
        "presence": {"labels": ["Active Ground Reputation"], "score": 10},
        "trait_box": True,
    },
}


class LayoutClassifier:
    """
    Pipeline-aware classifier: Determines the likely build type of a Star Trek Online character screenshot using spatial and textual label analysis.

    This classifier uses label data generated by the LabelLocator class to score a given screenshot as one of the following:
        - PC Ship Build
        - PC Ground Build
        - Console Ship Build
        - Console Ground Build
        - SETS Ship Build
        - SETS Ground Build

    Scores are based on the presence and layout of specific label types (e.g., "Fore Weapon", "Kit Frame", etc.).
    Rules include label presence, vertical or horizontal alignment, and relative spatial positioning (e.g. label A is left of label B).

    Attributes:
        VERTICAL_TOLERANCE (int): Pixel threshold for vertical alignment.
        HORIZONTAL_TOLERANCE (int): Pixel threshold for horizontal alignment.
        debug (bool): If True, enables verbose debug logging.
    """

    VERTICAL_TOLERANCE = 20
    HORIZONTAL_TOLERANCE = 20

    def __init__(
        self, config: Optional[Dict[str, Any]] = None, debug: bool = False
    ) -> None:
        """
        Initialize the BuildClassifier.

        Args:
            debug (bool): Whether to enable debug output.
        """
        self.config: Dict[str, Any] = config or {}
        self.debug = debug

    def classify(self, label_positions: np.ndarray) -> Dict[str, Any]:
        """
        Classify the build type based on detected label positions.

        Args:
            label_positions (dict): Mapping of label names to bounding box coordinates.

        Returns:
            dict: A dictionary with the most likely build type and its score.
        """

        results: Dict[str, Dict[str, Any]] = {}
        
        for build_type, rules in SCORING_RULES.items():
            score, is_required = self._score_with_rules(label_positions, rules, build_type)
            
            if score > 0:
                results[build_type] = {"score": score, "is_required": is_required}

        logger.info("Scoring breakdown:")
        
        for build_type, info in results.items():
            logger.info(f"  {build_type}: score={info['score']}, is_required={info['is_required']}")

        return results


    def _score_with_rules(
        self,
        labels: Dict[str, Tuple[int, int, int, int]],
        rule_set: Any,
        build_type: str,
    ) -> float:
        # Enforce required labels
        """
        Scores a given build type based on the presence of required and excluded labels,
        label presence, and spatial conditions.

        Args:
            labels (dict): Mapping of label names to bounding box coordinates.
            rule_set (dict): A dictionary describing the rules for the given build type.
            build_type (str): The name of the build type being scored.

        Returns:
            int: The total score for the given build type.
        """
        if "required" in rule_set:
            for req_label in rule_set["required"]:
                if req_label not in labels:
                    logger.info(
                        f"Disqualified '{build_type}': missing required label '{req_label}'"
                    )
                    return 0, False

        # Enforce excluded labels
        if "excluded" in rule_set:
            for excl_label in rule_set["excluded"]:
                if excl_label in labels:
                    logger.info(
                        f"Disqualified '{build_type}': found excluded label '{excl_label}'"
                    )
                    return 0, False

        score = 0
        is_required = False

        if "presence" in rule_set:
            presence = rule_set["presence"]
            presence_score = sum(
                presence.get("score", 10)
                for label in presence["labels"]
                if label in labels
            )
            score += presence_score
            logger.debug(f"Presence score: {presence_score}")

        if 'trait_box' in rule_set and rule_set['trait_box'] is True:
            is_required = True

        for bonus in rule_set.get("bonuses", []):
            if bonus["label"] in labels:
                score += bonus["score"]
                logger.debug(f"Bonus for {bonus['label']}: +{bonus['score']}")

        for cond in rule_set.get("conditions", []):
            if cond["type"] == "vertical_stack":
                if self._check_vertical_stack(
                    labels, cond["labels"], align=cond.get("align", "left")
                ):
                    score += cond["score"]
                    logger.debug(f"Vertical stack matched: +{cond['score']}")

            elif cond["type"] == "labels_vertically_between":
                if self._labels_vertically_between(
                    labels, cond["label1"], cond["label2"], cond["group"]
                ):
                    score += cond["score"]
                    logger.debug(f"Labels vertically between matched: +{cond['score']}")

            elif cond["type"] == "is_left_of":
                if self._is_left_of(labels, cond["left"], cond["right"]):
                    score += cond["score"]
                    logger.debug(f"Left-of condition matched: +{cond['score']}")

            elif cond["type"] == "horizontal_alignment":
                if self._check_horizontal_alignment(labels, cond["labels"]):
                    score += cond["score"]
                    logger.debug(f"Horizontal alignment matched: +{cond['score']}")

        return score, is_required

    def _check_vertical_stack(
        self,
        labels: Dict[str, Tuple[int, int, int, int]],
        required_labels: List[str],
        align: str = "left",
    ) -> bool:
        """
        Check whether a sequence of labels are vertically stacked and aligned.

        Args:
            labels (dict): Label name to position mappings.
            required_labels (list): List of labels expected to be in a vertical stack.
            align (str): Either 'left' or 'right', to determine alignment edge.

        Returns:
            bool: True if labels are vertically aligned and ordered top-to-bottom.
        """
        coords = []
        for label in required_labels:
            if label not in labels:
                logger.debug(f"Vertical stack: Missing label '{label}'")
                return False
            coords.append(
                labels[label]["top_left"]
                if align == "left"
                else labels[label]["top_right"]
            )

        coords_sorted = sorted(coords, key=lambda p: p[1])

        for i in range(len(coords_sorted) - 1):
            x1, y1 = coords_sorted[i]
            x2, y2 = coords_sorted[i + 1]
            logger.debug(f"Vertical stack check: ({x1},{y1}) to ({x2},{y2})")
            if abs(x1 - x2) > self.VERTICAL_TOLERANCE:
                logger.debug(
                    f"Vertical stack: X-alignment failed with diff {abs(x1 - x2)}"
                )
                return False
            if y2 <= y1:
                logger.debug(f"Vertical stack: Y-ordering failed with y1={y1}, y2={y2}")
                return False

        return True

    def _check_horizontal_alignment(
        self, labels: Dict[str, Tuple[int, int, int, int]], required_labels: List[str]
    ) -> bool:
        """
        Check whether a group of labels are horizontally aligned.

        Args:
            labels (dict): Label name to position mappings.
            required_labels (list): List of labels expected to be horizontally aligned.

        Returns:
            bool: True if labels are horizontally aligned.
        """
        coords = []
        for label in required_labels:
            if label not in labels:
                return False
            coords.append(labels[label]["top_left"])
        coords_sorted = sorted(coords, key=lambda p: p[0])
        for i in range(len(coords_sorted) - 1):
            x1, y1 = coords_sorted[i]
            x2, y2 = coords_sorted[i + 1]
            if abs(y1 - y2) > self.HORIZONTAL_TOLERANCE:
                return False
        return True

    def _is_left_of(
        self,
        labels: Dict[str, Tuple[int, int, int, int]],
        left_label: str,
        right_label: str,
    ) -> bool:
        """
        Determine whether one label is positioned to the left of another.

        Args:
            labels (dict): Label name to position mappings.
            left_label (str): Name of the label expected to be on the left.
            right_label (str): Name of the label expected to be on the right.

        Returns:
            bool: True if left_label is to the left of right_label.
        """
        if left_label not in labels or right_label not in labels:
            return False
        return labels[left_label]["top_left"][0] < labels[right_label]["top_left"][0]

    def _labels_vertically_between(
        self,
        labels: Dict[str, Tuple[int, int, int, int]],
        label1: str,
        label2: str,
        group: List[str],
    ) -> List[str]:
        """
        Check if there are labels from a group vertically between two other labels,
        and if they are also aligned in X position.

        Args:
            labels (dict): Label name to position mappings.
            label1 (str): One of the bounding labels (e.g., top).
            label2 (str): The other bounding label (e.g., bottom).
            group (list): List of candidate labels to check between the bounds.

        Returns:
            bool: True if any group labels are vertically between and aligned.
        """
        if label1 not in labels or label2 not in labels:
            logger.debug(
                f"Missing label(s) in _labels_vertically_between: {label1}, {label2}"
            )
            return False

        y1 = labels[label1]["top_left"][1]
        y2 = labels[label2]["top_left"][1]
        x1 = labels[label1]["top_left"][0]
        x2 = labels[label2]["top_left"][0]

        top_y = min(y1, y2)
        bottom_y = max(y1, y2)

        intervening = [
            label
            for label in group
            if label not in (label1, label2)
            and label in labels
            and top_y < labels[label]["top_left"][1] < bottom_y
            and abs(labels[label]["top_left"][0] - x1) <= self.VERTICAL_TOLERANCE
            and abs(labels[label]["top_left"][0] - x2) <= self.VERTICAL_TOLERANCE
        ]

        logger.debug(
            f"_labels_vertically_between: {label1} @ ({x1},{y1}), {label2} @ ({x2},{y2})"
        )
        logger.debug(
            f"Between {top_y} and {bottom_y}, found {len(intervening)} vertically aligned labels: {intervening}"
        )

        return len(intervening) > 0

    # Legacy methods - do not use, for correctness comparisons only, to be removed in the future

    def _score_sets_ship_build(self, labels):
        """
        Compute the score for a SETS Ship Build based on known label positions.

        Args:
            labels (dict): Detected labels and their bounding boxes.

        Returns:
            int: Score representing the confidence of this build type.
        """
        score = 0
        sets_labels = [k for k in labels if k.startswith("SETS")]
        score += 100 * len(sets_labels)
        logger.debug(f"SETS Ship Build: SETS label bonus {100 * len(sets_labels)}")

        required = ["Fore Weapon", "Aft Weapon"]
        presence_score = sum(10 for label in required if label in labels)
        score += presence_score
        logger.debug(f"SETS Ship Build: Presence score {presence_score}")
        if self._check_vertical_stack(labels, required, align="left"):
            score += 50
            logger.debug("SETS Ship Build: Vertical stack matched")
        return score

    def _score_sets_ground_build(self, labels):
        """
        Compute the score for a SETS Ground Build based on known label positions.

        Args:
            labels (dict): Detected labels and their bounding boxes.

        Returns:
            int: Score representing the confidence of this build type.
        """
        score = 0
        sets_labels = [k for k in labels if k.startswith("SETS")]
        score += 100 * len(sets_labels)
        logger.debug(f"SETS Ground Build: SETS label bonus {100 * len(sets_labels)}")

        required = ["Kit Module", "Weapon"]
        presence_score = sum(10 for label in required if label in labels)
        score += presence_score
        logger.debug(f"SETS Ground Build: Presence score {presence_score}")
        if self._check_vertical_stack(labels, required, align="left"):
            score += 50
            logger.debug("SETS Ground Build: Vertical stack matched")
        if self._is_left_of(labels, "Kit Module", "Kit Frame"):
            score += 30
            logger.debug("SETS Ground Build: Kit Module is left of Kit Frame")
        if self._check_horizontal_alignment(labels, ["Kit Module", "Kit Frame"]):
            score += 30
            logger.debug("SETS Ground Build: Horizontal alignment matched")
        return score
