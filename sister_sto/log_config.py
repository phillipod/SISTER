import logging
from logging.handlers import RotatingFileHandler
from tqdm.contrib.logging import _TqdmLoggingHandler 
import sys

class SuppressDebugFromIconMatch(logging.Filter):
    def __init__(self, allow_debug=False):
        super().__init__()
        self.allow_debug = allow_debug

    def filter(self, record):
        if record.name.startswith("src.iconmatch") and record.levelno == logging.DEBUG:
            return self.allow_debug
        return True  # allow everything else

class SuppressDebugFromRegionDetector(logging.Filter):
    def __init__(self, allow_debug=False):
        super().__init__()
        self.allow_debug = allow_debug

    def filter(self, record):
        if record.name.startswith("src.region") and record.levelno == logging.DEBUG:
            return self.allow_debug
        return True  # allow everything else

# --- Custom log level: VERBOSE ---
VERBOSE_LEVEL_NUM = 15
logging.addLevelName(VERBOSE_LEVEL_NUM, "VERBOSE")

def verbose(self, message, *args, **kwargs):
    if self.isEnabledFor(VERBOSE_LEVEL_NUM):
        self._log(VERBOSE_LEVEL_NUM, message, args, **kwargs)

logging.Logger.verbose = verbose

def get_log_level(level_str: str) -> int:
    """Convert string log level to numeric value, handling VERBOSE case."""
    if level_str.upper() == "VERBOSE":
        return VERBOSE_LEVEL_NUM
    return getattr(logging, level_str.upper(), logging.INFO)

def setup_console_logging(log_level="INFO"):
    """Set up basic console logging with tqdm-compatible handler."""
    root_logger = logging.getLogger()
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create and add console handler
    console = _TqdmLoggingHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                                datefmt='%Y-%m-%d %H:%M:%S')
    console.setFormatter(formatter)
    
    # Set levels
    level = get_log_level(log_level)
    root_logger.setLevel(level)
    console.setLevel(level)
    
    root_logger.addHandler(console)
    return console

def setup_file_logging(log_file, log_level="INFO", allow_iconmatch_debug=False, allow_region_detector_debug=False):
    """Add rotating file handler to root logger and configure filters."""
    root_logger = logging.getLogger()
    level = get_log_level(log_level)
    
    # Create and configure file handler
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                                datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    
    # Add filters
    file_handler.addFilter(SuppressDebugFromIconMatch(allow_iconmatch_debug))
    file_handler.addFilter(SuppressDebugFromRegionDetector(allow_region_detector_debug))
    
    root_logger.addHandler(file_handler)
    return file_handler

def set_log_level(level):
    """Adjust the log level of all handlers."""
    level = get_log_level(level) if isinstance(level, str) else level
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)