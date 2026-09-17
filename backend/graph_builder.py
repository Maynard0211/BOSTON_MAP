"""
backend/graph_builder.py — OpenStreetMap Parser & Graph Construction
====================================================================
Transforms raw OSM .pbf files into NetworkX MultiDiGraph.
Falls back to a simulated Boston landmark network if pyrosm is unavailable.
"""

import os
import pickle
import logging
from typing import Tuple
import numpy as np
import networkx as nx

try:
    from backend.config import GRAPH_PATH, PBF_PATH
except ImportError:
    from config import GRAPH_PATH, PBF_PATH

logger = logging.getLogger(__name__)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points on Earth in meters."""
    R = 6_371_000.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return float(2 * R * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))))


def parse_osm_network(pbf_path: str):
    """
    Parses .pbf file and extracts driving road network.
    Returns (nodes GeoDataFrame, edges GeoDataFrame).
    """
    try:
        import pyrosm
    except ImportError:
        raise ImportError("Library pyrosm is not installed. Run: pip install pyrosm")

    logger.info("Reading OSM PBF file: %s", pbf_path)
    osm = pyrosm.OSM(pbf_path)

    logger.info("Extracting driving network...")
    nodes, edges = osm.get_network(network_type="driving", nodes=True)

    if nodes is None or edges is None or len(nodes) == 0:
        raise ValueError("Could not extract road network from PBF file.")

    logger.info("Extracted raw network: %d nodes, %d edges", len(nodes), len(edges))
    return nodes, edges


def _safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if np.isfinite(v) and v >= 0 else default
    except (TypeError, ValueError):
        return default


def _is_oneway(val) -> bool:
    return val in (True, 1, "yes", "true", "1", "-1", "Yes")


def build_graph(nodes, edges) -> nx.MultiDiGraph:
    """
    Converts GeoDataFrames to NetworkX MultiDiGraph.
    Edge weight = segment length (Haversine distance in meters).
    """
    G = nx.MultiDiGraph()

    # Add Nodes
    for _, row in nodes.iterrows():
        nid = int(row["id"])
        if "lon" in row and "lat" in row:
            x, y = float(row["lon"]), float(row["lat"])
        else:
            x, y = row["geometry"].x, row["geometry"].y
        G.add_node(nid, x=x, y=y)

    node_set = set(G.nodes())

    # Add Edges
    for _, row in edges.iterrows():
        u = int(row["u"])
        v = int(row["v"])
        if u not in node_set or v not in node_set:
            continue

        if "length" in row and row["length"] is not None:
            length = _safe_float(row["length"])
        else:
            ud, vd = G.nodes[u], G.nodes[v]
            length = haversine_distance(ud["y"], ud["x"], vd["y"], vd["x"])

        if length <= 0:
            ud, vd = G.nodes[u], G.nodes[v]
            length = haversine_distance(ud["y"], ud["x"], vd["y"], vd["x"])

        oneway = _is_oneway(row.get("oneway", False))
        hw = row.get("highway", "unknown")
        if isinstance(hw, list):
            hw = hw[0] if hw else "unknown"
        highway = str(hw)

        attrs = dict(length=length, highway=highway, oneway=oneway)
        G.add_edge(u, v, **attrs)
        if not oneway:
            G.add_edge(v, u, **attrs)

    # Clean isolated nodes
    isolated = list(nx.isolates(G))
    G.remove_nodes_from(isolated)
    logger.info("Removed %d isolated nodes", len(isolated))

    # Keep only largest weakly connected component
    if G.number_of_nodes() > 0:
        wcc = max(nx.weakly_connected_components(G), key=len)
        G = G.subgraph(wcc).copy()

    logger.info("Clean graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def build_dummy_graph() -> nx.MultiDiGraph:
    """Creates a connected simulation graph between famous Boston landmarks."""
    G = nx.MultiDiGraph()

    locations = {
        1:  ("Harvard University",         42.3744, -71.1169),
        2:  ("MIT",                        42.3601, -71.0942),
        3:  ("Boston Common",              42.3551, -71.0657),
        4:  ("Logan Airport",              42.3656, -71.0096),
        5:  ("Fenway Park",                42.3467, -71.0972),
        6:  ("Boston City Hall",           42.3601, -71.0578),
        7:  ("Quincy Market",              42.3599, -71.0544),
        8:  ("Northeastern University",    42.3398, -71.0892),
        9:  ("Boston Children's Hospital", 42.3378, -71.1069),
        10: ("South Station",              42.3519, -71.0552),
        11: ("Tufts Medical Center",       42.3497, -71.0638),
        12: ("Museum of Fine Arts",        42.3394, -71.0942),
        13: ("Cambridge St Intersection",  42.3700, -71.1050),
        14: ("Broadway Crossing",          42.3650, -71.0950),
        15: ("Charles River Bridge East",  42.3610, -71.0750),
        16: ("Charles River Bridge West",  42.3590, -71.0850),
        17: ("Commonwealth Ave Junc",      42.3490, -71.0850),
        18: ("Downtown Crossing",          42.3550, -71.0600),
    }

    for nid, (name, lat, lon) in locations.items():
        G.add_node(nid, x=lon, y=lat, name=name)

    edges_to_add = [
        (1, 13, "primary"), (13, 14, "primary"), (14, 2, "primary"),
        (1, 16, "secondary"), (16, 2, "secondary"),
        (2, 15, "primary"), (15, 3, "primary"), (15, 18, "primary"),
        (16, 15, "secondary"),
        (3, 18, "primary"), (18, 6, "primary"), (6, 7, "primary"),
        (7, 4, "motorway"), (18, 4, "motorway"),
        (2, 5, "primary"),
        (5, 17, "secondary"), (17, 8, "primary"), (8, 12, "primary"),
        (12, 9, "secondary"),
        (9, 11, "secondary"),
        (11, 10, "primary"), (10, 3, "primary"), (10, 18, "primary"),
        (8, 11, "primary"),
        (3, 17, "secondary"),
        (4, 10, "motorway")
    ]

    for u, v, hw in edges_to_add:
        ud = G.nodes[u]
        vd = G.nodes[v]
        dist = haversine_distance(ud["y"], ud["x"], vd["y"], vd["x"])
        attrs = {"length": dist, "highway": hw, "oneway": False}
        G.add_edge(u, v, **attrs)
        G.add_edge(v, u, **attrs)

    return G


def build_and_save_graph(pbf_path: str = None, output_path: str = None) -> nx.MultiDiGraph:
    """
    Complete pipeline: Parse PBF → Build Graph → Save .pkl.
    Gracefully falls back to simulation graph if PBF or pyrosm fails.
    """
    pbf = pbf_path or PBF_PATH
    out = output_path or GRAPH_PATH

    try:
        nodes, edges = parse_osm_network(pbf)
        G = build_graph(nodes, edges)
        logger.info("Real-world graph successfully constructed from PBF.")
    except Exception as e:
        logger.warning(
            "Could not parse PBF (%s). Falling back to Boston landmark simulation graph...",
            str(e)
        )
        G = build_dummy_graph()

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Graph saved to: %s", out)
    return G


def load_graph(graph_path: str = None) -> nx.MultiDiGraph:
    """Loads pre-built graph pickle file."""
    path = graph_path or GRAPH_PATH
    with open(path, "rb") as f:
        return pickle.load(f)


def get_node_arrays(G: nx.MultiDiGraph) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Extracts numpy arrays (node_ids, lats, lons) for fast vectorized nearest node queries.
    """
    node_ids, lats, lons = [], [], []
    for nid, data in G.nodes(data=True):
        node_ids.append(nid)
        lats.append(data["y"])
        lons.append(data["x"])
    return np.array(node_ids, dtype=np.int64), np.array(lats), np.array(lons)


def find_nearest_node(lat: float, lon: float,
                      node_ids: np.ndarray,
                      lats: np.ndarray,
                      lons: np.ndarray) -> int:
    """Finds nearest node to given coordinate using vectorized Haversine calculation."""
    dlat = np.radians(lats - lat)
    dlon = np.radians(lons - lon)
    a = (np.sin(dlat / 2) ** 2
         + np.cos(np.radians(lat)) * np.cos(np.radians(lats)) * np.sin(dlon / 2) ** 2)
    distances = 2 * 6_371_000.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return int(node_ids[np.argmin(distances)])
