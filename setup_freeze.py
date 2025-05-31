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
        ('docs/icon.ico', 'icon.ico'),
        ('docs/licenses/', 'licenses/'),
        "README.md",
        'resources/',
    ],

    'excludes': [
        'importlib.metadata', 'pkg_resources', 'setuptools'
    ],
}

base = 'Console' if sys.platform == 'win32' else None

setup(
    name='sister_sto',
    version='v2025.05.31',
    description='Screenshot Interrogation System for Traits and Equipment Recognition - Star Trek Online',
    options={
        'build_exe': build_exe_options,
        'bdist_msi': {
            'upgrade_code': '{4CFE8143-B321-4505-841F-820AF06AC1AB}',
            'initial_target_dir': r'[ProgramFiles64Folder]\SISTER - STO',
            'all_users': True,
            'add_to_path': True,
            'install_icon': 'docs/icon.ico',
            "summary_data": {
                "author": "Phillip O'Donnell",
            },
            'data': {
                "ProgId": [
                    ("Prog.Id", None, None, "SISTER - Screenshot Interrogation System for Traits and Equipment Recognition", "IconId", None),
                ],
                #"Property": [
                    #("ProductName", "SISTER - Star Trek Online - Screenshot Interrogator"),
                    # ("ProductVersion", "2025.05.31"),
                    #("Manufacturer", "Phillip O'Donnell"),
                #],
                "Icon": [
                    ("IconId", "docs/icon.ico"),
                ],            
            }
        }        
    },
    executables=[Executable(
        script='sister_sto/cli.py',
        icon='docs/icon.ico',
        base=base,
        target_name='sister-cli.exe'
    )]
)