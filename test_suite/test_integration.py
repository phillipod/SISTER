import json
import os
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
import pytest
import numpy as np
import cv2

from sister_sto.pipeline.pipeline import build_default_pipeline
from sister_sto.pipeline.core import PipelineState

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "data"

class TestBuild:
    """Test case for a single build with multiple screenshots."""
    
    def __init__(self, build_dir: Path):
        self.build_dir = build_dir
        self.test_data = self._load_test_data()
        self.build_id = self.test_data.get("build_id", build_dir.name)
        self.expected_results = self.test_data.get("expected_results", {})
    
    def _load_test_data(self) -> Dict[str, Any]:
        """Load test data from the build directory."""
        test_data_file = self.build_dir / "test_data.json"
        if not test_data_file.exists():
            return {}
        
        with open(test_data_file, 'r') as f:
            return json.load(f)
    
    def get_screenshots(self) -> Dict[str, np.ndarray]:
        """Load screenshots from the build directory."""
        screenshots = {}
        for file in self.build_dir.glob("*.png"):
            img = cv2.imread(str(file))
            if img is not None:
                # Calculate MD5 of the file content
                with open(file, 'rb') as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()
                screenshots[file_hash] = img
        return screenshots
    
    def _sort_items_by_score(self, items):
        """Sort items by score (descending for SSIM, ascending for hash)."""
        def sort_key(item):
            method = item.get("method", "ssim")
            if method.startswith("hash"):
                # For hash, lower distance is better
                return (0, item.get("distance", float('inf')))
            else:
                # For SSIM, higher score is better
                return (1, -item.get("score", -float('inf')))
        
        return sorted(items, key=sort_key)

    def _is_method_match(self, actual_method: str, expected_method: str) -> bool:
        """Check if actual method matches expected method with prefix handling."""
        if actual_method.startswith("ssim") and expected_method.startswith("ssim"):
            return True
        if actual_method.startswith("hash") and expected_method.startswith("hash"):
            return True
        return actual_method == expected_method

    def validate_result(self, expected: Dict, actual_output: Dict) -> List[str]:
        """
        Validate that the actual pipeline output matches the expected results.
        
        Args:
            expected: Dictionary containing expected results
            actual_output: Actual pipeline output
            
        Returns:
            List of error messages, empty if validation passes
        """
        errors = []
        expected_matches = expected.get("matches", {})
        actual_matches = actual_output.get("matches", {})
        
        # Check for missing icon groups
        missing_groups = set(expected_matches.keys()) - set(actual_matches.keys())
        if missing_groups:
            errors.append(f"Missing expected icon groups: {', '.join(missing_groups)}")
        
        # Check each icon group
        for group_name, expected_slots in expected_matches.items():
            if group_name not in actual_matches:
                continue
                
            actual_slots = actual_matches[group_name]
            
            # Check for missing slots
            missing_slots = set(expected_slots.keys()) - set(actual_slots.keys())
            if missing_slots:
                errors.append(f"Group {group_name} is missing slots: {', '.join(missing_slots)}")
            
            # Check each slot
            for slot_idx, expected_items in expected_slots.items():
                if slot_idx not in actual_slots:
                    continue
                    
                # Sort actual items by score (descending for SSIM, ascending for hash)
                actual_items = self._sort_items_by_score(actual_slots[slot_idx])
                
                # For each expected item, check if there's a matching actual item
                for expected_item in expected_items:
                    expected_method = expected_item.get("method", "ssim")
                    expected_item_name = expected_item.get("item_name")
                    expected_overlay = expected_item.get("overlay")
                    matched = False
                    
                    # Find all actual items with matching name and overlay (if specified)
                    candidate_items = []
                    for item in actual_items:
                        # Check if item names match
                        if item.get("item_name") != expected_item_name:
                            continue
                            
                        # Check overlay if specified in expected
                        if expected_overlay is not None:
                            actual_overlay = item.get("detected_overlay", [{}])[0].get("overlay") \
                                          if isinstance(item.get("detected_overlay"), list) \
                                          else item.get("overlay")
                            if actual_overlay != expected_overlay:
                                continue
                        
                        # Check if method matches (SSIM/SSIM-* or hash/hash-*)
                        actual_method = item.get("method", "")
                        if not self._is_method_match(actual_method, expected_method):
                            continue
                            
                        candidate_items.append(item)
                    
                    # For SSIM, check if it's the best match
                    if expected_method.startswith("ssim"):
                        if candidate_items and candidate_items[0].get("item_name") == expected_item_name:
                            matched = True
                    
                    # For hash, check if it's among the best matches (lowest distance)
                    elif expected_method.startswith("hash") and candidate_items:
                        min_distance = min(item.get("distance", float('inf')) for item in candidate_items)
                        if any(item.get("distance") == min_distance for item in candidate_items):
                            matched = True
                    
                    # For other methods, any match is acceptable
                    elif candidate_items:
                        matched = True
                    
                    if not matched:
                        error_msg = f"No matching item found for {expected_item} in {group_name}[{slot_idx}]. "
                        error_msg += f"Available items: {[item.get('item_name') for item in actual_items]}"
                        errors.append(error_msg)
        
        return errors


def collect_test_builds():
    """Collect all test builds from the data directory."""
    test_builds = []
    for build_dir in TEST_DATA_DIR.glob("*"):
        if build_dir.is_dir():
            test_builds.append(build_dir)
    return test_builds


# Test fixtures
@pytest.fixture(scope="module")
def pipeline():
    """Create a pipeline instance for testing."""
    def on_progress(stage, substage, pct, ctx):
        pass
        
    def on_interactive(stage, ctx):
        return True
        
    def on_error(err):
        pass
    
    return build_default_pipeline(
        on_progress=on_progress,
        on_interactive=on_interactive,
        on_error=on_error,
        config={}
    )


@pytest.mark.parametrize("build_dir", collect_test_builds())
def test_build(pipeline, build_dir):
    """Test a single build with its screenshots."""
    test_build = TestBuild(build_dir)
    screenshots = test_build.get_screenshots()
    
    assert screenshots, f"No screenshots found in {build_dir}"
    
    for screenshot_hash, img in screenshots.items():
        # Skip if no expected results for this screenshot
        if screenshot_hash not in test_build.expected_results:
            continue
            
        # Run the pipeline
        state = PipelineState(screenshots=[img])
        try:
            ctx, results = pipeline.run([img])
            
            # Validate the results
            errors = test_build.validate_result(screenshot_hash, ctx.output)
            
            # Fail if there are validation errors
            if errors:
                error_msg = f"Validation failed for {build_dir.name}/{screenshot_hash}.png:\n"
                error_msg += "\n".join(f"  - {error}" for error in errors)
                assert False, error_msg
                
        except Exception as e:
            assert False, f"Pipeline failed for {build_dir.name}/{screenshot_hash}.png: {str(e)}"


if __name__ == "__main__":
    # This allows running the tests directly with: python -m test_suite.test_integration
    pytest.main([__file__])
