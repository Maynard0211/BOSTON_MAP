"""
modules/graph_builder.py — Compatibility Shim
Re-exports graph_builder functions from backend.graph_builder.
"""
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.graph_builder import *
