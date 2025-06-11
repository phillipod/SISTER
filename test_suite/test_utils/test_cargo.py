import pytest
from pathlib import Path
from sister_sto.utils.cargo import CargoDownloader
import tempfile
import json

@pytest.fixture
def cargo_downloader(tmp_path):
    """Create a CargoDownloader instance with a temporary cache directory."""
    return CargoDownloader(cargo_dir=tmp_path)

def test_cargo_downloader_init(cargo_downloader, tmp_path):
    """Test CargoDownloader initialization."""
    assert cargo_downloader.cache_dir == tmp_path
    assert not cargo_downloader.force_download
    assert cargo_downloader.cache_dir.exists()

def test_build_url(cargo_downloader):
    """Test URL construction for cargo queries."""
    # Test URL for equipment type
    url = cargo_downloader.build_url('equipment')
    assert 'tables=' in url
    assert 'fields=' in url
    assert 'limit=' in url
    assert 'offset=0' in url
    assert 'format=json' in url
    
    # Test URL with offset
    url_with_offset = cargo_downloader.build_url('equipment', offset=100)
    assert 'offset=100' in url_with_offset

def test_cache_file(cargo_downloader):
    """Test cache file path generation."""
    cache_path = cargo_downloader.cache_file('equipment')
    assert isinstance(cache_path, Path)
    assert str(cache_path).endswith('equipment.json')
    assert cache_path.parent == cargo_downloader.cache_dir

@pytest.mark.parametrize('cargo_type', ['equipment'])
def test_cache_file_creation(cargo_downloader, cargo_type):
    """Test that cache files are created in the correct location."""
    cache_path = cargo_downloader.cache_file(cargo_type)
    
    # Create a dummy cache file
    test_data = {'test': 'data'}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, 'w') as f:
        json.dump(test_data, f)
    
    assert cache_path.exists()
    assert cache_path.is_file()
    
    # Verify content
    with open(cache_path) as f:
        loaded_data = json.load(f)
    assert loaded_data == test_data 