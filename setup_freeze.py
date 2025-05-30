import sys
sys.setrecursionlimit(10000)

from cx_Freeze import setup, Executable
import sys, os

# Include necessary packages, modules, and data files
build_exe_options = {
    'packages': [
        'os', 'sys', 'cv2', 'numpy', 'skimage', 'easyocr', 'imagehash', 'pybktree', 'requests', 'torch'
    ],
    'include_files': [
        'resources/'
    ],

    'excludes': [
        'importlib.metadata', 'pkg_resources', 'setuptools'
    ],

    #'zip_include_packages': [],    # disables zipping of all packages
    #'zip_exclude_packages': ['*'], # keeps packages as files to avoid deep metadata traversal

}

base = 'Console' if sys.platform == 'win32' else None

setup(
    name='sister',
    version='v2025.05.30',
    description='Screenshot Interrogation System for Traits and Equipment Recognition - Star Trek Online',
    options={'build_exe': build_exe_options},
    executables=[Executable(
        script='sister-cli.py',
        base=base,
        target_name='sister-cli.exe'
    )]
)