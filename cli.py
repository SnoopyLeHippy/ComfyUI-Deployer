"""Command line of the ComfyUI Deployer, without its window — see deployer/cli.py."""

import os
import sys

# The embedded python ignores the working directory: make the package importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deployer.cli import main

if __name__ == "__main__":
    sys.exit(main())
