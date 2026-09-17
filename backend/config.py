"""
backend/config.py — Centralized Configuration
=============================================
Manages file paths, environment variables, preset locations, and constants.
"""

import os
from typing import Dict, Tuple

# Base directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(BACKEND_DIR)

# Data paths
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

PBF_PATH = os.getenv("PBF_PATH", os.path.join(DATA_DIR, "boston_massachusetts.osm.pbf"))
GRAPH_PATH = os.getenv("GRAPH_PATH", os.path.join(DATA_DIR, "boston_graph.pkl"))
BLOCKED_PATH = os.getenv("BLOCKED_PATH", os.path.join(DATA_DIR, "blocked_edges.pkl"))
LAST_ROUTE_PATH = os.getenv("LAST_ROUTE_PATH", os.path.join(DATA_DIR, "last_route.json"))

# Server settings
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_URL = os.getenv("API_URL", f"http://localhost:{API_PORT}")

# Algorithm constants
ALGO_NAMES = {
    "astar": "A* (A-Star)",
    "dijkstra": "Dijkstra"
}

ALGO_COLORS = {
    "astar": "#2563EB",
    "dijkstra": "#60A5FA"
}

# Boston key landmarks (Presets)
PRESET_LOCATIONS: Dict[str, Tuple[float, float]] = {
    "Harvard University":         (42.3744, -71.1169),
    "MIT":                        (42.3601, -71.0942),
    "Boston Common":              (42.3551, -71.0657),
    "Logan Airport":              (42.3656, -71.0096),
    "Fenway Park":                (42.3467, -71.0972),
    "Boston City Hall":           (42.3601, -71.0578),
    "Quincy Market":              (42.3599, -71.0544),
    "Northeastern University":    (42.3398, -71.0892),
    "Boston Children's Hospital": (42.3378, -71.1069),
    "South Station":              (42.3519, -71.0552),
    "Tufts Medical Center":       (42.3497, -71.0638),
    "Museum of Fine Arts":        (42.3394, -71.0942),
}
