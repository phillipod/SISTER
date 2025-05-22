from typing import Any


class SISTERError(Exception):
    """Base exception for all errors in the SISTER project."""

    pass


class PipelineError(SISTERError):
    """Raised when any stage of the pipeline fails.
    Carries the stage name, the original exception, and the PipelineState.
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


class IconGroupLocatorError(StageError):
    """Raised when the icon group locator stage fails."""

    pass


class IconGroupLocatorComputeIconGroupError(IconGroupLocatorError):
    """Raised when the icon group locator stage fails with a compute_region error."""

    pass


class IconGroupLocatorExpressionParseError(IconGroupLocatorComputeIconGroupError):
    """Raised when the icon group locator stage fails with an expression parse error."""

    pass


class IconGroupLocatorExpressionEvaluationError(IconGroupLocatorComputeIconGroupError):
    """Raised when the icon group locator stage fails with an expression evaluation error."""

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


class CargoDownloadError(CargoError):
    """Raised when cargo cache download fails."""

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


class ImageNotFoundError(ImageProcessingError):
    """Raised when an image cannot be found."""

    pass


__all__ = [
    "SISTERError",
    "PipelineError",
    "StageError",
    "CargoError",
    "LocatorError",
    "ClassificationError",
    "IconGroupLocatorError",
    "IconGroupLocatorComputeIconGroupError",
    "IconGroupLocatorExpressionParseError",
    "IconGroupLocatorExpressionEvaluationError",
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
