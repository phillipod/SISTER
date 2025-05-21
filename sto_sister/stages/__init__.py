from .label_locator import LabelLocatorStage
from .classifier import ClassifierStage
from .region_detection import RegionDetectionStage
from .icon_slot_detection import IconSlotDetectionStage
from .icon_prefilter import IconPrefilterStage
from .icon_quality_detection import IconMatchingQualityDetectionStage
from .icon_matching import IconMatchingStage
from .output_transform import OutputTransformationStage

__all__ = ["LabelLocatorStage", "ClassifierStage", "RegionDetectionStage", "IconSlotDetectionStage", "IconPrefilterStage", "IconMatchingQualityDetectionStage", "IconMatchingStage", "OutputTransformationStage"]