import imagehash
from PIL import Image
import cv2
import numpy as np

class PHashHasher:
    """
    Computes perceptual hashes (pHash) from raw image bytes using the imagehash library.
    Resizes images to 32x32 for consistency before hashing.
    """

    def compute(self, image_bytes, size=(32, 32), grayscale=False):
        """
        Compute the perceptual hash from image bytes.

        Args:
            image_bytes (bytes): Encoded image (e.g., PNG) as bytes.

        Returns:
            str: Hex string of the computed hash.
        """
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image from bytes.")
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        #masked = apply_mask(img)
        masked = rgb

        if grayscale:
            masked = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
        

        resized = cv2.resize(masked, size, interpolation=cv2.INTER_AREA)
        pil_img = Image.fromarray(resized)

        return str(imagehash.phash(pil_img))
