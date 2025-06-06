from setuptools import setup, find_packages
import os

# Get the long description from the README file
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Get the package's version from the __init__.py file
def get_version():
    init_path = os.path.join(os.path.dirname(__file__), 'src', 'forwardemail', '__init__.py')
    with open(init_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                return line.split('=')[1].strip().strip('\'"')
    return '0.1.0'

setup(
    name="forwardemail",
    version=get_version(),
    author="Your Name",
    author_email="your.email@example.com",
    description="A Python client for the ForwardEmail API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/forwardemail-python",
    package_dir={"": "src"},  # Tell setuptools that packages are under src
    packages=find_packages(where="src"),
    python_requires='>=3.6',
    install_requires=[
        'requests>=2.25.0',
    ],
    extras_require={
        'dev': [
            'pytest>=6.0',
            'pytest-cov>=2.0',
            'black>=21.5b2',
            'isort>=5.0',
            'mypy>=0.812',
            'types-requests>=2.25.0',
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Communications :: Email",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
