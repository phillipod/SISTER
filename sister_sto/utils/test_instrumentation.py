import json
from pathlib import Path
from typing import List, Dict, Any

class TestInstrumentationCollector:
    """Collects and manages test instrumentation data during pipeline execution."""
    
    def __init__(self):
        self.data = {
            "input": {
                "screenshots": [],  # Will store screenshot names/paths only
                "config": {}  # Will store pipeline config
            },
            "locate_labels": {
                "labels": [],
                "positions": []
            },
            "classify_layout": {
                "classification": "",
                "confidence": 0.0
            },
            "locate_icon_groups": {
                "groups": []
            },
            "locate_icon_slots": {
                "slots": {}
            },
            "prefilter_icons": {
                "matches": [],
                "filtered": []
            },
            "detect_icon_overlays": {
                "overlays": []
            },
            "detect_icons": {
                "matches": [],
                "ssim_scores": []
            },
            "output_transformation": {
                "transformations": [],
                "matches": {}  # Will store the final transformed matches
            }
        }
    
    def record_input(self, screenshot_paths: List[str], config: Dict[str, Any]):
        """Record input screenshot paths and config, but not the actual image data"""
        self.data["input"]["screenshots"] = [str(Path(p).name) for p in screenshot_paths]
        self.data["input"]["config"] = config
    
    def record_labels(self, labels: List[str], positions: List[Dict[str, int]]):
        """Record detected labels and their positions."""
        self.data["locate_labels"]["labels"] = labels
        self.data["locate_labels"]["positions"] = positions
    
    def record_classification(self, classification: str, confidence: float):
        """Record layout classification result."""
        self.data["classify_layout"]["classification"] = classification
        self.data["classify_layout"]["confidence"] = confidence
    
    def record_icon_groups(self, groups: List[Any]):
        """Record detected icon groups."""
        self.data["locate_icon_groups"]["groups"] = groups
    
    def record_icon_slots(self, slots: Dict[str, List[Dict[str, Any]]]):
        """Record detected icon slots."""
        self.data["locate_icon_slots"]["slots"] = slots
    
    def record_prefilter_matches(self, matches: List[Dict], filtered_matches: List[Dict]):
        """Record prefilter matches before and after filtering."""
        self.data["prefilter_icons"]["matches"] = matches
        self.data["prefilter_icons"]["filtered"] = filtered_matches
    
    def record_overlays(self, overlays: List[Dict]):
        """Record detected overlays."""
        self.data["detect_icon_overlays"]["overlays"] = overlays
    
    def record_icon_matches(self, matches: List[Dict], ssim_scores: List[float]):
        """Record final icon matches and SSIM scores."""
        self.data["detect_icons"]["matches"] = matches
        self.data["detect_icons"]["ssim_scores"] = ssim_scores
    
    def record_transformations(self, transformations: List[Dict], matches: Dict = None):
        """Record output transformations and final matches."""
        self.data["output_transformation"]["transformations"] = transformations
        if matches is not None:
            self.data["output_transformation"]["matches"] = matches
    
    def save(self, output_path: str):
        """Save collected test data to JSON file"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    @classmethod
    def load(cls, input_path: str) -> 'TestInstrumentationCollector':
        """Load test instrumentation data from a JSON file."""
        collector = cls()
        with open(input_path) as f:
            collector.data = json.load(f)
        return collector 