import json
import os
import time
import re
import html
from datetime import datetime, timedelta
from pathlib import Path
import requests

from ..exceptions import CargoError, CargoCacheIOError, CargoDownloadError

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import logging

logger = logging.getLogger(__name__)

# === Constants ===
WIKI_BASE_URL = "https://stowiki.net/wiki/"
CARGO_EXPORT_PAGE = "Special:CargoExport"
FILE_PATH_BASE = "https://stowiki.net/wiki/Special:FilePath/"

DEFAULT_CACHE_DIR = Path(os.path.expanduser("~")) / ".sto-cargo-cache"
CACHE_EXPIRE_DAYS = 3

CARGO_TYPES = {
    "equipment": {
        "tables": "Infobox",
        "fields": "_pageName=Page,name,rarity,type,boundto,boundwhen,who,"
        + ",".join(
            f"{prefix}{i}"
            for prefix in ("head", "subhead", "text")
            for i in range(1, 10)
        ),
        "limit": 5000,
    },
    "personal_trait": {
        "tables": "Traits",
        "fields": "_pageName=Page,name,chartype,environment,type,isunique,description",
        "limit": 2500,
    },
    "starship_trait": {
        "tables": "StarshipTraits",
        "fields": "_pageName=Page,name,short,type,detailed,obtained,basic",
        "limit": 2500,
        "where": "name IS NOT NULL",
    },
    "doff": {
        "tables": "Specializations",
        "fields": "_pageName=Page,name=doff_specialization,shipdutytype,department,description,white,green,blue,purple,violet,gold",
        "limit": 1000,
    },
}

# Normalization rules per cargo type and field
NORMALIZATION_RULES = {
    "equipment": {
        "type": {
            "Ground Ability": "Ground Device",
            "Ground Armor": "Body Armor",
            "Kit Modules": "Kit Module",
            "Sniper Rifle": "Ground Weapon",
            "inventory": "Inventory",
            "Consumable": "Inventory",
        }
    },
}


class CargoDownloader:
    """
    Class responsible for downloading, caching, normalizing, and managing STO wiki Cargo data and associated item icons.
    """

    def __init__(self, force_download=False, cache_dir=None):
        """
        Initialize the CargoDownloader.

        Args:
            force_download (bool): If True, bypasses cache and forces fresh downloads.
            cache_dir (str or Path): Optional custom path for cache directory.
            verbose (bool): If True, enables console output for progress.
        """
        self.force_download = force_download
        self.cache_dir = (
            Path(cache_dir).expanduser() if cache_dir else DEFAULT_CACHE_DIR
        )

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using cache directory: {self.cache_dir}")

    def build_url(self, cargo_type, offset=0):
        """
        Construct the CargoExport API URL for the specified cargo type and result offset.

        Args:
            cargo_type (str): The cargo type to query (e.g., 'equipment').
            offset (int): Offset for paginated results.

        Returns:
            str: Full API URL to request data.
        """
        config = CARGO_TYPES[cargo_type]
        params = [
            f"tables={config['tables']}",
            f"fields={config['fields']}",
            f"limit={config['limit']}",
            f"offset={offset}",
            "format=json",
        ]
        if "where" in config:
            params.append(f"where={config['where']}")
        return WIKI_BASE_URL + CARGO_EXPORT_PAGE + "?" + "&".join(params)

    def cache_file(self, cargo_type):
        """
        Generate the cache file path for the given cargo type.

        Args:
            cargo_type (str): The cargo type.

        Returns:
            Path: Path object pointing to the expected cache file.
        """
        return self.cache_dir / f"{cargo_type}.json"

    def is_cache_valid(self, path):
        """
        Check whether a given cache file is still valid based on expiration settings.

        Args:
            path (Path): Path to the cache file.

        Returns:
            bool: True if cache file is still valid, False otherwise.
        """
        if not path.exists():
            return False
        return datetime.fromtimestamp(
            path.stat().st_mtime
        ) > datetime.now() - timedelta(days=CACHE_EXPIRE_DAYS)

    def normalize_item(self, cargo_type, item):
        """
        Normalize individual item fields based on predefined rules.

        Args:
            cargo_type (str): The type of cargo.
            item (dict): The item data to normalize.
        """
        normalization = NORMALIZATION_RULES.get(cargo_type, {})
        for field, field_map in normalization.items():
            original_value = item.get(field)
            if original_value in field_map:
                item[field] = field_map[original_value]

    def download(self, cargo_type):
        """
        Download and cache data for a specific cargo type.

        Args:
            cargo_type (str): The type of cargo to download.

        Raises:
            Exception: If HTTP request fails.
        """
        path = self.cache_file(cargo_type)
        if not self.force_download and self.is_cache_valid(path):
            logger.verbose(f"Using cached {cargo_type} data.")
            return

        logger.info(f"Downloading {cargo_type} data...")

        all_data = []
        offset = 0
        while True:
            url = self.build_url(cargo_type, offset)
            batch = None

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                batch = response.json()
            except (ValueError, json.JSONDecodeError) as e:
                raise CargoError(f"Invalid JSON for {cargo_type}") from e
            except Exception as e:
                raise CargoDownloadError(
                    f"Network error downloading {cargo_type}"
                ) from e

            if not batch:
                break

            for item in batch:
                self.normalize_item(cargo_type, item)

            all_data.extend(batch)

            if len(batch) < CARGO_TYPES[cargo_type]["limit"]:
                break

            offset += CARGO_TYPES[cargo_type]["limit"]
            time.sleep(1)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)

    def download_all(self):
        """
        Download and cache all supported cargo types defined in CARGO_TYPES.
        """
        for cargo_type in CARGO_TYPES:
            self.download(cargo_type)

    def load(self, cargo_type):
        """
        Load cached data for a given cargo type.

        Args:
            cargo_type (str): The type of cargo to load.

        Returns:
            list: Parsed list of cargo data from the JSON cache.

        Raises:
            FileNotFoundError: If cache file is missing.
        """
        path = self.cache_file(cargo_type)
        if not path.exists():
            raise FileNotFoundError(f"No cached file found for {cargo_type}")
        # with open(path, 'r', encoding='utf-8') as f:
        #     return json.load(f)

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as e:
            raise CargoCacheIOError(f"Cache file not found for {cargo_type}") from e
        except json.JSONDecodeError as e:
            raise CargoCacheIOError(f"Cache file corrupted for {cargo_type}") from e
        except (OSError, Exception) as e:
            raise CargoCacheIOError(
                f"Failed to read cache file for {cargo_type}"
            ) from e

    def get_unique_equipment_types(self):
        """
        Get a sorted list of all unique 'type' values in the equipment cargo.

        Returns:
            list: Sorted list of unique equipment types.
        """
        equipment_data = self.load("equipment")
        types = {item.get("type") for item in equipment_data if item.get("type")}
        return sorted(types)

    def download_icons(self, cargo_type, dest_dir, image_cache_path, filters=None, on_progress=None):
        """
        Download icons for cargo entries of the specified type.

        Args:
            cargo_type (str): The cargo type (e.g., 'equipment').
            dest_dir (str or Path): Directory to save the icons.
            image_cache_path (Path): JSON cache file for already downloaded icons.
            filters (dict, optional): Optional filters to restrict items.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        data = self.load(cargo_type)

        def item_matches(item):
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

        matching_items = [item for item in data if item_matches(item)]

        logger.info(
            f"Downloading {len(matching_items)} {cargo_type} icons into {dest_dir}..."
        )

        self._download_icons(
            matching_items, dest_dir, image_cache_path, cargo_type, filters, on_progress=on_progress
        )

    def _download_icons(
        self, items, dest_dir, image_cache_path, cargo_type=None, filters=None, on_progress=None
    ):
        """
        Internal function to handle threaded downloading of icon images.

        Args:
            items (list): List of items to download icons for.
            dest_dir (Path): Destination directory for saved icons.
            image_cache_path (Path): Path to the icon metadata cache.
            cargo_type (str, optional): Optional cargo type label.
            filters (dict, optional): Optional filters for metadata.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        cache_lock = threading.Lock()

        with cache_lock:
            if image_cache_path.exists():
                # with image_cache_path.open("r", encoding="utf-8") as f:
                #    cache_entries = json.load(f)
                try:
                    with image_cache_path.open("r", encoding="utf-8") as f:
                        cache_entries = json.load(f)
                except (OSError, json.JSONDecodeError) as e:
                    # either unreadable or invalid JSON
                    raise CargoCacheIOError("Failed to read icon metadata cache") from e

            else:
                cache_entries = []

        existing_files = {entry["file"] for entry in cache_entries}

        def download_single_icon(item):
            """Download a single icon file."""
            raw_name = item.get("name")
            if not raw_name:
                return

            name_unescaped = html.unescape(html.unescape(raw_name))
            cleaned_name = re.sub(
                r"\s*(∞)\s*", "", name_unescaped, flags=re.IGNORECASE
            ).strip()
            cleaned_name = re.sub(r"(\s*\[[^\]]+\](x\d+)*)+$", "", cleaned_name).strip()
            cleaned_name = re.sub(
                r"\s*(Mk [IVXLCDM]+)$", "", cleaned_name, flags=re.IGNORECASE
            ).strip()
            cleaned_name = re.sub(r"[\/\\:\*\?\"\<\>\|]", "_", cleaned_name).strip()

            filename = cleaned_name.replace(" ", "_") + ("_(" + item["faction_suffix"] + ")" if "faction_suffix" in item else "") + ".png"
            url = FILE_PATH_BASE + cleaned_name.replace(" ", "_") + ("_(" + item["faction_suffix"] + ")" if "faction_suffix" in item else "") + "_icon.png"
            dest_path = dest_dir / filename

            local_counter = 0

            metadata = {
                "file": filename,
                "cargo": cargo_type if cargo_type else "",
                "filters": filters if filters else {},
                "name": raw_name,
                "cleaned_name": cleaned_name,
            }

            with cache_lock:
                if filename not in existing_files:
                    cache_entries.append(metadata)
                    existing_files.add(filename)
                    local_counter += 1

            if dest_path.exists():
                logger.verbose(f"  [Skip] {filename} already exists.")
                if local_counter > 0 and local_counter % 20 == 0:
                    with cache_lock:
                        self._write_image_cache(image_cache_path, cache_entries)
                return

            try:
                response = requests.get(url)
                if response.ok:
                    try:
                        with open(dest_path, "wb") as f:
                            f.write(response.content)
                    except Exception as e:
                        raise CargoCacheIOError(f"Failed to write {filename}") from e

                    logger.verbose(f"  [Downloaded] {filename}")
                else:
                    logger.verbose(f"  [Failed] {filename} ({response.status_code})")
            except Exception as e:
                logger.error(f"  [Error] {filename}: {e}")
                raise CargoDownloadError(f"Failed to download {filename}") from e

            if local_counter > 0 and local_counter % 20 == 0:
                with cache_lock:
                    self._write_image_cache(image_cache_path, cache_entries)

        download_items = []
        for item in items:
            if 'environment' in item and item['environment'] == 'space' and item['type'] in ("reputation", "activereputation"):
                download_items.append(item.copy()) # Base icon (Fed)
                
                item['faction_suffix'] = "Dominion"
                download_items.append(item.copy()) # Dominion icon

                item['faction_suffix'] = "Romulan"
                download_items.append(item.copy()) # Romulan icon

                item['faction_suffix'] = "Klingon"
                download_items.append(item.copy()) # Klingon icon
            else:
                download_items.append(item.copy())

        items = download_items

        #start_pct = 1.0
        #end_pct   = 99.0
        items_total     = len(items)
        items_completed = 0
        with ThreadPoolExecutor() as executor:
            try:
                futures = [
                    executor.submit(download_single_icon, item) for item in items
                ]
                for future in as_completed(futures):
                    items_completed += 1
                    
                    frac       = items_completed / items_total
                    sub = f"{items_completed}/{items_total}"

                    on_progress(f"Downloading icons -> {sub}", frac*100.0)
                    pass
            except KeyboardInterrupt:
                print("\n[Abort] Keyboard interrupt received, shutting down...")
                executor.shutdown(wait=True, cancel_futures=True)
                raise

        with cache_lock:
            self._write_image_cache(image_cache_path, cache_entries)

    def _write_image_cache(self, cache_path, entries):
        """
        Write downloaded icon metadata to cache.

        Args:
            cache_path (Path): Path to the icon cache file.
            entries (list): Metadata entries to write.
        """
        try:
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise CargoCacheIOError("Failed to write icon cache") from e
