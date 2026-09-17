"""
modules/routing.py — Compatibility Shim
Re-exports routing functions from backend.routing.
"""
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.routing import *
