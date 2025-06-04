import os
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import importlib.resources
import logging

logger = logging.getLogger(__name__)

def get_default_config_path() -> Optional[Path]:
    """Get the path to the default config file installed with the package."""
    try:
        # Try to get the config from package resources first
        resources_root = importlib.resources.files("sister_sto").joinpath("config/default.yaml")
        if resources_root.is_file():
            return resources_root
        
        # If not found in package resources, try the executable's directory (for frozen apps)
        if getattr(sys, "frozen", False):
            bundle_dir = Path(sys.executable).parent
            config_path = bundle_dir / "config" / "default.yaml"
            if config_path.is_file():
                return config_path
            
        # Finally try the source tree
        import sister_sto
        bundle_dir = Path(sister_sto.__file__).resolve().parent.parent
        config_path = bundle_dir / "config" / "default.yaml"
        if config_path.is_file():
            return config_path
            
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        pass
    
    return None

def get_user_config_dir() -> Path:
    """Get the user's config directory, creating it if it doesn't exist."""
    config_dir = Path(os.path.expanduser("~/.sister_sto/config"))
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def load_config(user_config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from multiple sources in order of precedence:
    1. User-specified config file (if provided)
    2. User config file in ~/.sister_sto/config/config.yaml
    3. Default config file installed with package
    
    Args:
        user_config_path: Optional path to a user config file
        
    Returns:
        Dict containing merged configuration
    """
    config = {}
    
    # Load default config first
    default_config_path = get_default_config_path()
    if default_config_path:
        try:
            with open(default_config_path) as f:
                config.update(yaml.safe_load(f) or {})
            logger.debug(f"Loaded default config from {default_config_path}")
        except Exception as e:
            logger.warning(f"Failed to load default config from {default_config_path}: {e}")
    
    # Load user config from standard location
    user_config_dir = get_user_config_dir()
    standard_user_config = user_config_dir / "config.yaml"
    if standard_user_config.is_file():
        try:
            with open(standard_user_config) as f:
                config.update(yaml.safe_load(f) or {})
            logger.debug(f"Loaded user config from {standard_user_config}")
        except Exception as e:
            logger.warning(f"Failed to load user config from {standard_user_config}: {e}")
    
    # Load user-specified config file
    if user_config_path:
        config_path = Path(user_config_path)
        if config_path.is_file():
            try:
                with open(config_path) as f:
                    config.update(yaml.safe_load(f) or {})
                logger.debug(f"Loaded config from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")

    
    return config 