import pytest
import logging
import os
import time
from pathlib import Path
from sister_sto.log_config import (
    setup_console_logging,
    setup_file_logging,
    VERBOSE_LEVEL_NUM,
    SuppressDebugFromIconMatch,
    SuppressDebugFromRegionDetector
)
from logging.handlers import RotatingFileHandler
from tqdm.contrib.logging import _TqdmLoggingHandler

def get_our_handlers(logger):
    """Helper to get only our specific handlers."""
    return [h for h in logger.handlers if isinstance(h, (RotatingFileHandler, _TqdmLoggingHandler))]

@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration before each test."""
    root = logging.getLogger()
    root.setLevel(logging.NOTSET)  # Reset level
    # Remove only our handlers (RotatingFileHandler and TqdmLoggingHandler), leave pytest's handlers alone
    for handler in root.handlers[:]:
        if isinstance(handler, (RotatingFileHandler, _TqdmLoggingHandler)):
            handler.close()
            root.removeHandler(handler)
    yield
    # Clean up after test
    for handler in root.handlers[:]:
        if isinstance(handler, (RotatingFileHandler, _TqdmLoggingHandler)):
            handler.close()
            root.removeHandler(handler)

@pytest.fixture
def temp_log_dir(tmp_path):
    """Create a temporary directory for log files."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir

def test_setup_logging(temp_log_dir):
    """Test basic logging setup."""
    log_file = str(temp_log_dir / "test.log")
    
    # Ensure no handlers exist before setup
    root_logger = logging.getLogger()
    our_handlers = get_our_handlers(root_logger)
    assert len(our_handlers) == 0, "Root logger should have no sister_sto handlers"
    
    # Set up both console and file logging
    setup_console_logging(log_level="INFO")
    setup_file_logging(log_file=log_file, log_level="INFO")
    
    # Verify handlers are set up correctly
    our_handlers = get_our_handlers(root_logger)
    console_handlers = [h for h in our_handlers if isinstance(h, _TqdmLoggingHandler)]
    file_handlers = [h for h in our_handlers if isinstance(h, RotatingFileHandler)]
    assert len(console_handlers) > 0, "No console handler found"
    assert len(file_handlers) > 0, "No RotatingFileHandler found"
    
    # Test message
    logger = logging.getLogger("sister_sto")
    logger.info("Test setup message")
    
    # Force flush and close handlers
    for handler in our_handlers:
        handler.flush()
        if isinstance(handler, RotatingFileHandler):
            handler.close()
    
    # Verify file exists and has content
    assert os.path.exists(log_file), f"Log file {log_file} does not exist"
    with open(log_file, 'r') as f:
        log_contents = f.read()
        assert "Test setup message" in log_contents
        assert "[INFO]" in log_contents

def test_verbose_level():
    """Test custom verbose log level."""
    assert VERBOSE_LEVEL_NUM == 15
    assert logging.getLevelName(VERBOSE_LEVEL_NUM) == "VERBOSE"

def test_logging_levels(temp_log_dir):
    """Test different logging levels."""
    log_file = str(temp_log_dir / "test.log")
    
    # Ensure no handlers exist before setup
    root_logger = logging.getLogger()
    our_handlers = get_our_handlers(root_logger)
    assert len(our_handlers) == 0, "Root logger should have no sister_sto handlers"
    
    # Set up both console and file logging with DEBUG level
    setup_console_logging(log_level="DEBUG")
    setup_file_logging(log_file=log_file, log_level="DEBUG")
    
    # Verify handlers are set up correctly
    our_handlers = get_our_handlers(root_logger)
    console_handlers = [h for h in our_handlers if isinstance(h, _TqdmLoggingHandler)]
    file_handlers = [h for h in our_handlers if isinstance(h, RotatingFileHandler)]
    assert len(console_handlers) > 0, "No console handler found"
    assert len(file_handlers) > 0, "No RotatingFileHandler found"
    
    # Test messages
    logger = logging.getLogger("test_levels")
    logger.setLevel(logging.DEBUG)
    
    test_message = "Test message"
    logger.debug(test_message)
    logger.info(test_message)
    logger.warning(test_message)
    logger.error(test_message)
    
    # Force flush and close handlers
    for handler in our_handlers:
        handler.flush()
        if isinstance(handler, RotatingFileHandler):
            handler.close()
    
    # Verify file exists and has content
    assert os.path.exists(log_file), f"Log file {log_file} does not exist"
    with open(log_file, 'r') as f:
        log_contents = f.read()
        assert "DEBUG" in log_contents
        assert "INFO" in log_contents
        assert "WARNING" in log_contents
        assert "ERROR" in log_contents

def test_suppress_debug_filters():
    """Test debug suppression filters."""
    icon_match_filter = SuppressDebugFromIconMatch(allow_debug=False)
    region_filter = SuppressDebugFromRegionDetector(allow_debug=False)
    
    # Create test records
    debug_record = logging.LogRecord(
        "src.iconmatch", logging.DEBUG, "", 0, "test message", (), None
    )
    info_record = logging.LogRecord(
        "src.iconmatch", logging.INFO, "", 0, "test message", (), None
    )
    
    # Test filters
    assert not icon_match_filter.filter(debug_record)  # Should suppress debug
    assert icon_match_filter.filter(info_record)  # Should allow info
    
    # Test with debug allowed
    icon_match_filter = SuppressDebugFromIconMatch(allow_debug=True)
    assert icon_match_filter.filter(debug_record)  # Should allow debug when enabled 