import os
import logging
import json
import imagehash
import hashlib

import cv2
import numpy as np

from pathlib import Path
from datetime import datetime
from PIL import Image
from pybktree import BKTree
from imagehash import hex_to_hash

from ..exceptions import HashIndexError, HashIndexNotFoundError
from ..utils.image import apply_overlay, apply_mask, map_mask_type, show_image

logger = logging.getLogger(__name__)

def get_pil_image(image, size=(32, 32), grayscale=False):
    """
    Get a PIL image, sized and ready for hashing

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
            # single-channel grayscale -> convert to BGR so later steps are uniform
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

    # 2) Convert BGR->RGB
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # 3) Optionally force grayscale
    if grayscale:
        # if it’s already gray after cvtColor above, this is a no-op
        rgb = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # 4) Resize to target size
    resized = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)

    # 5) Get PIL image
    pil_img = Image.fromarray(resized)
    return pil_img

def compute_phash(image, size=(32, 32), grayscale=False):
    pil_img = get_pil_image(image, size, grayscale)
    return str(imagehash.phash(pil_img))

def compute_dhash(image, size=(32, 32), grayscale=False):
    pil_img = get_pil_image(image, size, grayscale)
    return str(imagehash.dhash(pil_img))


HASH_TYPES = {
    "phash": compute_phash,
    # "ahash": AHashHasher,  # If you add more
    "dhash": compute_dhash,
}


def hamming_distance(h1, h2):
    return h1 - h2

def tuple_hamming_distance(t1, t2):
    return hamming_distance(t1[0], t2[0])

BK_TREE_MAP = {}
BK_TREE_RELPATHS = {}


def add_to_bktree(namespace, hash_str, rel_path, item):
    if namespace not in BK_TREE_MAP:
        BK_TREE_MAP[namespace] = BKTree(tuple_hamming_distance)
        BK_TREE_RELPATHS[namespace] = {}
    hash_obj = hex_to_hash(hash_str)
    BK_TREE_MAP[namespace].add((hash_obj, item))
    BK_TREE_RELPATHS[namespace][str(hash_obj)] = rel_path


def item_matches(item: dict, filters: dict) -> bool:
    """
    Return True iff `item` (a metadata dict) satisfies the key→value filters.
    """
    for key, raw_val in (filters or {}).items():
        val = item.get(key)

        # explicit None filter: only include items where val is None
        if raw_val is None:
            if val is not None:
                return False
            continue

        # normalize the filter values into a list
        if isinstance(raw_val, str):
            parts = [p.strip() for p in raw_val.split(',') if p.strip()]
        elif isinstance(raw_val, (list, tuple)):
            parts = list(raw_val)
        else:
            parts = [raw_val]

        # split into inclusions and exclusions
        includes = [p for p in parts if not (isinstance(p, str) and p.startswith('!'))]
        excludes = [p[1:] for p in parts if isinstance(p, str) and p.startswith('!')]

        # if we have any includes, val must be one of them
        if includes and val not in includes:
            return False
        # if we have any excludes, val must _not_ be any of them
        if excludes and val in excludes:
            return False

    return True


def find_similar_in_namespace(
    namespace: str,
    target_hash: str | bytes,
    max_distance: int = 10,
    top_n: int | None = None,
    filters: dict | None = None,
) -> list[tuple[str, int, list[dict]]]:
    """
    Return up to top_n items whose hash is within max_distance of target_hash,
    filtered by metadata if `filters` is given.

    Each result is (rel_path, distance, metadata_list), where metadata_list
    contains all metadata dicts attached to that same hash.
    """
    if namespace not in BK_TREE_MAP:
        return []

    # normalize the incoming hash
    if isinstance(target_hash, str):
        target_hash = hex_to_hash(target_hash)

    # query the BK-tree; every `item` comes back as (hash_obj, entry_dict)
    raw_results = BK_TREE_MAP[namespace].find((target_hash, None), max_distance)

    # aggregate by hash_str -> {relpath, distance, [metadata, ...]}
    agg: dict[str, dict] = {}
    for distance, (hash_obj, entry_dict) in raw_results:
        key = str(hash_obj)
        relpath = BK_TREE_RELPATHS[namespace].get(key)
        if relpath is None:
            continue

        # the metadata you stored under "data"
        metadata = entry_dict.get("data", {})

        # if filters provided, drop metadata entries that don't match
        if filters and not item_matches(metadata, filters):
            continue

        agg_key = entry_dict["md5_hash"]

        if agg_key not in agg:
            agg[agg_key] = {
                "relpath": relpath,
                "distance": distance,
                "metadatalist": []
            }
        
        # avoid duplicate metadata by image_path
        existing = agg[agg_key]["metadatalist"]
        current_path = metadata.get("image_path")
        if current_path is None or all(md.get("image_path") != current_path for md in existing):
            existing.append(metadata)
        # else: skip adding duplicate image_path

    # build the final list of tuples
    out: list[tuple[str, int, list[dict]]] = [
        (info["relpath"], info["distance"], info["metadatalist"])
        for info in agg.values()
    ]

    # already roughly in ascending distance order; trim if needed
    if top_n is not None:
        out = out[:top_n]

    return out

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
        metadata_map: dict = None,
    ):
        self.base_dir = Path(base_dir)

        self.output_file = self.base_dir / output_file
        self.image_cache_file = self.base_dir / "image_cache.json"
        self.recursive = recursive
        self.match_size = match_size

        # rel_path -> {"hash": str, "mtime": float, "data": {...}}
        self.hashes = {}

        self.metadata_map = metadata_map or {}

        self._load_cache()

    def _load_cache(self):
        if not self.output_file.exists():
            logger.info(f"No existing hash index at {self.output_file}")
            return

        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.hashes = data.get("hashes", {})

            logger.verbose(
                f"Loaded hash index from {self.output_file} with {len(self.hashes)} entries."
            )

            for rel_path, entry in self.hashes.items():
                try:
                    add_to_bktree("phash", entry["phash"], rel_path, entry)
                    add_to_bktree("dhash", entry["dhash"], rel_path, entry)
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

    def _load_image_cache(self):
        try:
            with open(self.image_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # data looks like this: [
            #   {
            #     "file": "Counter-Command_Exo-Armor.png",
            #     "cargo": "equipment",
            #     "filters": {
            #       "type": "Body Armor"
            #     },
            #     "name": "Counter-Command Exo-Armor Mk XII",
            #     "cleaned_name": "Counter-Command Exo-Armor"
            #   },
            # ]
            #
            # we want to convert this to a dict with the file as the key and the rest as the value
            self.image_cache = {}
            for entry in data:
                self.image_cache[entry["file"]] = entry


            logger.verbose(
                f"Loaded image cache from {self.image_cache_file} with {len(self.image_cache)} entries."
            )

        except Exception as e:
            logger.warning(f"Failed to load image cache: {e}")
            raise HashIndexError("Failed to load image cache") from e

    def build_or_update(self):
        """Build or update the hash index."""

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
                    phash_val = self.compute_phash(data)
                    dhash_val = self.compute_dhash(data)
                # self.hashes[rel_path] = {"hash": hash_val, "mtime": mtime}
                # determine image category from parent folder name
                category = Path(rel_path).parent.name

                # merge any user-supplied metadata with the category
                metadata = dict(self.metadata_map.get(rel_path, {}))
                metadata["image_category"] = category

                entry_data = {
                    "phash":  phash_val,
                    "dhash":  dhash_val,
                    "mtime": mtime,
                    "data":  metadata,
                }
                self.hashes[rel_path] = entry_data
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
        Apply each overlay to each icon, compute perceptual hashes,
        and record an MD5 checksum of the original file.
        """
        pattern = "**/*.png" if self.recursive else "*.png"
        updated = 0
        found_keys = set()

        self._load_image_cache()

        for path in self.base_dir.glob(pattern):
            rel_path = str(path.relative_to(self.base_dir))
            try:
                mtime = os.path.getmtime(path)

                # Read the file once into memory
                file_bytes = path.read_bytes()
                file_md5   = hashlib.md5(file_bytes).hexdigest()

                # Build NumPy buffer for OpenCV from the same bytes
                data      = np.frombuffer(file_bytes, dtype=np.uint8)
                image_bgr = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
                if image_bgr is None or image_bgr.shape[2] < 3:
                    logger.warning(f"Failed to load or incomplete image: {rel_path}")
                    continue

                for overlay_name, overlay_image in overlays.items():
                    key = f"{rel_path}::{overlay_name}"
                    filename = Path(rel_path).name
                    category = Path(rel_path).parent.as_posix()

                    metadata = dict(self.metadata_map.get(rel_path, {}))
                    metadata.update({
                        "image_category":  category,
                        "image_path":      rel_path,
                        "image_filename":  filename,
                        "overlay_name":    overlay_name,
                        "cargo_type":      self.image_cache.get(filename, {}).get("cargo", ""),
                        "cargo_item_name": self.image_cache.get(filename, {}).get("name", ""),
                        "cargo_filters":   self.image_cache.get(filename, {}).get("filters", {}),
                        "item_name":       self.image_cache.get(filename, {}).get("cleaned_name", ""),
                    })

                    # decide mask_type
                    metadata["mask_type"] = map_mask_type(category)

                    blended = apply_overlay(image_bgr[:, :, :3], overlay_image)
                    masked  = apply_mask(blended.copy(), metadata["mask_type"])
                    _, buf = cv2.imencode(".png", masked)
                    
                    phash_val = compute_phash(buf.tobytes(),
                                           size=self.match_size,
                                           grayscale=False)

                    dhash_val = compute_dhash(buf.tobytes(),
                                           size=self.match_size,
                                           grayscale=False)


                    # if filename == 'Maquis_Tactics.png':
                    #     print(f"{key}: {phash_val} {dhash_val}")
                    #     show_image([blended, masked])

                    entry_data = {
                        "phash":     phash_val,
                        "dhash":     dhash_val,
                        "mtime":    mtime,
                        "md5_hash": file_md5,
                        "data":     metadata,
                    }

                    self.hashes[key] = entry_data
                    found_keys.add(key)
                    updated += 1
                    logger.verbose(f"Hashed {key}")
            except Exception as e:
                logger.warning(f"Failed to hash overlays for {rel_path}: {e}")
                raise HashIndexError(
                    f"Failed to hash overlays for {rel_path}: {e}"
                ) from e

        # prune stale
        stale = set(self.hashes) - found_keys
        for key in stale:
            del self.hashes[key]
            logger.verbose(f"Pruned stale entry: {key}")

        self._save_cache()
        logger.info(f"Overlay hash update complete: {updated} entries added/updated.")

    def get(self, rel_path):
        entry = self.hashes.get(rel_path)
        return entry["hash"] if entry else None

    def all_hashes(self):
        return {k: v["hash"] for k, v in self.hashes.items()}

    def get_hash(self, hash_type, roi_bgr, icon_group_label, slot_idx, mask_type, size=None, grayscale=False):
        """
        Compute the perceptual hash of the ROI.

        Args:
            roi_bgr (np.ndarray): Target region (BGR format) as a numpy array.

        Returns:
            str: Hex string of the computed hash.
        """
        hasher = None
        if hash_type in HASH_TYPES:
            hasher = HASH_TYPES[hash_type]
        else:
            raise HashIndexError(f"Unknown hash type: {hash_type}")

        target_hash = None

        if roi_bgr is None or roi_bgr.size == 0:
            raise HashIndexError("ROI image is empty or invalid")

        if size is None:
            size = self.match_size

        try:
            masked = apply_mask(roi_bgr, mask_type)
            
            target_hash = hasher(masked, size=size, grayscale=grayscale)
        except Exception as e:
            raise HashIndexFindError("Failed to prepare image for hashing") from e

        # print(f"Target hash: {target_hash}, max_distance: {max_distance}, top_n: {top_n}")
        return str(target_hash)

    def find_similar(self, hash_type, target_hash, max_distance=10, top_n=None, filters=None):
        if hash_type not in HASH_TYPES:
            raise HashIndexError(f"Unknown hash type: {hash_type}")

        return find_similar_in_namespace(
            hash_type, target_hash, max_distance, top_n, filters
        )

    def find_similar_to_image(
        self, hash_type, target_hash, max_distance=20, top_n=None, size=None, grayscale=False, filters=None
    ):
        """
        Compute the perceptual hash of the ROI and return matching icons within max Hamming distance.

        Args:
            target_hash (str): Hex string of the target hash.
            max_distance (int): Max Hamming distance to accept as similar.
            top_n (int, optional): Limit the number of results.

        Returns:
            list of (rel_path, distance): Paths relative to the base dir, sorted by increasing distance.
        """

        # print(f"Target hash: {target_hash}, max_distance: {max_distance}, top_n: {top_n}")
        #print(f"filter: {filter}") 
        return self.find_similar(hash_type, target_hash, max_distance=max_distance, top_n=top_n, filters=filters)
