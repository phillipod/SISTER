from pathlib import Path
from typing import (
    Mapping, Iterable, List, Optional, Dict
)

class IconDirectoryMap:
    """
    Encapsulates multiple icon_sets, each mapping region_label → list[Path].
    Implements .get and __getitem__ so it can be passed directly to existing engine code.
    """
    def __init__(
        self,
        nested: Mapping[str, Mapping[str, Iterable[Path]]],
        default_set: Optional[str] = None
    ) -> None:
        # Normalize and resolve all folder paths once up-front
        self._mapping: Dict[str, Dict[str, List[Path]]] = {}

        print(f"Resolving {len(nested)} icon_sets"
              f" (nested: {nested})")
        for set_name, regions in nested.items():
            resolved: Dict[str, List[Path]] = {}
            print(f"Resolving {len(regions)} folders for icon_set '{set_name}'"
                  f" (regions: {regions})")

            for region_label, folders in regions.items():
                resolved[region_label] = [Path(p).resolve() for p in folders]
            self._mapping[set_name] = resolved

        # Pick a default set
        if default_set is None:
            try:
                default_set = next(iter(self._mapping))
            except StopIteration:
                raise ValueError("IconDirectoryMap requires at least one icon_set")
        if default_set not in self._mapping:
            raise KeyError(f"Unknown default_set '{default_set}'")
        self._current_set = default_set

    def sets(self) -> List[str]:
        """List all available icon_set names."""
        return list(self._mapping.keys())

    def set(self, set_name: str) -> None:
        """Change which icon_set is active for subsequent calls to .get/.allowed_dirs."""
        if set_name not in self._mapping:
            raise KeyError(f"Unknown icon_set '{set_name}'")
        self._current_set = set_name

    def allowed_dirs(
        self,
        region_label: str,
        icon_set: Optional[str] = None
    ) -> List[Path]:
        """
        Return the list of directories for `region_label` in the given set.
        If no folders configured, returns an empty list.
        """
        key = icon_set or self._current_set
        return list(self._mapping.get(key, {}).get(region_label, []))

    def is_allowed(
        self,
        region_label: str,
        file_path: Path,
        icon_set: Optional[str] = None
    ) -> bool:
        """
        True if `file_path` is under any of the allowed_dirs for region_label.
        """
        file_path = Path(file_path).resolve()
        for folder in self.allowed_dirs(region_label, icon_set):
            if folder == file_path or folder in file_path.parents:
                return True
        return False

    # --- Mapping-like interface so existing code still works unchanged ---
    def get(self, region_label: str, default=None):
        """
        .get(key, default) returns the same as dict.get:
          * if key in current_set, returns list[Path]
          * else returns default
        """
        dirs = self.allowed_dirs(region_label)
        return dirs if dirs else default

    def __getitem__(self, region_label: str) -> List[Path]:
        """icon_dir_map[region_label] → list of Path (empty list if none)."""
        return self.allowed_dirs(region_label)

    def region_map(self, icon_set: Optional[str] = None) -> Dict[str, List[Path]]:
        """
        Return a brand-new dict of region_label → folders for the chosen set.
        Perfect for filtering down to just the labels you detected:
            labels = ctx.regions.keys()
            raw = icon_map.region_map()
            filtered = {L: raw[L] for L in labels if L in raw}
        """
        key = icon_set or self._current_set
        return dict(self._mapping.get(key, {}))
