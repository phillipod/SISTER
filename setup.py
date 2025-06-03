from setuptools import setup, find_packages

setup(
    name="sister_sto",
    version="2025.05.31",
    description="Screenshot Interrogation System for Traits and Equipment Recognition - Star Trek Online",
    author="Phillip O'Donnell",
    packages=find_packages(),
    package_data={
        "sister_sto": [
            "resources/config/*.yaml",  # Add config files
            "resources/overlays/*",
            "resources/cache/*",
        ]
    },
    install_requires=[
        "numpy",
        "opencv-python",
        "scikit-image",
        "easyocr",
        "imagehash",
        "pybktree",
        "requests",
        "tqdm",
        "pyyaml",  # Add YAML dependency
    ],
    entry_points={
        "console_scripts": [
            "sister=sister_sto.cli:main",
        ],
    },
) 