"""Entry point for the ComfyUI custom node manager GUI."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deployer.ui import run

if __name__ == "__main__":
    run()