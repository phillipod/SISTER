import pytest
from pathlib import Path
from sister_sto.utils.config import get_default_config_path, get_user_config_dir, load_config
import tempfile
import yaml
import os

def test_get_user_config_dir(tmp_path, monkeypatch):
    """Test that get_user_config_dir creates and returns the correct directory."""
    # Mock home directory to use a temporary directory
    monkeypatch.setenv('HOME', str(tmp_path))
    
    config_dir = get_user_config_dir()
    
    assert config_dir.exists()
    assert config_dir.is_dir()
    # Use parts to check path components in an OS-independent way
    assert config_dir.parts[-2:] == ('.sister_sto', 'config')

def test_load_config_empty():
    """Test loading config with no config files present."""
    config = load_config()
    assert isinstance(config, dict)

def test_load_config_with_user_file(tmp_path):
    """Test loading config with a user-specified config file."""
    # Create a temporary config file
    user_config = {
        'test_key': 'test_value',
        'nested': {
            'key': 'value'
        }
    }
    
    config_path = tmp_path / 'test_config.yaml'
    with open(config_path, 'w') as f:
        yaml.dump(user_config, f)
    
    # Load the config
    config = load_config(str(config_path))
    
    assert config.get('test_key') == 'test_value'
    assert config.get('nested', {}).get('key') == 'value'

def test_load_config_precedence(tmp_path, monkeypatch):
    """Test that config loading follows the correct precedence order."""
    # Mock home directory and set up environment
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr('sister_sto.utils.config.get_default_config_path', lambda: default_dir / 'default.yaml')
    
    # Create default config
    default_config = {'key': 'default', 'unique_default': 'value'}
    default_dir = tmp_path / '.sister_sto' / 'config'
    default_dir.mkdir(parents=True)
    with open(default_dir / 'default.yaml', 'w') as f:
        yaml.dump(default_config, f)
    
    # Create user config
    user_config = {'key': 'user', 'unique_user': 'value'}
    user_config_path = tmp_path / 'user_config.yaml'
    with open(user_config_path, 'w') as f:
        yaml.dump(user_config, f)
    
    # Load config with user file
    config = load_config(str(user_config_path))
    
    # User config should override default
    assert config['key'] == 'user'
    # Both configs should be merged
    assert 'unique_default' in config
    assert 'unique_user' in config 