import time
import json
import cv2
import numpy as np
import argparse
import logging
from typing import Dict, Any, Optional

def get_logger() -> logging.Logger:
    return logging.getLogger('text_detection')

def setup_logging(debug: bool = False) -> None:
    """Configure the logging system"""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

def log_debug(msg: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Log debug message with optional structured data"""
    if get_logger().isEnabledFor(logging.DEBUG):
        if data:
            get_logger().debug(f"{msg}\n{json.dumps(data, indent=2)}")
        else:
            get_logger().debug(msg)

def log_info(msg: str) -> None:
    """Log info message"""
    get_logger().info(msg)

def log_error(msg: str) -> None:
    """Log error message"""
    get_logger().error(msg)

metrics = { }

def start_metric(name: str) -> None:
    metrics[name] = {
        "start": time.time(),
    }

def end_metric(name: str) -> None:
    metrics[name]["end"] = time.time()

def get_metrics():
    return [
        {"name": name, "duration": metric["end"] - metric["start"]}
        for name, metric in metrics.items()
    ]

def load_model_and_config(model_path, config_path):
    """Load the ONNX model and its configuration using OpenCV with runtime optimizations."""
    # Load configuration
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Load ONNX model with OpenCV
    net = cv2.dnn.readNetFromONNX(model_path)
    
    # Configure for optimized CPU execution
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    
    # Try to enable fusion optimization if available
    try:
        net.enableFusion(True)
    except:
        pass  # Ignore if not available
    
    return net, config

def process_region_for_model(image_region):
    """Process an image region to match the model's expected input."""
    # Convert BGR to grayscale
    gray_region = cv2.cvtColor(image_region, cv2.COLOR_BGR2GRAY)
    
    # Resize to match training size
    resized = cv2.resize(gray_region, (128, 32))
    
    # Normalize to [0,1] range
    normalized = resized.astype(np.float32) / 255.0
    
    # Expand dimensions to match model input shape [1, 1, 32, 128]
    normalized = np.expand_dims(normalized, axis=0)  # Add batch dimension
    normalized = np.expand_dims(normalized, axis=0)  # Add channel dimension
    
    # Transpose to match NCHW format expected by ONNX
    normalized = normalized.transpose(0, 1, 2, 3)
    
    return normalized

def resize_to_max_fullhd(image, max_width=1920, max_height=1080):
    """
    Resize an image to fit within 1920x1080 (or specified limits) while maintaining aspect ratio.

    Args:
        image (np.array): Input BGR or grayscale image.
        max_width (int): Maximum width (default 1920).
        max_height (int): Maximum height (default 1080).

    Returns:
        np.array: Resized image if scaling was needed; original image otherwise.
    """
    h, w = image.shape[:2]

    if w <= max_width and h <= max_height:
        return image  # No resizing needed

    # Calculate scale factor to fit within max dimensions
    scale_w = max_width / w
    scale_h = max_height / h
    scale = min(scale_w, scale_h)

    new_w = int(w * scale)
    new_h = int(h * scale)

    try:
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    except Exception as e:
        raise ImageProcessingError("Failed to resize image.") from e

    return image

def decode_predictions(scores, geometry, score_thresh):
    """
    Decode the raw output of the EAST model:
      - scores: probability scores (1x1xHxW)
      - geometry: geometry map (1x5xHxW) containing distances and angles
    Returns:
      - boxes: list of [startX, startY, endX, endY] in the resized image's coordinate space
      - confidences: list of score values
    """
    start_metric('decode_predictions')
    (num_rows, num_cols) = scores.shape[2:4]
    boxes = []
    confidences = []

    for y in range(num_rows):
        # Extract scores and geometry at row y
        scores_data = scores[0, 0, y]
        x0_data    = geometry[0, 0, y]
        x1_data    = geometry[0, 1, y]
        x2_data    = geometry[0, 2, y]
        x3_data    = geometry[0, 3, y]
        angles_data= geometry[0, 4, y]

        for x in range(num_cols):
            score = scores_data[x]
            if score < score_thresh:
                continue

            # Geometry: distances to bounding box sides
            offset_x = x * 4.0
            offset_y = y * 4.0

            angle = angles_data[x]
            cos_a = np.cos(angle)
            sin_a = np.sin(angle)

            h = x0_data[x] + x2_data[x]
            w = x1_data[x] + x3_data[x]

            # Compute box's center
            end_x = int(offset_x + (cos_a * x1_data[x]) + (sin_a * x2_data[x]))
            end_y = int(offset_y - (sin_a * x1_data[x]) + (cos_a * x2_data[x]))
            start_x = int(end_x - w)
            start_y = int(end_y - h)

            boxes.append((start_x, start_y, end_x, end_y))
            confidences.append(float(score))

    end_metric('decode_predictions')
    return (boxes, confidences)

def group_boxes_by_line(boxes, confidences,
                           vert_gap_factor=0.4,
                           hor_overlap_factor=0.5):
    """
    Merge boxes that sit almost directly above/below each other (with a small vertical gap
    or slight overlap) AND have significant horizontal overlap. This should correctly fuse:
        ┌─────┐
        │ Aft │
        └─────┘
        ┌─────────┐
        │ Weapons │
        └─────────┘
    into one "Aft Weapons" box, **even if Aft's bottom edge slightly overlaps Weapons' top edge**.

    Args:
      boxes: List of (x1, y1, x2, y2) in **resized image** coordinates (floats or ints).
      confidences: List of float confidences (same length as boxes).
      vert_gap_factor:
        Fraction of the **average box‐height** to allow as a "vertical gap/overlap" between lines.
        - If your two lines have a bigger gap, raise this (e.g. 0.5 or 0.6).
        - If they're nearly touching, you could drop this to 0.2 or 0.3.
      hor_overlap_factor:
        Fraction of the **smaller box's width** that must overlap in X to be considered "same column."
        (0.5 means at least 50% horizontal overlap.)

    Returns:
      merged_boxes: List of (x1, y1, x2, y2) after merging, still in the resized‐image space.
      merged_confs: List of float confidences (max confidence within each merged group).
    """
    if not boxes:
        return [], []
    start_metric('group_boxes_by_line')

    N = len(boxes)
    # Compute widths/heights
    widths  = np.array([x2 - x1 for (x1, y1, x2, y2) in boxes], dtype=float)
    heights = np.array([y2 - y1 for (x1, y1, x2, y2) in boxes], dtype=float)
    avg_h = np.mean(heights)

    # Precompute array versions of coordinates
    x1_arr = np.array([b[0] for b in boxes], dtype=float)
    y1_arr = np.array([b[1] for b in boxes], dtype=float)
    x2_arr = np.array([b[2] for b in boxes], dtype=float)
    y2_arr = np.array([b[3] for b in boxes], dtype=float)

    vert_tol = avg_h * vert_gap_factor

    # Build adjacency list: if i and j satisfy both vertical‐gap (or slight overlap)
    # AND horizontal‐overlap, we link them.
    adj = [[] for _ in range(N)]
    for i in range(N):
        for j in range(i+1, N):
            # Compute vertical "gap" = (top of lower) − (bottom of upper)
            # We'll test both orders (i above j and j above i).
            # Case i above j:
            if y1_arr[j] >= y1_arr[i]:
                gap_ij = y1_arr[j] - y2_arr[i]
                # Now allow negative gap_ij (i.e. slight overlap) or small positive gap
                if abs(gap_ij) <= vert_tol:
                    # Horizontal overlap:
                    inter_left  = max(x1_arr[i], x1_arr[j])
                    inter_right = min(x2_arr[i], x2_arr[j])
                    overlap_len = max(0.0, inter_right - inter_left)
                    min_w = min(widths[i], widths[j])
                    if overlap_len >= hor_overlap_factor * min_w:
                        adj[i].append(j)
                        adj[j].append(i)

            # Case j above i:
            if y1_arr[i] >= y1_arr[j]:
                gap_ji = y1_arr[i] - y2_arr[j]
                if abs(gap_ji) <= vert_tol:
                    inter_left  = max(x1_arr[i], x1_arr[j])
                    inter_right = min(x2_arr[i], x2_arr[j])
                    overlap_len = max(0.0, inter_right - inter_left)
                    min_w = min(widths[i], widths[j])
                    if overlap_len >= hor_overlap_factor * min_w:
                        adj[i].append(j)
                        adj[j].append(i)

    # Find connected components (boxes that link either directly or via a chain)
    visited = [False] * N
    components = []
    for i in range(N):
        if not visited[i]:
            stack = [i]
            comp = []
            visited[i] = True
            while stack:
                u = stack.pop()
                comp.append(u)
                for v in adj[u]:
                    if not visited[v]:
                        visited[v] = True
                        stack.append(v)
            components.append(comp)

    # Merge each component into one bounding‐box + max confidence
    merged_boxes = []
    merged_confs = []
    for comp in components:
        xs = []
        ys = []
        confs = []
        for idx in comp:
            x1, y1, x2, y2 = boxes[idx]
            xs.extend([x1, x2])
            ys.extend([y1, y2])
            confs.append(confidences[idx])
        merged_x1 = float(min(xs))
        merged_y1 = float(min(ys))
        merged_x2 = float(max(xs))
        merged_y2 = float(max(ys))
        merged_boxes.append((merged_x1, merged_y1, merged_x2, merged_y2))
        merged_confs.append(max(confs))

    end_metric('group_boxes_by_line')

    return merged_boxes, merged_confs

def refine_boxes_to_pixels(resized_image, merged_boxes):
    """
    For each merged box (x1, y1, x2, y2) in the **resized** image coordinate space,
    do:
      1) Crop out that region from `resized_image`.
      2) Convert to grayscale & threshold so text becomes "white on black" (or vice versa).
      3) Find all nonzero (text) pixels' coordinates.
      4) Compute a new tight bounding‐box around those pixels.
      5) Map that back into resized‐image coords, optionally expanding by a 1–2px margin.

    Args:
      resized_image: The BGR image you fed to EAST (shape = new_h×new_w×3).
      merged_boxes: List of tuples (x1, y1, x2, y2), each in resized‐image coords.

    Returns:
      refined_boxes: List of (x1r, y1r, x2r, y2r), each a tighter box in the resized‐image space.
    """
    start_metric('refine_boxes_to_pixels')
    h_resized, w_resized = resized_image.shape[:2]
    refined_boxes = []

    for (x1, y1, x2, y2) in merged_boxes:
        # 1) Crop the ROI from the resized image
        x1_i, y1_i = int(x1), int(y1)
        x2_i, y2_i = int(x2), int(y2)
        roi = resized_image[y1_i:y2_i, x1_i:x2_i]

        if roi.size == 0:
            # Empty ROI—just skip or use the original
            refined_boxes.append((x1, y1, x2, y2))
            continue

        # 2) Convert to gray and threshold: we assume text is lighter than background.
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Invert threshold so text (white or light) becomes foreground:
        # Use Otsu to automatically pick a good threshold.
        _, thresh = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 3) Find coordinates of all "text pixels" (nonzero in thresh)
        pts = cv2.findNonZero(thresh)  # returns Nx1x2 array of (x,y) coords
        if pts is None:
            # No "white" pixels detected—fallback to the original merged box
            refined_boxes.append((x1, y1, x2, y2))
            continue

        # Reshape pts to an (N×2) array
        pts = pts.reshape(-1, 2)

        # 4) Compute a tight bounding rect around these pixels (in ROI-coordinates)
        x_coords = pts[:, 0]
        y_coords = pts[:, 1]
        x1_new_roi = int(np.min(x_coords))
        y1_new_roi = int(np.min(y_coords))
        x2_new_roi = int(np.max(x_coords))
        y2_new_roi = int(np.max(y_coords))

        # 5) Map that ROI-tight box back to resized_image coords
        new_x1 = x1_i + x1_new_roi
        new_y1 = y1_i + y1_new_roi
        new_x2 = x1_i + x2_new_roi
        new_y2 = y1_i + y2_new_roi

        # 6) (Optional) Add a 1–2 px margin so you don't cut off descenders (like "g")
        #    You can tweak this number if you still want a tiny pad.
        pad_px = 2
        new_x1 = max(0, new_x1 - pad_px)
        new_y1 = max(0, new_y1 - pad_px)
        new_x2 = min(w_resized - 1, new_x2 + pad_px)
        new_y2 = min(h_resized - 1, new_y2 + pad_px)

        refined_boxes.append((float(new_x1),
                              float(new_y1),
                              float(new_x2),
                              float(new_y2)))

    end_metric('refine_boxes_to_pixels')

    return refined_boxes

def safe_shape_to_list(shape):
    """Convert shape to list, handling both numpy arrays and tuples"""
    if hasattr(shape, 'tolist'):
        return shape.tolist()
    return list(shape)

def validate_prediction(region_dims, predicted_label: str, confidence: float) -> tuple[bool, str]:
    """
    Validate predictions based on confidence threshold.
    Returns (is_valid, reason)
    """
    if confidence < 0.7:
        return False, f"Low confidence {confidence:.2f}"
    
    return True, "Valid prediction"

if __name__ == "__main__":
    start_metric('main')
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--image", required=True,
        help="Path to input image"
    )
    parser.add_argument(
        "-east", "--east", required=True,
        help="Path to pretrained EAST text detector (frozen_east_text_detection.pb)"
    )
    parser.add_argument(
        "-m", "--model", required=True,
        help="Path to trained model in ONNX format"
    )
    parser.add_argument(
        "-cfg", "--config", required=True,
        help="Path to model configuration JSON file"
    )
    parser.add_argument(
        "-c", "--min_confidence", type=float, default=0.5,
        help="Minimum probability to consider a region as text"
    )
    parser.add_argument(
        "-w", "--width", type=int,
        help="Resized image width (must be multiple of 32)"
    )
    parser.add_argument(
        "-e", "--height", type=int,
        help="Resized image height (must be multiple of 32)"
    )
    parser.add_argument(
        "-d", "--debug", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()
    
    # Configure logging
    setup_logging(debug=args.debug)

    # Load our trained model and config
    log_info("Loading trained model...")
    model, config = load_model_and_config(args.model, args.config)
    idx_to_class = {idx: label for label, idx in config['class_to_idx'].items()}

    # Load image and grab original dimensions
    image = cv2.imread(args.image)
    if image is None:
        log_error(f"ERROR: could not load image at {args.image}")
        exit(1)

    image = resize_to_max_fullhd(image)

    orig_h, orig_w = image.shape[:2]

    # Determine new dimensions that are multiples of 32
    if hasattr(args, "width") and hasattr(args, "height") and args.width and args.height:
        new_w, new_h = args.width, args.height
    else:
        # Compute nearest multiple of 32 for width and height
        # Use round() so that we pick the closest multiple;
        # ensure we never drop below 32.
        new_w = max(32, int(round((orig_w / 1.5) / 32.0)) * 32)
        new_h = max(32, int(round((orig_h / 1.5) / 32.0)) * 32)

    print(f"new_w: {new_w}, new_h: {new_h}")
    r_w = orig_w / float(new_w)
    r_h = orig_h / float(new_h)
    resized = cv2.resize(image, (new_w, new_h))

    start_metric('load_blob')
    blob = cv2.dnn.blobFromImage(
        resized,
        scalefactor=1.0,
        size=(new_w, new_h),
        mean=(123.68, 116.78, 103.94),
        swapRB=True,
        crop=False
    )
    end_metric('load_blob')

    start_metric('setup_east')
    east_net = cv2.dnn.readNet(args.east)
    east_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    east_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    layer_names = [
        "feature_fusion/Conv_7/Sigmoid",
        "feature_fusion/concat_3"
    ]
    end_metric('setup_east')

    start_metric('run_east')
    east_net.setInput(blob)
    (scores, geometry) = east_net.forward(layer_names)
    end_metric('run_east')

    (boxes, confidences) = decode_predictions(
        scores, geometry, score_thresh=args.min_confidence
    )

    indices = cv2.dnn.NMSBoxes(
        bboxes=[(b[0], b[1], b[2]-b[0], b[3]-b[1]) for b in boxes],
        scores=confidences,
        score_threshold=args.min_confidence,
        nms_threshold=0.4
    )

    picked_boxes = [boxes[i] for i in indices.flatten()]
    picked_confs = [confidences[i] for i in indices.flatten()]

    grouped_boxes, grouped_confs = group_boxes_by_line(
        picked_boxes, picked_confs, vert_gap_factor=0.4, hor_overlap_factor=0.2
    )

    refined_boxes = refine_boxes_to_pixels(resized, grouped_boxes)

    start_metric('run_model')

    # Process each detected region with our trained model
    log_info("\nTesting detected regions...")
    resized_with_boxes = resized.copy()
    
    log_info(f"Found {len(refined_boxes)} regions to test")
    log_debug("Model configuration", {
        "num_classes": len(idx_to_class),
        "class_mapping": idx_to_class
    })
    
    for (x1_p, y1_p, x2_p, y2_p) in refined_boxes:
        # Extract region from resized image
        x1, y1, x2, y2 = map(int, (x1_p, y1_p, x2_p, y2_p))
        region = resized[y1:y2, x1:x2]
        
        # Skip if region is empty or too small
        if region.size == 0 or region.shape[0] < 4 or region.shape[1] < 4:
            log_debug(f"Skipping small/empty region at ({x1}, {y1}, {x2}, {y2})")
            continue
            
        # Process region for model
        input_blob = process_region_for_model(region)
        log_debug("Processing region", {
            "location": f"({x1}, {y1}, {x2}, {y2})",
            "dimensions": f"{region.shape[1]}x{region.shape[0]}",
            "input_shape": safe_shape_to_list(input_blob.shape)
        })
        
        # Get model prediction
        model.setInput(input_blob)
        outputs = model.forward(model.getUnconnectedOutLayersNames())
        
        # Debug output information
        output_info = {
            "layer_names": model.getUnconnectedOutLayersNames(),
            "num_outputs": len(outputs),
            "output_shapes": [safe_shape_to_list(out.shape) for out in outputs]
        }
        log_debug("Model outputs", output_info)
        
        # Get label logits (first output)
        label_logits = outputs[0].flatten()
        log_debug("Raw logits", {
            "values": label_logits.tolist()
        })
        
        # Get predicted class
        label_pred = np.argmax(label_logits)
        
        # Apply softmax to get probabilities
        exp_logits = np.exp(label_logits - np.max(label_logits))
        probabilities = exp_logits / exp_logits.sum()
        
        # Get top 3 predictions
        top3_idx = np.argsort(probabilities)[-3:][::-1]
        top3_predictions = [
            {"label": idx_to_class.get(idx, f"Unknown-{idx}"),
             "probability": float(probabilities[idx])}
            for idx in top3_idx
        ]
        log_debug("Top 3 predictions", {"predictions": top3_predictions})
        
        confidence = probabilities[label_pred]
        predicted_label = idx_to_class.get(label_pred, f"Unknown-{label_pred}")
        
        # Validate prediction based on region characteristics
        is_valid, reason = validate_prediction(
            (region.shape[0], region.shape[1]), 
            predicted_label, 
            confidence
        )
        
        if not is_valid:
            log_debug(f"Rejecting prediction: {reason}")
            color = (0, 0, 255)  # Red for rejected predictions
        else:
            log_info(f"Final prediction: {predicted_label} ({confidence:.3f})")
            
            # Draw box with color based on confidence
            if confidence > 0.7:  # High confidence threshold
                color = (0, 255, 0)  # Green for matches
                log_info(f"Match found! Label: {predicted_label}, Confidence: {confidence:.2f}")
            else:
                color = (0, 0, 255)  # Red for non-matches


        # Draw on both resized and original images
        cv2.rectangle(resized_with_boxes, (x1, y1), (x2, y2), color, 2)
        
        # Draw on original image (with scaling)
        sx = int(x1_p * r_w)
        sy = int(y1_p * r_h)
        ex = int(x2_p * r_w)
        ey = int(y2_p * r_h)
        cv2.rectangle(image, (sx, sy), (ex, ey), color, 2)
        
        # If it's a match, add label text
        if confidence > 0.7:
            label_text = f"{predicted_label} ({confidence:.2f})"
            cv2.putText(resized_with_boxes, label_text, (x1, y1-5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            cv2.putText(image, label_text, (sx, sy-5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    end_metric('run_model')
    
    end_metric('main')

    for metric in get_metrics():
        print(f"{metric['name']} took {metric['duration']:.2f} seconds")

    # Show results
    cv2.imshow("EAST Resized (with boxes)", resized_with_boxes)
    cv2.imshow("Original Scale (with scaled boxes)", image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
