"""Top-level conftest — ensure src/ is on sys.path so test files can
import modules directly (e.g., `from schemas import Doctrine`).
"""
import os
import sys

# Add src/ to sys.path so tests can do plain `from schemas import ...`
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)