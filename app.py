"""
app.py — Root Entrypoint (Compatibility Shim)
=============================================
Enables backwards-compatibility so running:
    streamlit run app.py
seamlessly executes the modularized frontend application at frontend/app.py.
"""

import os
import sys
import runpy

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FRONTEND_APP_PATH = os.path.join(BASE_DIR, "frontend", "app.py")

if __name__ == "__main__" or "streamlit" in sys.modules:
    runpy.run_path(FRONTEND_APP_PATH, run_name="__main__")
