# SISTER

**SISTER** (Screenshot Interrogation System for Traits and Equipment Recognition) is a computer vision pipeline designed to analyze **Star Trek Online** character build screenshots. It detects labels, classifies build types, extracts icon slots, and matches equipment and trait icons using image similarity methods.

---

## 🚀 Features

- 🎮 Support for PC and Console builds (Ship & Ground).
- 🔍 OCR-based label detection via EasyOCR.
- 🧠 Heuristic-based build classification.
- 🖼 Region detection using a rule-based DSL.
- 🔲 Icon slot extraction using contour analysis.
- 🧩 Icon matching using:
  - **Perceptual hash + BK-Tree** (**pre-filter**)
  - **SSIM** (Structural Similarity Index **matching engine**)
- 🎨 Quality overlay detection (e.g. Epic, Rare).
- 🧠 Auto-scaling and downsampling for large screenshots.
- 📝 Match summaries exported as text files.
- 🧰 CLI with debugging, GPU toggle for OCR, and cache building.

---

## 📦 Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/phillipod/SISTER.git
cd SISTER
pip install -r requirements.txt
```


Requires:

- Python 3.8+
- [EasyOCR](https://github.com/JaidedAI/EasyOCR) dependencies (PyTorch, etc.)
- [pybktree](https://github.com/Jetsetter/pybktree)
- [imagehash](https://github.com/JohannesBuchner/imagehash)
- [Pillow](https://python-pillow.org/) (required by imagehash)

---

## 📸 Usage

```bash
python sister.py --screenshot path/to/screenshot.png
```

### Common Options

| Option                     | Description |
|---------------------------|-------------|
| `--screenshot`            | Path to the screenshot image |
| `--icons`                 | Directory of downloaded icons (default: `images`) |
| `--overlays`              | Overlay images for quality detection (default: `overlays`) |
| `--output`                | Output directory (default: `output`) |
| `--download`              | Download icon data from STO Wiki |
| `--build-phash-cache`     | Generate perceptual hash index for faster matching |
| `--no-resize`             | Disable downscaling screenshots to 1920x1080 |
| `--debug`                 | Enable debug image output |
| `--gpu`                   | Enable GPU for OCR (if supported) |
| `--threshold`             | Matching confidence threshold (default: `0.7`) |

---

## 🧠 Pipeline Overview

1. **Label Detection**: Uses EasyOCR to locate known labels like "Fore Weapon", "Shield", etc.
2. **Build Classification**: Determines build type using a rule-based scoring engine.
3. **Region Detection**: Applies layout-specific DSL rules to compute icon regions.
4. **Slot Detection**: Detects potential icon slots inside regions via contour filtering.
5. **Candidate Filtering**: Uses PHash + BK-tree to pre-filter matching icons.
6. **SSIM Matching**: Performs high-accuracy visual matching with overlays.
7. **Quality Matching**: Determines icon rarity (e.g., Ultra Rare) via overlay comparison.

---

## 📥 Downloading Icons

Run this to download all icons:

```bash
python sister.py --download
```

Icons will be saved into a structured `images/` directory by category (ground, space, traits, etc.).

---

## 🧪 Building Hash Index

Build a perceptual hash index (used for pre-filtering):

```bash
python sister.py --build-phash-cache
```

This will overlay each icon with rarity color bands and hash the result.

---

## 🛠 Developer Notes

- All major components are modular:
  - `LabelLocator`: OCR and label extraction
  - `BuildClassifier`: Heuristic rules for layout type
  - `RegionDetector`: DSL interpreter for layout rules
  - `IconSlotDetector`: Slot extraction using entropy and standard deviation
  - `IconMatcher`: SSIM matching pipeline with pHash prefilter
  - `HashIndex`: Persistent hash cache using BK-tree

---

## 🔍 Known Limitations

- Specific to Star Trek Online layouts and label conventions.
- No deep learning for icon detection — performance depends on OCR accuracy and overlay visibility.
- OCR errors may propagate through later stages, though safeguards exist.

---
## 📄 License

AGPL-3.0 License © 2025 Phillip O'Donnell

---

## 💬 Acknowledgements

- `STO Wiki` (stowiki.net) for public asset data and metadata
- `EasyOCR` for OCR support
- `imagehash` for perceptual hashing
- `pybktree` for BKTree
- `scikit-image` for ssim

---