from .locate_labels import LocateLabelsStage
from .classify_layout import ClassifyLayoutStage
from .crop_label_regions import CropLabelRegionsStage
from .locate_icon_groups import LocateIconGroupsStage
from .locate_icon_slots import LocateIconSlotsStage
from .prefilter_icons import PrefilterIconsStage
from .load_icons import LoadIconsStage
from .detect_icon_overlays import DetectIconOverlaysStage
from .detect_icons import DetectIconsStage
from .output_transform import OutputTransformationStage

__all__ = [
    "LocateLabelsStage",
    "ClassifyLayoutStage",
    "CropLabelRegionsStage",
    "LocateIconGroupsStage",
    "LocateIconSlotsStage",
    "PrefilterIconsStage",
    "LoadIconsStage",
    "DetectIconOverlaysStage",
    "DetectIconsStage",
    "OutputTransformationStage",
]
