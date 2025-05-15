import imagehash
from PIL import Image
import cv2
import numpy as np


def compute(image, size=(32, 32), grayscale=False):
    """
    Compute the perceptual hash from an image.

    Args:
        image (bytes or bytearray or array-like or numpy.ndarray):
            - Raw encoded bytes (e.g. PNG/JPEG) or
            - A NumPy array (any integer dtype) representing an image
            - A Python list of lists/integers (will be turned into an array)
        size (tuple):  Desired output size for hashing.
        grayscale (bool): Convert to gray before hashing.

    Returns:
        str: Hex string of the computed perceptual hash.
    """
    # 1) Normalize input to a NumPy array of dtype uint8
    if isinstance(image, (bytes, bytearray)):
        arr = np.frombuffer(image, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image from bytes.")
    else:
        # array-like or ndarray
        arr = np.array(image, copy=False)
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8)
        # If it’s already a 2D (grayscale) or 3D array, we treat it as image pixels.
        if arr.ndim == 2:
            # single-channel grayscale → convert to BGR so later steps are uniform
            img = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        elif arr.ndim == 3 and arr.shape[2] in (1, 3, 4):
            # 1‐channel, 3‐channel, or 4‐channel array
            if arr.shape[2] == 4:
                # drop alpha
                img = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            else:
                img = arr
        else:
            raise ValueError(f"Unsupported array shape for image: {arr.shape}")

    # 2) Convert BGR→RGB
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # 3) Optionally force grayscale
    if grayscale:
        # if it’s already gray after cvtColor above, this is a no-op
        rgb = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # 4) Resize to target size
    resized = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)

    # 5) Compute perceptual hash
    pil_img = Image.fromarray(resized)
    return str(imagehash.phash(pil_img))

class PHashHasher:
    """
    Computes perceptual hashes (pHash) from raw image bytes using the imagehash library.
    Resizes images to 32x32 for consistency before hashing.
    """


    def compute(self, image, size=(32, 32), grayscale=False):
        return compute(image, size, grayscale)