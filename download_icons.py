import argparse

from src.cargo import CargoDownloader
from pathlib import Path

from log_config import setup_logging

def main():
    """
    Main function to download and organize icons for equipment, personal traits,
    and starship traits using CargoDownloader.
    """
    parser = argparse.ArgumentParser(description="Download icons for equipment, personal traits, and starship traits from STO wiki.")
    parser.add_argument("--log-level", default="WARNING", help="Set log level: DEBUG, VERBOSE, INFO, WARNING, ERROR.")
    args = parser.parse_args()
    setup_logging(log_level=args.log_level)

    images_root = Path('images')
    image_cache_path = images_root / "image_cache.json"

    downloader = CargoDownloader()
    downloader.download_all()

    types = downloader.get_unique_equipment_types()
    print("Unique equipment types found:")
    for t in types:
        print(f" - {t}")

    # Define all mappings as a list of tuples: (cargo_type, filters, subdirectory)
    download_mappings = [
        # Equipment types
        ('equipment', {'type': 'Body Armor'}, 'ground/armor'),
        ('equipment', {'type': 'Personal Shield'}, 'ground/shield'),
        ('equipment', {'type': 'EV Suit'}, 'ground/ev_suit'),
        ('equipment', {'type': 'Kit Module'}, 'ground/kit_module'),
        ('equipment', {'type': 'Kit'}, 'ground/kit'),
        ('equipment', {'type': 'Ground Weapon'}, 'ground/weapon'),
        ('equipment', {'type': 'Ground Device'}, 'ground/device'),
        ('equipment', {'type': 'Ship Deflector Dish'}, 'space/deflector'),
        ('equipment', {'type': 'Ship Secondary Deflector'}, 'space/secondary_deflector'),
        ('equipment', {'type': 'Ship Shields'}, 'space/shield'),
        ('equipment', {'type': 'Ship Vanity Shield'}, 'space/vanity_shield'),
        ('equipment', {'type': 'Experimental Weapon'}, 'space/weapons/experimental'),
        ('equipment', {'type': 'Ship Weapon'}, 'space/weapons/unrestricted'),
        ('equipment', {'type': 'Ship Aft Weapon'}, 'space/weapons/aft'),
        ('equipment', {'type': 'Ship Fore Weapon'}, 'space/weapons/fore'),
        ('equipment', {'type': 'Universal Console'}, 'space/consoles/universal'),
        ('equipment', {'type': 'Ship Engineering Console'}, 'space/consoles/engineering'),
        ('equipment', {'type': 'Ship Tactical Console'}, 'space/consoles/tactical'),
        ('equipment', {'type': 'Ship Science Console'}, 'space/consoles/science'),
        ('equipment', {'type': 'Impulse Engine'}, 'space/impulse'),
        ('equipment', {'type': 'Warp Engine'}, 'space/warp'),
        ('equipment', {'type': 'Singularity Engine'}, 'space/singularity'),
        ('equipment', {'type': 'Hangar Bay'}, 'space/hangar'),
        ('equipment', {'type': 'Ship Device'}, 'space/device'),

        # Personal traits
        ('personal_trait', {'environment': 'ground', 'chartype': 'char'}, 'ground/traits/personal'),
        ('personal_trait', {'environment': 'ground', 'type': 'reputation', 'chartype': 'char'}, 'ground/traits/reputation'),
        ('personal_trait', {'environment': 'ground', 'type': 'activereputation', 'chartype': 'char'}, 'ground/traits/active_reputation'),
        ('personal_trait', {'environment': 'space', 'chartype': 'char'}, 'space/traits/personal'),
        ('personal_trait', {'environment': 'space', 'type': 'reputation', 'chartype': 'char'}, 'space/traits/reputation'),
        ('personal_trait', {'environment': 'space', 'type': 'activereputation', 'chartype': 'char'}, 'space/traits/active_reputation'),

        # Starship traits (no filters)
        ('starship_trait', None, 'space/traits/starship')
    ]

    # Download all icons in one loop
    for cargo_type, filters, subdir in download_mappings:
        dest_dir = images_root / subdir
        downloader.download_icons(cargo_type, dest_dir, image_cache_path, filters)

if __name__ == "__main__":
    main()
