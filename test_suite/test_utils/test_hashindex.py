import pytest
import numpy as np
from PIL import Image, ImageDraw
from sister_sto.utils.hashindex import compute_dhash, compute_phash, hamming_distance, tuple_hamming_distance

def create_test_image(size=(32, 32), color=(255, 255, 255)):
    """Helper function to create a test image."""
    return Image.new('RGB', size, color)

def create_pattern_image(size=(32, 32), pattern_type='circle'):
    """Create an image with a specific pattern."""
    img = Image.new('RGB', size, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    if pattern_type == 'circle':
        draw.ellipse([size[0]//4, size[1]//4, 3*size[0]//4, 3*size[1]//4], fill='black')
    elif pattern_type == 'rectangle':
        draw.rectangle([size[0]//4, size[1]//4, 3*size[0]//4, 3*size[1]//4], fill='black')
    
    return img

def test_compute_dhash():
    """Test that dhash computation works correctly."""
    # Create a simple test image
    test_image = create_test_image()
    
    # Compute hash
    hash_value = compute_dhash(test_image)
    
    # Basic validation
    assert isinstance(hash_value, str)
    assert len(hash_value) > 0

def test_compute_phash():
    """Test that phash computation works correctly."""
    # Create a simple test image
    test_image = create_test_image()
    
    # Compute hash
    hash_value = compute_phash(test_image)
    
    # Basic validation
    assert isinstance(hash_value, str)
    assert len(hash_value) > 0

def test_hash_consistency():
    """Test that hashing is consistent for the same image."""
    test_image = create_test_image()
    
    # Compute hashes multiple times
    dhash1 = compute_dhash(test_image)
    dhash2 = compute_dhash(test_image)
    phash1 = compute_phash(test_image)
    phash2 = compute_phash(test_image)
    
    # Check consistency
    assert dhash1 == dhash2
    assert phash1 == phash2

def test_hash_difference():
    """Test that different images produce different hashes."""
    image1 = create_pattern_image(pattern_type='circle')
    image2 = create_pattern_image(pattern_type='rectangle')
    
    dhash1 = compute_dhash(image1)
    dhash2 = compute_dhash(image2)
    phash1 = compute_phash(image1)
    phash2 = compute_phash(image2)
    
    # Different images should have different hashes
    assert dhash1 != dhash2
    assert phash1 != phash2

def test_hamming_distance():
    """Test hamming distance computation."""
    # Create mock hash objects with a defined difference
    class MockHash:
        def __init__(self, value):
            self.hash = value
        
        def __sub__(self, other):
            return abs(self.hash - other.hash)
    
    hash1 = MockHash(10)
    hash2 = MockHash(15)
    
    distance = hamming_distance(hash1, hash2)
    assert distance == 5

def test_tuple_hamming_distance():
    """Test tuple hamming distance computation."""
    # Create mock hash tuples
    class MockHash:
        def __init__(self, value):
            self.hash = value
        
        def __sub__(self, other):
            return abs(self.hash - other.hash)
    
    tuple1 = (MockHash(10), "metadata1")
    tuple2 = (MockHash(15), "metadata2")
    
    distance = tuple_hamming_distance(tuple1, tuple2)
    assert distance == 5 