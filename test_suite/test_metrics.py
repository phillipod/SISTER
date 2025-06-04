import pytest
import numpy as np
from sister_sto.metrics.ms_ssim import multi_scale_match
from sister_sto.utils.image import apply_mask

@pytest.fixture
def sample_images():
    """Create sample images for testing."""
    # Create a simple pattern in both images
    # Region slightly larger than template to allow for matching
    region = np.zeros((60, 50, 3), dtype=np.uint8)
    region[5:52, 5:41] = 255  # White rectangle matching icon size
    
    template = np.zeros((47, 36, 3), dtype=np.uint8)
    template[:, :] = 255  # White rectangle of exact icon size
    
    return region, template

def test_multi_scale_match_exact(sample_images):
    """Test multi-scale matching with exact match."""
    region, template = sample_images
    result = multi_scale_match(
        "test_match",
        region,
        template,
        mask_type=None,
        scales=[1.0],
        threshold=0.7
    )
    
    assert result is not None
    location, dimensions, score, scale, method = result
    assert score >= 0.7
    assert scale == 1.0

def test_multi_scale_match_with_scaling(sample_images):
    """Test multi-scale matching with different scales."""
    region, template = sample_images
    result = multi_scale_match(
        "test_match",
        region,
        template,
        mask_type=None,
        scales=np.linspace(0.8, 1.2, 3),  # Reduced number of scales
        threshold=0.7
    )
    
    assert result is not None
    location, dimensions, score, scale, method = result
    assert score >= 0.7

def test_multi_scale_match_no_match(sample_images):
    """Test multi-scale matching with no match."""
    region = np.zeros((60, 50, 3), dtype=np.uint8)  # All black
    template = np.ones((47, 36, 3), dtype=np.uint8) * 255  # All white
    
    result = multi_scale_match(
        "test_match",
        region,
        template,
        mask_type=None,
        scales=[1.0],
        threshold=0.7
    )
    
    assert result is None

def test_multi_scale_match_with_steps(sample_images):
    """Test multi-scale matching with specified steps."""
    region, template = sample_images
    result = multi_scale_match(
        "test_match",
        region,
        template,
        mask_type=None,
        scales=[1.0],
        steps=(5, 5),  # Steps to known location
        threshold=0.7
    )
    
    assert result is not None
    location, dimensions, score, scale, method = result
    assert score >= 0.7 