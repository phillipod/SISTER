#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sister-cli.py

Thin launcher that simply delegates to sister_sto.cli.main().
"""

import sys
from sister_sto.cli import main

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    else:
        # Fallback for older versions
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    main()
