import pytest
from sister_sto.exceptions import (
    SISTERError,
    StageError,
    ClassificationError,
    CargoError,
    CargoDownloadError,
    DomainError,
    HashIndexError,
    HashIndexNotFoundError,
    PHashError,
    SSIMError,
    ImageProcessingError,
    ImageNotFoundError
)

def test_sister_error_hierarchy():
    """Test that the exception hierarchy is correctly structured."""
    # Test base exception
    assert issubclass(SISTERError, Exception)
    
    # Test stage errors
    assert issubclass(StageError, SISTERError)
    assert issubclass(ClassificationError, StageError)
    
    # Test cargo errors
    assert issubclass(CargoError, SISTERError)
    assert issubclass(CargoDownloadError, CargoError)
    
    # Test domain errors
    assert issubclass(DomainError, SISTERError)
    assert issubclass(HashIndexError, DomainError)
    assert issubclass(HashIndexNotFoundError, HashIndexError)
    assert issubclass(PHashError, DomainError)
    assert issubclass(SSIMError, DomainError)
    assert issubclass(ImageProcessingError, DomainError)
    assert issubclass(ImageNotFoundError, ImageProcessingError)

def test_error_instantiation():
    """Test that all exceptions can be instantiated with messages."""
    exceptions = [
        SISTERError,
        StageError,
        ClassificationError,
        CargoError,
        CargoDownloadError,
        DomainError,
        HashIndexError,
        HashIndexNotFoundError,
        PHashError,
        SSIMError,
        ImageProcessingError,
        ImageNotFoundError
    ]
    
    for exception_class in exceptions:
        message = f"Test {exception_class.__name__}"
        exc = exception_class(message)
        assert str(exc) == message
        assert isinstance(exc, Exception)
        assert isinstance(exc, SISTERError)

def test_error_chaining():
    """Test that exceptions properly chain with cause."""
    try:
        try:
            raise ValueError("Original error")
        except ValueError as e:
            raise ImageProcessingError("Processing failed") from e
    except ImageProcessingError as e:
        assert isinstance(e.__cause__, ValueError)
        assert str(e.__cause__) == "Original error"
        assert str(e) == "Processing failed" 