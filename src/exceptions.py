from typing import Any

class SISTERError(Exception):
    """Base exception for all errors in the SISTER project."""
    pass

class PipelineError(SISTERError):
    """Raised when any stage of the pipeline fails.
    Carries the stage name, the original exception, and the PipelineContext.
    """
    def __init__(self, stage: str, original: Exception, ctx: Any):
        message = f"[{stage}] {original!r}"
        super().__init__(message)
        self.stage: str = stage
        self.original: Exception = original
        self.context: Any = ctx

class StageError(SISTERError):
    """Base class for errors occurring within individual pipeline stages."""
    pass

class LocatorError(StageError):
    """Raised when the label locator stage fails."""
    pass

class ClassificationError(StageError):
    """Raised when the classifier stage fails."""
    pass

class RegionDetectionError(StageError):
    """Raised when the region detector stage fails."""
    pass

class RegionDetectionComputeRegionError(RegionDetectionError):
    """Raised when the region detector stage fails with a compute_region error."""
    pass

class RegionDetectionExpressionParseError(RegionDetectionComputeRegionError):
    """Raised when the region detector stage fails with an expression parse error."""
    pass

class RegionDetectionExpressionEvaluationError(RegionDetectionComputeRegionError):
    """Raised when the region detector stage fails with an expression evaluation error."""
    pass

class IconSlotError(StageError):
    """Raised when the icon slot detection stage fails."""
    pass

class IconMatchError(StageError):
    """Raised when the icon matching stage fails."""
    pass

class PrefilterError(StageError):
    """Raised when the prefilter stage fails."""
    pass

class CargoError(StageError):
    """Raised when the cargo (asset loading) stage fails."""
    pass

class CargoCacheIOError(CargoError):
    """Raised when cargo cache I/O fails."""
    pass

class DomainError(SISTERError):
    """Base class for domain-specific or utility errors."""
    pass

class HashIndexError(DomainError):
    """Raised for failures in the hash index subsystem."""
    pass

class HashIndexNotFoundError(HashIndexError):
    """Raised when the hash index file cannot be found."""
    pass

class PHashError(DomainError):
    """Raised for failures in perceptual hashing operations."""
    pass

class SSIMError(DomainError):
    """Raised for failures in SSIM-based matching or quality checks."""
    pass

class ImageProcessingError(DomainError):
    """Raised for general image I/O or processing failures."""
    pass


__all__ = [
    "SISTERError",
    "PipelineError",
    "StageError",

    "CargoError",
    "LocatorError",
    "ClassificationError",
    "RegionDetectionError",
    "RegionDetectionComputeRegionError",
    "RegionDetectionExpressionParseError",
    "RegionDetectionExpressionEvaluationError",
    "IconSlotError",
    "PrefilterError",    
    "IconMatchError",
    "PrefilterError",
    "CargoError",
    "DomainError",
    "HashIndexError",
    "PHashError",
    "SSIMError",
    "ImageProcessingError",
    
]