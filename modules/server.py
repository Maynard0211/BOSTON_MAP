"""
modules/server.py — Compatibility Shim
Re-exports FastAPI app and components from backend.server.
"""
import sys
import os

# Ensure project root is in sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.server import *
