import os
import json
from pathlib import Path
from datetime import datetime
from PIL import Image
import imagehash
import logging
from pybktree import BKTree
from imagehash import hex_to_hash

import cv2
import numpy as np

from .exceptions import HashIndexError, HashIndexNotFoundError
from .hashers.phash import PHashHasher
from .utils.image import apply_overlay, apply_mask  # Adjust if needed

logger = logging.getLogger(__name__)
HASHER_FACTORY = {
    "phash": PHashHasher,
    # "ahash": AHashHasher,  # If you add more
    # "dhash": DHashHasher,
}


def hamming_distance(h1, h2):
    return h1 - h2


BK_TREE_MAP = {}
BK_TREE_RELPATHS = {}


def add_to_bktree(namespace, hash_str, rel_path):
    if namespace not in BK_TREE_MAP:
        BK_TREE_MAP[namespace] = BKTree(hamming_distance)
        BK_TREE_RELPATHS[namespace] = {}
    hash_obj = hex_to_hash(hash_str)
    BK_TREE_MAP[namespace].add(hash_obj)
    BK_TREE_RELPATHS[namespace][str(hash_obj)] = rel_path


def find_similar_in_namespace(namespace, target_hash, max_distance=10, top_n=None):
    if namespace not in BK_TREE_MAP:
        return []
    if isinstance(target_hash, str):
        target_hash = hex_to_hash(target_hash)
    results = BK_TREE_MAP[namespace].find(target_hash, max_distance)
    filtered = [
        (BK_TREE_RELPATHS[namespace].get(str(item)), distance)
        for distance, item in results
        if str(item) in BK_TREE_RELPATHS[namespace]
    ]
    return filtered[:top_n] if top_n else filtered


class HashIndex:
    """
    Maintains a persistent perceptual hash index for icon files.

    Supports incremental updates, pruning stale entries, and similarity search.
    """

    def __init__(
        self,
        base_dir,
        hasher,
        output_file="hash_index.json",
        recursive=True,
        match_size=(32, 32),
    ):
        # print(f"[HashIndex] base_dir: {base_dir}, hasher: {hasher}, output_file: {output_file}, recursive: {recursive}, match_size: {match_size}")
        self.base_dir = Path(base_dir)
        # print(f"[HashIndex] base_dir: {self.base_dir}")
        # print(f"[HashIndex] output_file: {self.base_dir / output_file}")
        self.hasher_name = None

        hasher_key = hasher.lower()

        try:
            self.hasher = HASHER_FACTORY[hasher_key]()
            self.hasher_name = hasher_key
        except KeyError as e:
            raise HashIndexError(f"Unknown hasher '{hasher_key}'") from e

        self.output_file = self.base_dir / output_file
        self.recursive = recursive
        self.match_size = match_size

        self.hashes = {}  # rel_path -> {"hash": str, "mtime": float}

        self._load_cache()

    def _load_cache(self):
        if not self.output_file.exists():
            logger.info(f"No existing hash index at {self.output_file}")
            raise HashIndexNotFoundError(
                f"No existing hash index at {self.output_file}"
            )

        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            cached_hasher = data.get("hasher")

            if cached_hasher != self.hasher_name:
                logger.info(
                    f"Hash method changed from '{cached_hasher}' to '{self.hasher_name}'; discarding old index."
                )
                return

            self.hashes = data.get("hashes", {})

            logger.verbose(
                f"Loaded hash index from {self.output_file} with {len(self.hashes)} entries."
            )

            for rel_path, entry in self.hashes.items():
                try:
                    hash_obj = hex_to_hash(entry["hash"])
                    # self.bktree.add(hash_obj)
                    add_to_bktree(self.hasher_name, entry["hash"], rel_path)
                    # self.bktree_map[hash_obj] = rel_path
                except Exception as e:
                    logger.warning(f"Failed to rehydrate BKTree for {rel_path}: {e}")
                    raise HashIndexError(
                        f"Failed to rehydrate BKTree for {rel_path}: {e}"
                    ) from e
        except Exception as e:
            logger.warning(f"Failed to load hash index: {e}")
            raise HashIndexError("Failed to load hash index") from e

    def _save_cache(self):
        try:
            out = {
                "hasher": self.hasher_name,
                "generated": datetime.utcnow().isoformat(),
                "hashes": self.hashes,
            }
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            logger.info(
                f"Saved hash index to {self.output_file} with {len(self.hashes)} entries."
            )
        except Exception as e:
            logger.error(f"Failed to write hash index: {e}")
            raise HashIndexError("Failed to write hash index") from e

    def build_or_update(self):
        pattern = "**/*.png" if self.recursive else "*.png"
        found_files = set()
        updated = 0

        for path in self.base_dir.glob(pattern):
            rel_path = str(path.relative_to(self.base_dir))
            found_files.add(rel_path)

            try:
                mtime = os.path.getmtime(path)
                entry = self.hashes.get(rel_path)
                if entry and abs(entry["mtime"] - mtime) < 1:
                    continue

                with open(path, "rb") as f:
                    data = f.read()
                    hash_val = self.hasher.compute(data)
                self.hashes[rel_path] = {"hash": hash_val, "mtime": mtime}
                updated += 1
                logger.verbose(f"Updated hash for {rel_path}")

            except Exception as e:
                logger.warning(f"Failed to hash {rel_path}: {e}")
                raise HashIndexError(f"Failed to hash {rel_path}: {e}") from e

        stale_keys = set(self.hashes.keys()) - found_files
        for key in stale_keys:
            del self.hashes[key]
            logger.verbose(f"Removed stale hash entry: {key}")

        self._save_cache()
        logger.info(
            f"Hash index update complete: {updated} updated, {len(stale_keys)} removed, {len(self.hashes)} total."
        )

    def build_with_overlays(self, overlays: dict):
        """
        Apply each overlay to each icon and compute perceptual hashes.

        Args:
            overlays (dict): Mapping of quality label (e.g., 'ultra') to RGBA overlay images (numpy arrays).
        """
        pattern = "**/*.png" if self.recursive else "*.png"
        updated = 0
        found_keys = set()

        for path in self.base_dir.glob(pattern):
            rel_path = str(path.relative_to(self.base_dir))
            try:
                mtime = os.path.getmtime(path)
                image_bgr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                if image_bgr is None or image_bgr.shape[2] < 3:
                    logger.warning(f"Failed to load or incomplete image: {rel_path}")
                    continue

                for quality, overlay in overlays.items():
                    blended = apply_overlay(image_bgr[:, :, :3], overlay)

                    masked = apply_mask(blended)

                    _, buf = cv2.imencode(".png", masked)
                    hash_val = self.hasher.compute(
                        buf.tobytes(), size=self.match_size, grayscale=False
                    )
                    key = f"{rel_path}::{quality}"
                    self.hashes[key] = {"hash": hash_val, "mtime": mtime}
                    found_keys.add(key)
                    updated += 1
                    logger.verbose(f"Hashed {key}")
            except Exception as e:
                logger.warning(f"Failed to hash overlays for {rel_path}: {e}")
                raise HashIndexError(
                    f"Failed to hash overlays for {rel_path}: {e}"
                ) from e

        all_existing = set(self.hashes.keys())
        stale_keys = all_existing - found_keys
        for key in stale_keys:
            del self.hashes[key]
            logger.verbose(f"Pruned stale entry: {key}")

        self._save_cache()
        logger.info(f"Overlay hash update complete: {updated} entries added/updated.")

    def get(self, rel_path):
        entry = self.hashes.get(rel_path)
        return entry["hash"] if entry else None

    def all_hashes(self):
        return {k: v["hash"] for k, v in self.hashes.items()}

    def find_similar(self, target_hash, max_distance=10, top_n=None):
        return find_similar_in_namespace(
            self.hasher_name, target_hash, max_distance, top_n
        )

    def find_similar_to_image(
        self, roi_bgr, max_distance=20, top_n=None, size=None, grayscale=False
    ):
        """
        Compute the perceptual hash of the ROI and return matching icons within max Hamming distance.

        Args:
            roi_bgr (np.ndarray): Target region (BGR format) as a numpy array.
            max_distance (int): Max Hamming distance to accept as similar.
            top_n (int, optional): Limit the number of results.

        Returns:
            list of (rel_path, distance): Paths relative to the base dir, sorted by increasing distance.
        """
        if roi_bgr is None or roi_bgr.size == 0:
            raise HashIndexError("ROI image is empty or invalid")

        if size is None:
            size = self.match_size

        try:
            rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB)

            masked = apply_mask(rgb)

            if grayscale:
                masked = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)

            resized = cv2.resize(masked, size, interpolation=cv2.INTER_AREA)
            pil_img = Image.fromarray(resized)
            target_hash = imagehash.phash(pil_img)
            pil_img.close()
        except Exception as e:
            raise HashIndexFindError("Failed to prepare image for hashing") from e

        # print(f"Target hash: {target_hash}, max_distance: {max_distance}, top_n: {top_n}")
        return self.find_similar(target_hash, max_distance=max_distance, top_n=top_n)
