import logging
from logging.handlers import RotatingFileHandler
from tqdm.contrib.logging import _TqdmLoggingHandler 

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

def setup_logging(log_level="INFO", log_file="log/sister.log", allow_iconmatch_debug=False, allow_region_detector_debug=False):
    """
    Set up logging configuration with console and file handlers.

    Args:
        log_level (str): Minimum log level to capture (e.g., 'DEBUG', 'INFO').
        log_file (str): File path to write log output.
    """
    if isinstance(log_level, str):
        if log_level.upper() == "VERBOSE":
            log_level = VERBOSE_LEVEL_NUM
        else:
            log_level = getattr(logging, log_level.upper(), logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console = _TqdmLoggingHandler()
    console.setFormatter(formatter)
    console.setLevel(log_level)

    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    logging.basicConfig(level=log_level, handlers=[console, file_handler])

    console.addFilter(SuppressDebugFromIconMatch(allow_iconmatch_debug))
    file_handler.addFilter(SuppressDebugFromIconMatch(allow_iconmatch_debug))

    console.addFilter(SuppressDebugFromRegionDetector(allow_region_detector_debug))
    file_handler.addFilter(SuppressDebugFromRegionDetector(allow_region_detector_debug))