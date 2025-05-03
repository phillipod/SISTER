import os
import json
import argparse

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.locator import LabelLocator
from src.classifier import BuildClassifier

from log_config import setup_logging

def main():
    parser = argparse.ArgumentParser(description="Run label detection on SISTER test screenshots.")
    parser.add_argument("--gpu", action="store_true", help="Use GPU for OCR.")
    parser.add_argument("--debug", action="store_true", help="Enable debug images.")
    parser.add_argument("--input-dir", default="./", help="Directory containing test screenshots.")
    parser.add_argument("--output-dir", default="output/label_locator", help="Directory to save debug output images.")
    parser.add_argument("--log-level", default="INFO", help="Set log level: DEBUG, VERBOSE, INFO, WARNING, ERROR.")
    parser.add_argument("--logfile", default="../log/sister.log", help="File to write log output.")

    args = parser.parse_args()

    setup_logging(log_level=args.log_level, log_file=args.logfile)

    os.makedirs(args.output_dir, exist_ok=True)

    locator = LabelLocator(gpu=args.gpu, debug=args.debug)
    classifier = BuildClassifier(debug=args.debug)
    
    sample_images = {
        #"sets_space_1.png": "SETS Ship Build",
        "screenshot_space_1.png": "PC Ship Build",
        #"screenshot_space_2.png": "Unknown",
        #"screenshot_space_3.png": "PC Ship Build",
        #"screenshot_ground_1.png": "PC Ground Build",
        #"screenshot_ground_2.png": "PC Ground Build",
        #"screenshot_ground_3.png": "PC Ground Build",
        #"screenshot_console_ground_1.png": "Console Ground Build",
        #"screenshot_console_ground_2.png": "Unknown",
        #"screenshot_console_space_1.png": "Console Ship Build",
        #"screenshot_console_space_2.png": "Console Ship Build",
        #"screenshot_console_space_3.png": "Unknown",
        #"screenshot_console_space_4.png": "Console Ship Build",
        #"screenshot_console_space_5.png": "Console Ship Build",
        #"screenshot_console_space_6.png": "Console Ship Build",
    }


    for image_name, expected_type in sample_images.items():
        input_path = os.path.join(args.input_dir, image_name)
        base_name = os.path.splitext(image_name)[0]
        output_path = os.path.join(args.output_dir, f"debug_{image_name}")
        output_json_path = os.path.join(args.output_dir, f"debug_{base_name}.json")

        print(f"Processing {input_path}... (Expected: {expected_type})")
        try:
            results = locator.locate_labels(input_path, output_path if args.debug else None)
            print(f"Found {len(results)} labels.")

            classification = classifier.classify(results)
            detected_type = classification["build_type"]
            print(f"Detected Build Type: {detected_type}")

            if detected_type == expected_type:
                print(f"[PASS] Classification matches expected.")
            else:
                print(f"[FAIL] Expected '{expected_type}', got '{detected_type}'")

            results_dict = {
                "labels": {str(k): v for k, v in results.items()},
                "build_type": detected_type,
                "expected_build_type": expected_type,
                "match": detected_type == expected_type
            }

            if args.debug:
                print(json.dumps(results_dict, indent=2))
            
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(results_dict, f, indent=2)
                print(f"Saved results to {output_json_path}")
            
            print()
        except Exception as e:
            print(f"[ERROR] Failed to process {image_name}: {e}")

if __name__ == "__main__":
    main()
