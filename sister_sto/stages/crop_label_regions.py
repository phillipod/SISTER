from typing import Any, Dict, List, Callable
import os
import cv2
import numpy as np
import json
import hashlib
from pathlib import Path

from ..pipeline.core import PipelineStage, PipelineState, StageOutput
from ..pipeline.progress_reporter import StageProgressReporter

class CropLabelRegionsStage(PipelineStage):
    def __init__(self, config: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(config, app_config)
        self.name = "crop_label_regions"
        self.output_dir = Path(config.get("label_output_dir", "label_output"))
        self.participate_learning_data_acquisition = config.get("participate_learning_data_acquisition", False)
        
    def _compute_md5(self, image: np.ndarray) -> str:
        """Compute MD5 hash of an image array."""
        return hashlib.md5(image.tobytes()).hexdigest()
        
    def process(self, ctx: PipelineState, report: Callable[[str, float], None]) -> StageOutput:
        if not ctx.labels_list or not ctx.screenshots or not hasattr(ctx, 'classification'):
            return StageOutput(ctx, None)
            
        # If not participating in learning data acquisition, return early
        if not self.participate_learning_data_acquisition:
            return StageOutput(ctx, None)
            
        # Create progress reporter
        progress_cb = StageProgressReporter(
            self.name,
            report
        )
            
        # Create base output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize global label info
        global_label_info = {
            "screenshots": [],
            "total_labels": 0,
            "platform": ctx.classification["platform"],
            "icon_set": ctx.classification["icon_set"],
            "build_type": ctx.classification["build_type"]
        }
        
        total_labels = sum(len(labels) for labels in ctx.labels_list)
        processed = 0
        
        report(self.name, "Starting", 0.0)
        
        for screenshot_idx, (screenshot, labels_dict) in enumerate(zip(ctx.screenshots, ctx.labels_list)):
            # Compute MD5 hash for this screenshot
            screenshot_hash = self._compute_md5(screenshot)
            
            # Create screenshot-specific directory
            screenshot_dir = self.output_dir / screenshot_hash
            os.makedirs(screenshot_dir, exist_ok=True)
            
            # Initialize screenshot-specific label info
            screenshot_label_info = {
                "screenshot_hash": screenshot_hash,
                "screenshot_index": screenshot_idx,
                "platform": ctx.classification["platform"],
                "icon_set": ctx.classification["icon_set"],
                "build_type": ctx.classification["build_type"],
                "labels": []
            }
            
            # Process each label in the screenshot
            for label_idx, (label_text, label_data) in enumerate(labels_dict.items()):
                # Get coordinates
                x1, y1 = label_data["top_left"]
                x2, y2 = label_data["bottom_right"]
                w = x2 - x1
                h = y2 - y1
                
                # Crop the color region
                cropped_region = screenshot[y1:y2, x1:x2]
                
                # Get the grayscale ROI
                gray_roi = label_data["roi_data"]["gray_roi"]
                
                # Create filenames
                base_filename = f"{label_idx:04d}"
                color_filename = f"{base_filename}.png"
                gray_filename = f"{base_filename}_gray.png"
                
                # Save both versions
                cv2.imwrite(str(screenshot_dir / color_filename), cropped_region)
                cv2.imwrite(str(screenshot_dir / gray_filename), gray_roi)
                
                # Add label info
                label_info = {
                    "file": color_filename,
                    "file_gray": gray_filename,
                    "text": label_text,
                    "bbox": [x1, y1, w, h],
                    "dimensions": f"{w}x{h}",
                    "corners": {
                        "top_left": label_data["top_left"],
                        "top_right": label_data["top_right"],
                        "bottom_left": label_data["bottom_left"],
                        "bottom_right": label_data["bottom_right"]
                    },
                    "platform": ctx.classification["platform"],
                    "icon_set": ctx.classification["icon_set"]
                }
                screenshot_label_info["labels"].append(label_info)
                
                processed += 1
                report(self.name, f"Processing screenshot {screenshot_idx+1}, label {label_idx+1}/{len(labels_dict)}", (processed / total_labels) * 100)
            
            # Write screenshot-specific label JSON
            with open(screenshot_dir / "labels.json", "w", encoding="utf-8") as f:
                json.dump(screenshot_label_info, f, indent=2, ensure_ascii=False)
            
            # Add to global label info
            global_label_info["screenshots"].append({
                "hash": screenshot_hash,
                "index": screenshot_idx,
                "label_count": len(labels_dict)
            })
            global_label_info["total_labels"] += len(labels_dict)
        
        # Write global label JSON
        with open(self.output_dir / "labels.json", "w", encoding="utf-8") as f:
            json.dump(global_label_info, f, indent=2, ensure_ascii=False)
        
        output = {
            "output_dir": str(self.output_dir),
            "total_labels": total_labels,
            "label_info": global_label_info
        }
        
        report(self.name, f"Completed - Processed {total_labels} labels", 100.0)
        return StageOutput(ctx, output) 