import os
import cv2
import numpy as np

from ..exceptions import ImageProcessingError, ImageNotFoundError

#try:
#    from .c_ext.fastssim import fast_ssim as ssim
#except ImportError:
from skimage.metrics import structural_similarity as ssim
#    print("[WARNING] fast_ssim C-extension not available, falling back to skimage SSIM.")

def load_image(image_or_path, resize_fullhd=False):
    """
    Load an image from path, bytes, or numpy array, with optional resize-to-FullHD.

    Args:
        image_or_path (str | bytes | np.ndarray): Input image source.
        resize_fullhd (bool): If True, resize any large image to fit within 1920x1080.

    Returns:
        np.ndarray: Loaded (and optionally resized) image in BGR format.

    Raises:
        ValueError: On unsupported input or loading failure.
    """
    if isinstance(image_or_path, str):
        if not os.path.exists(image_or_path):
            raise ImageNotFoundError(f"Image path does not exist: {image_or_path}")
        
        try:
            image = cv2.imread(image_or_path)
        except Exception as e:
            raise ImageProcessingError(f"Failed to load image from path: {image_or_path}") from e

    elif isinstance(image_or_path, bytes):
        try:
            nparr = np.frombuffer(image_or_path, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as e:
            raise ImageProcessingError("Failed to decode image from bytes.") from e

    elif isinstance(image_or_path, np.ndarray):
        image = image_or_path.copy()
    else:
        raise ImageProcessingError("Unsupported input type. Use str, bytes, or numpy array.")

    if resize_fullhd:
        image = resize_to_max_fullhd(image)

    return image

def load_quality_overlays(overlay_folder):
    overlays = {}
    filenames = [
        "common.png", "uncommon.png", "rare.png",
        "very rare.png", "ultra rare.png", "epic.png"
    ]

    for filename in filenames:
        path = os.path.join(overlay_folder, filename)
        if not os.path.exists(path):
            logger.warning(f"Overlay not found: {filename}")
            continue

        overlay = None
        try:
            overlay = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if overlay is None or overlay.shape[2] != 4:
                logger.warning(f"Skipping {filename}: not a valid 4-channel PNG.")
                continue
        except Exception as e:
            raise ImageProcessingError(f"Failed to load overlay from path: {path}") from e

        key = filename.rsplit(".", 1)[0]  # remove ".png"
        overlays[key] = overlay

    return overlays

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

def apply_overlay(template_color, overlay):
    """
    Apply an overlay image onto a template image with alpha blending.

    Args:
        template_color (np.array): The base image onto which the overlay is applied. 
                                   It should be a 3-channel (BGR or RGB) image.
        overlay (np.array): The overlay image with an alpha channel. 
                            It should be a 4-channel (BGR/RGB + Alpha) image.

    Returns:
        np.array: The blended image resulting from applying the overlay onto the template image.
                  The output image has the same dimensions and 3 channels as the template image.
    """

    overlay_rgb = overlay[:, :, :3]
    overlay_alpha = overlay[:, :, 3] / 255.0
    overlay_rgb = cv2.resize(overlay_rgb, (template_color.shape[1], template_color.shape[0]))
    overlay_alpha = cv2.resize(overlay_alpha, (template_color.shape[1], template_color.shape[0]))

    blended = np.zeros_like(template_color)
    for c in range(3):
        blended[:, :, c] = (overlay_rgb[:, :, c] * overlay_alpha +
                            template_color[:, :, c] * (1 - overlay_alpha))
    return blended.astype(np.uint8)


def create_mask(w, h):
    """
    Create a mask for a given image size (w x h) which fades out the lower right corner.

    The mask is a 2D array of float32 values in the range [0.0, 1.0] used for alpha blending.
    The area from the middle x-coordinate to the right, and from the 75% mark of the y-coordinate
    to the bottom, is set to 0.0 (fully transparent). All other pixels are set to 1.0 (fully opaque).

    Args:
        w (int): Width of the mask image.
        h (int): Height of the mask image.

    Returns:
        np.array: The mask image as a 2D array of float32 values.
    """
    mask = np.ones((h, w), dtype=np.float32)
    mask[int(h*0.75):, int(w*0.5):] = 0.0
    return mask


def apply_mask(image):
    """
    Apply a fading mask to the given image.

    This function uses a mask to fade out the lower right corner of the input image.
    The mask is created based on the dimensions of the image, and it is applied to
    each of the three color channels.

    Args:
        image (np.array): The input image to which the mask is applied. It should be
                          a 3-channel (BGR or RGB) image.

    Returns:
        np.array: The modified image with the mask applied, resulting in a faded effect
                  in the lower right corner.
    """

    h, w = image.shape[:2]
    mask = create_mask(w, h)
    for c in range(3):
        image[:, :, c] = (image[:, :, c].astype(np.float32) * mask).astype(np.uint8)
    return image
