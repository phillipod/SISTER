from .locate_labels import LocateLabelsStage
from .classify_layout import ClassifyLayoutStage
from .locate_icon_groups import LocateIconGroupsStage
from .locate_icon_slots import LocateIconSlotsStage
from .icon_prefiltering import IconPrefilteringStage
from .detect_icon_overlays import DetectIconOverlaysStage
from .detect_icons import DetectIconsStage
from .output_transform import OutputTransformationStage

__all__ = [
    "LocateLabelsStage",
    "ClassifyLayoutStage",
    "LocateIconGroupsStage",
    "LocateIconSlotsStage",
    "IconPrefilteringStage",
    "DetectIconOverlaysStage",
    "DetectIconsStage",
    "OutputTransformationStage",
]
