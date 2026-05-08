"""Unit-test configuration. Adds scripts/ to sys.path so test_build_food_taxonomy.py
can import build_food_taxonomy directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
