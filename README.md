# SISTER (Screenshot Interrogation System for Traits and Equipment Recognition)

**SISTER** is a computer vision pipeline designed to detect and match equipment and trait icons within Star Trek Online (STO) screenshots. It automates OCR-based label detection, layout classification, icon slot extraction, and icon matching using a combination of perceptual hashing and SSIM for robust performance.

---

## 🚀 Features

- **OCR-based label detection** using EasyOCR with optional GPU acceleration.
- **Icon slot extraction** via contour analysis and heuristic filters.
- **Icon matching** leveraging:
  - **Perceptual Hash (phash/dhash) + BK-Tree prefilter** for fast candidate selection.
  - **SSIM (Structural Similarity Index) matching engine** for precise matching.
- **Quality overlay detection** (e.g., Epic, Rare overlays).
- **Layout classification** to handle different screenshot formats (PC and Console builds, Ship & Ground).
- **Auto-scaling and downsampling** support for high-resolution screenshots.
- **Extensible pipeline** with modular stages and tasks.
- **CLI interface** (`sister-cli`) with debugging, logging, and customizable configuration.
- **Tasks** to download STO Wiki icon assets and build a hash cache for pre-filtering.
- **Match summary export** as a text file

---

## 📦 Installation

### Downloadable MSI (Windows)

Windows users can download the latest MSI installer from the [GitHub Releases](https://github.com/phillipod/SISTER/releases) page. After downloading, run the installer to set up `sister-cli` on your system path.

### Install via pip (Cross-platform)

Clone the repository and install using pip. Note that the package is *not* published on PyPI and must be installed from source:

```bash
git clone https://github.com/phillipod/SISTER.git
cd SISTER
pip install .
```

Alternatively, if you already have the codebase locally (e.g., from a release ZIP), navigate to the root directory containing `pyproject.toml` and run:

```bash
pip install .
```

This will install the `sister_sto` package along with its console script entry point `sister-cli`.

---

## 📖 Usage

After installation, the primary entry point is the `sister-cli` command.

### Common Arguments

```text
--data-dir <path>       Directory for STO data (default: ~/.sister_sto)
--log-dir <path>        Directory to write log files (default: log under data-dir)
--icon-dir <path>       Directory for downloaded icon images (default: icons under data-dir)
--overlay-dir <path>    Directory for overlay images (default: overlays under data-dir)
--output-dir <path>     Directory to save match summary outputs (default: current working directory)
--log-level <level>     Logging level (DEBUG, INFO, WARNING, ERROR; default: WARNING)
--gpu                   Enable GPU support for OCR (EasyOCR)
--no-resize             Disable automatic downscaling of screenshots larger than 1920×1080
-s, --screenshot <paths>  Paths to one or more screenshot image files to process (required for matching)
-o, --output <prefix>   Output file prefix for saving match summary (default: stem of first screenshot)
--download              Download all icon assets from the STO Wiki (runs `download_all_icons` task and exits)
--build-hash-cache      Build/update the perceptual hash cache for all downloaded icons (runs `build_hash_cache` task and exits)
```

Below are common usage patterns:

#### 1. Download STO Wiki icon assets (optional)

By default, SISTER will lazily download icon assets as needed during matching. Lazy downloads occur on-the-fly—icons are fetched and cached so that subsequent runs do not re-download them. While this avoids a long initial download, it can slow down matching the first time an icon is needed.

Alternatively, you can pre-download all icon assets upfront to ensure the fastest matching performance and to avoid on-the-fly downloads. To download the latest icons and overlays from the STO Wiki, run:

```bash
sister-cli --download
```

This will fetch all relevant icons and store them under `--icon-dir` (defaults to `~/.sister_sto/icons`) and overlays under `--overlay-dir`. Note: downloading all icons can take a considerable amount of time, depending on your connection.
#### 2. Build the perceptual hash cache (optional)

A pre-built perceptual hash cache is provided with this release, so you do not need to update the cache for normal use. Only rebuild the cache when new icons are released or if you have added custom icons.

If you need to rebuild the cache, ensure that you have completed a full download of all icon assets (see step 1) so there are no missing icons. To rebuild, run:

```bash
sister-cli --build-hash-cache
```

The new cache will be stored under `--cache-dir` (defaults to `~/.sister_sto/cache`). You only need to run this when icons change; the provided cache is sufficient otherwise.
#### 3. Match icons in screenshots

Process one or more screenshots and generate a match summary:

```bash
sister-cli -s path/to/screenshot1.png path/to/screenshot2.jpg -o my_match_results
```

Options explained:
- `-s`/`--screenshot`: Provide one or more screenshot file paths.
- `-o`/`--output`: Specify the prefix for the output summary file. By default, uses the stem of the first screenshot.
- `--gpu`: Enable GPU for OCR (if supported).
- `--no-resize`: Keep original resolution (if you wish to skip downscaling).

**Windows users:** Be sure to run the command from `cmd.exe` or `powershell.exe`, and make sure you are in a directory where you want the output files to be stored. Otherwise, the output summary will be created in your current working directory.

---

## 🛠 Pipeline Overview

SISTER's core is built as a modular pipeline. The default pipeline (`build_default_pipeline`) orchestrates the following **Tasks** and **Stages**:

### Tasks

1. **app_init**  
   Initialize application directories, logging, and configurations.

2. **start_executor_pool**  
   Spin up a multiprocessing or thread pool to parallelize CPU-bound tasks (e.g., SSIM matching).

3. **stop_executor_pool**  
   Cleanly shut down the parallel executor pool after processing completes.

4. **download_all_icons**  
   Fetch icon files (and overlays) from the STO Wiki. Requires internet access.

5. **build_hash_cache**  
   Compute and store perceptual hashes (phash/dhash) for all icons. Speeds up the prefilter stage.


### Stages

1. **locate_labels** (`sister_sto/stages/locate_labels.py`)  
   Uses EasyOCR to detect and recognize text labels (e.g., equipment type labels) in the screenshot. Can leverage GPU with `--gpu`.

2. **classify_layout** (`sister_sto/stages/classify_layout.py`)  
   Classifies the overall build type or screenshot layout (e.g., PC vs. Console, Ship vs. Ground).

3. **locate_icon_groups** (`sister_sto/stages/locate_icon_groups.py`)  
   Determines groups of icon slots (e.g., equipment clusters) based on layout heuristics.

4. **locate_icon_slots** (`sister_sto/stages/locate_icon_slots.py`)  
   Identifies bounding boxes for individual icon slots using contour detection.

5. **prefilter_icons** (`sister_sto/stages/prefilter_icons.py`)  
   Quickly identifies candidate icons for each detected slot using perceptual hashing (configurable method: `hash` by default).

6. **load_icons** (`sister_sto/stages/load_icons.py`)  
   Loads icon images into memory for deeper matching stages.

7. **detect_icon_overlays** (`sister_sto/stages/detect_icon_overlays.py`)  
   Detects rarity/quality overlays on icons (e.g., epic, rare) and refines the bounding boxes for individual icon slots using stepping.

8. **detect_icons** (`sister_sto/stages/detect_icons.py`)  
   Performs SSIM-based matching on candidate icon slots to find the best match(es) among prefiltered icons.

9. **output_transformation** (`sister_sto/stages/output_transform.py`)  
   Merges prefiltered icons with SSIM results (if configured), applies post-processing transforms, and formats final match data.

After all stages run, the pipeline writes a match summary file (e.g., `*_matches.txt`) containing detected icon groups, slots, the best matches (with scores), and any runner-up candidates.

---

## ⚙ Configuration

Most configuration is handled via CLI flags, but advanced users can modify settings by editing or overriding entries in the configuration dictionary (see `sister_sto/cli.py`):

```python
config = {
    "debug": True,
    "log_level": "INFO",
    "locate_labels": {
        "gpu": False
    },
    "prefilter_icons": {
        "method": "hash"
    },
    "output_transformation": {
        "transformations_enabled_list": [
            "BACKFILL_MATCHES_WITH_PREFILTERED"
        ]
    },
    "data_dir": "/absolute/path/to/.sister_sto",
    # Optionally override directories:
    # "log_dir": "/path/to/log",
    # "icon_dir": "/path/to/icons",
    # "overlay_dir": "/path/to/overlays",
    # "cache_dir": "/path/to/cache",
    # "cargo_dir": "/path/to/cargo",
    # "output_dir": "/path/to/output"
}
```

---

## 📝 Output

By default, after running the pipeline on one or more screenshots, the match results are written to:

```
<output_dir>/<output_prefix>_matches.txt
```

Each match summary file contains sections for each **Icon Group** detected, listing individual slots, the best-matched icon (with overlay and score), and any runner-up candidates. This text format allows for easy integration into larger data processing or reporting workflows.

---
## 🐛 Bug Reports

If you encounter any issues—especially incorrect icon identifications—please raise them via [GitHub Issues](https://github.com/phillipod/SISTER/issues). Your feedback helps improve matching accuracy and feature robustness.

## 🛡 License

This project is licensed under the **AGPL-3.0 License** 

Copyright © 2025 Phillip O'Donnell.

---

## 💬 Acknowledgments

- **STO Wiki** (https://stowiki.net) for public game asset data and metadata.
- **EasyOCR** for OCR support.
- **imagehash** for perceptual hashing.
- **pybktree** for BK-Tree indexing.
- **scikit-image** for SSIM-based matching.
- **OpenCV (cv2)** for image processing primitives.
