#!/usr/bin/env python3
"""نقطة دخول متوافقة مع الإصدارات السابقة — الـ CLI الفعلي في finder/cli.py.

    python file_finder_cli.py --scan /path --recursive --mode full
"""

import sys

from finder.cli import main

if __name__ == "__main__":
    sys.exit(main())
