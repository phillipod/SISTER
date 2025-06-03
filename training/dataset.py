import os
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import torch
from torch.utils.data import Dataset
import cv2
import numpy as np

class LabeledRegionDataset(Dataset):
    def __init__(
        self,
        user_dirs: List[str],
        transform=None,
        target_size=(32, 128),  # Height, Width
        use_grayscale=True
    ):
        self.user_dirs = user_dirs
        self.transform = transform
        self.target_size = target_size
        self.use_grayscale = use_grayscale
        
        # Load all samples
        self.samples = []  # List of (image_path, label, platform)
        self.class_to_idx = {}  # Map label text to numeric index
        self.platform_to_idx = {"pc": 0, "console": 1}
        
        self._load_all_samples()
        print(f"Loaded {len(self.samples)} samples with {len(self.class_to_idx)} unique labels")
        
    def _find_label_dirs(self, base_dir: Path) -> List[Path]:
        """Recursively find directories containing labels.json files."""
        label_dirs = []
        
        # First check if this directory itself has a labels.json and image subdirectories
        labels_file = base_dir / "labels.json"
        if labels_file.exists():
            # Check if it has any screenshot subdirectories with their own labels.json
            has_screenshot_dirs = False
            for subdir in base_dir.iterdir():
                if subdir.is_dir() and (subdir / "labels.json").exists():
                    has_screenshot_dirs = True
                    label_dirs.append(subdir)
            
            # If no screenshot subdirectories found, this might be a screenshot directory itself
            if not has_screenshot_dirs:
                label_dirs.append(base_dir)
        else:
            # Recursively search subdirectories
            for subdir in base_dir.iterdir():
                if subdir.is_dir():
                    label_dirs.extend(self._find_label_dirs(subdir))
        
        return label_dirs
        
    def _load_all_samples(self):
        """Load all samples from all user directories."""
        for user_dir in self.user_dirs:
            base_dir = Path(user_dir)
            label_dirs = self._find_label_dirs(base_dir)
            
            print(f"Found {len(label_dirs)} label directories in {user_dir}")
            
            for label_dir in label_dirs:
                labels_file = label_dir / "labels.json"
                if not labels_file.exists():
                    continue
                    
                with open(labels_file, "r", encoding="utf-8") as f:
                    label_info = json.load(f)
                
                # Process each label in the screenshot
                if "labels" in label_info:  # This is a screenshot-specific labels.json
                    for label_info in label_info["labels"]:
                        # Get image path
                        img_path = label_dir / (label_info["file_gray"] if self.use_grayscale else label_info["file"])
                        if not img_path.exists():
                            continue
                        
                        # Add label to class mapping if new
                        label_text = label_info["text"]
                        if label_text not in self.class_to_idx:
                            self.class_to_idx[label_text] = len(self.class_to_idx)
                        
                        # Store sample
                        self.samples.append({
                            "image_path": str(img_path),
                            "label_idx": self.class_to_idx[label_text],
                            "label_text": label_text,
                            "platform_idx": self.platform_to_idx[label_info["platform"]],
                            "platform": label_info["platform"]
                        })
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        sample = self.samples[idx]
        
        # Load and preprocess image
        image = cv2.imread(sample["image_path"], cv2.IMREAD_GRAYSCALE if self.use_grayscale else cv2.IMREAD_COLOR)
        
        # Resize to target size
        image = cv2.resize(image, (self.target_size[1], self.target_size[0]))
        
        # Normalize to [0, 1]
        image = image.astype(np.float32) / 255.0
        
        # Add channel dimension if grayscale
        if self.use_grayscale:
            image = np.expand_dims(image, axis=0)
        
        # Convert to tensor
        image = torch.FloatTensor(image)
        
        # Apply any additional transforms
        if self.transform is not None:
            image = self.transform(image)
        
        return {
            "image": image,
            "label_idx": sample["label_idx"],
            "label_text": sample["label_text"],
            "platform_idx": sample["platform_idx"],
            "platform": sample["platform"]
        }
    
    @property
    def num_classes(self):
        return len(self.class_to_idx)
    
    @property
    def class_names(self):
        return list(self.class_to_idx.keys()) 