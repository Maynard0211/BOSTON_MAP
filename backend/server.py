"""
backend/server.py — FastAPI Backend Service
===========================================
High-performance REST API for Boston map routing and dynamic road incident blocking.
Run: uvicorn backend.server:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import os
import threading
import pickle
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Tuple, Set, List, Any

import numpy as np
import networkx as nx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from backend.config import (
        PBF_PATH, GRAPH_PATH, BLOCKED_PATH, PRESET_LOCATIONS
    )
    from backend.graph_builder import (
        build_and_save_graph, load_graph, get_node_arrays, find_nearest_node
    )
    from backend.routing import dijkstra, astar, path_to_coordinates
except ImportError:
    from config import (
        PBF_PATH, GRAPH_PATH, BLOCKED_PATH, PRESET_LOCATIONS
    )
    from graph_builder import (
        build_and_save_graph, load_graph, get_node_arrays, find_nearest_node
    )
    from routing import dijkstra, astar, path_to_coordinates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# HELPER: REUSABLE EDGE ATTRIBUTE EXTRACTOR (DRY)
# ══════════════════════════════════════════════════════════════════════════════

def extract_edge_attributes(
    edge_data: Any,
    u: int,
    v: int,
    G: nx.MultiDiGraph
) -> Tuple[float, str, List[Tuple[float, float]]]:
    """
    Extracts (length_m, highway_type, coordinates) from an edge.
    Uniformly supports both DiGraph and MultiDiGraph structures and generates
    fallback straight-line coordinates if Shapely LineString geometry is absent.
    """
    length = 1.0
    highway = "unknown"
    coords = []
    best_geom = None

    if edge_data is not None:
        # 1. Direct dict attributes (DiGraph)
        if "length" in edge_data:
            try:
                length = float(edge_data["length"])
            except (TypeError, ValueError):
                pass
        if "highway" in edge_data:
            highway = str(edge_data["highway"])
        if "geometry" in edge_data:
            best_geom = edge_data["geometry"]

        # 2. MultiDiGraph attributes (dict of dicts)
        if isinstance(edge_data, dict) and not ("length" in edge_data or "highway" in edge_data):
            min_len = float("inf")
            for d in edge_data.values():
                if isinstance(d, dict):
                    l_val = d.get("length")
                    if l_val is not None:
                        try:
                            l_float = float(l_val)
                            if l_float < min_len:
                                min_len = l_float
                                length = l_float
                                best_geom = d.get("geometry", best_geom)
                        except (TypeError, ValueError):
                            pass
                    if "highway" in d and highway == "unknown":
                        highway = str(d["highway"])

    # Extract coordinates from geometry if available
    if best_geom is not None:
        try:
            if hasattr(best_geom, "coords"):
                coords = [(float(pt[1]), float(pt[0])) for pt in best_geom.coords]
            elif isinstance(best_geom, list):
                coords = [(float(pt[1]), float(pt[0])) for pt in best_geom]
        except Exception:
            coords = []

    # Fallback: Straight line between node endpoints
    if not coords and u in G and v in G:
        coords = [
            (float(G.nodes[u]["y"]), float(G.nodes[u]["x"])),
            (float(G.nodes[v]["y"]), float(G.nodes[v]["x"]))
        ]

    return round(length, 1), highway, coords


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH SINGLETON WITH THREAD-SAFETY
# ══════════════════════════════════════════════════════════════════════════════

class _GraphState:
    """Thread-safe singleton managing graph state, fast spatial indexing, and road blocks."""

    def __init__(self):
        self._lock = threading.Lock()
        self.G: Optional[nx.MultiDiGraph] = None
        self.node_ids: Optional[np.ndarray] = None
        self.lats: Optional[np.ndarray] = None
        self.lons: Optional[np.ndarray] = None

        # Edge search arrays for fast nearest-edge spatial queries
        self.edge_us: Optional[np.ndarray] = None
        self.edge_vs: Optional[np.ndarray] = None
        self.edge_keys: Optional[np.ndarray] = None
        self.edge_lats: Optional[np.ndarray] = None
        self.edge_lons: Optional[np.ndarray] = None

        # Background build management
        self.build_status = "idle"  # idle, building, success, error
        self.build_error: Optional[str] = None
        self.build_thread: Optional[threading.Thread] = None

        # Blocked edges: Set[Tuple[int, int]]
        self.blocked_edges: Set[Tuple[int, int]] = set()

    def _refresh_arrays(self):
        self.node_ids, self.lats, self.lons = get_node_arrays(self.G)

        edge_us, edge_vs, edge_keys, edge_lats, edge_lons = [], [], [], [], []
        if self.G:
            for u, v, k, data in self.G.edges(keys=True, data=True):
                geom = data.get("geometry")
                if geom:
                    for pt in geom:
                        edge_us.append(u)
                        edge_vs.append(v)
                        edge_keys.append(k)
                        edge_lats.append(pt[1])
                        edge_lons.append(pt[0])
                else:
                    u_data, v_data = self.G.nodes[u], self.G.nodes[v]
                    edge_us.extend([u, u])
                    edge_vs.extend([v, v])
                    edge_keys.extend([k, k])
                    edge_lats.extend([u_data["y"], v_data["y"]])
                    edge_lons.extend([u_data["x"], v_data["x"]])

        self.edge_us = np.array(edge_us, dtype=np.int64)
        self.edge_vs = np.array(edge_vs, dtype=np.int64)
        self.edge_keys = np.array(edge_keys, dtype=np.int64)
        self.edge_lats = np.array(edge_lats)
        self.edge_lons = np.array(edge_lons)

    def startup(self):
        self.load_blocked_edges()

        if os.path.exists(GRAPH_PATH):
            try:
                logger.info("Found cached graph file (%s). Loading into memory...", GRAPH_PATH)
                self.G = load_graph(GRAPH_PATH)
                self._refresh_arrays()
                self.build_status = "success"
                logger.info("Graph loaded successfully: %d nodes, %d edges.",
                            self.G.number_of_nodes(), self.G.number_of_edges())
            except Exception as e:
                logger.error("Error loading graph cache: %s", str(e))
                self.build_status = "error"
                self.build_error = f"Cache read error: {str(e)}"
        else:
            logger.info("Graph cache not found. Starting async background build...")
            self.start_async_build()

    def start_async_build(self) -> dict:
        with self._lock:
            if self.build_status == "building":
                return self.info()

            self.build_status = "building"
            self.build_error = None

            def _worker():
                try:
                    logger.info("Background thread building graph...")
                    self.G = build_and_save_graph(PBF_PATH, GRAPH_PATH)
                    self._refresh_arrays()
                    self.build_status = "success"
                    logger.info("Graph build completed successfully.")
                except Exception as e:
                    self.build_status = "error"
                    self.build_error = str(e)
                    logger.error("Error during graph build: %s", str(e))

            self.build_thread = threading.Thread(target=_worker, daemon=True)
            self.build_thread.start()
            return self.info()

    def reload(self) -> dict:
        with self._lock:
            self.G = load_graph(GRAPH_PATH)
            self._refresh_arrays()
            self.build_status = "success"
        return self.info()

    @property
    def ready(self) -> bool:
        return self.G is not None

    def info(self) -> dict:
        return {
            "loaded": self.ready,
            "node_count": self.G.number_of_nodes() if self.G else 0,
            "edge_count": self.G.number_of_edges() if self.G else 0,
            "pbf_path": PBF_PATH,
            "graph_path": GRAPH_PATH,
            "build_status": self.build_status,
            "build_error": self.build_error,
            "blocked_count": len(self.blocked_edges) // 2
        }

    def nearest(self, lat: float, lon: float) -> int:
        return find_nearest_node(lat, lon, self.node_ids, self.lats, self.lons)

    def nearest_edge(self, lat: float, lon: float) -> Tuple[int, int, int]:
        dlat = np.radians(self.edge_lats - lat)
        dlon = np.radians(self.edge_lons - lon)
        a = (np.sin(dlat / 2) ** 2
             + np.cos(np.radians(lat)) * np.cos(np.radians(self.edge_lats)) * np.sin(dlon / 2) ** 2)
        distances = 2 * 6_371_000.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
        min_idx = np.argmin(distances)
        return int(self.edge_us[min_idx]), int(self.edge_vs[min_idx]), int(self.edge_keys[min_idx])

    # ── Blocked Edges Persistence & Thread Safety ─────────────────────────────

    def load_blocked_edges(self):
        with self._lock:
            if os.path.exists(BLOCKED_PATH):
                try:
                    with open(BLOCKED_PATH, "rb") as f:
                        self.blocked_edges = pickle.load(f)
                    logger.info("Loaded %d blocked edges from %s", len(self.blocked_edges), BLOCKED_PATH)
                except Exception as e:
                    logger.error("Failed to load blocked edges: %s", str(e))
                    self.blocked_edges = set()
            else:
                self.blocked_edges = set()

    def save_blocked_edges(self):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(BLOCKED_PATH)), exist_ok=True)
            with open(BLOCKED_PATH, "wb") as f:
                pickle.dump(self.blocked_edges, f)
            logger.info("Saved %d blocked edges to %s", len(self.blocked_edges), BLOCKED_PATH)
        except Exception as e:
            logger.error("Failed to save blocked edges: %s", str(e))

    def add_blocked_edge(self, u: int, v: int) -> int:
        with self._lock:
            self.blocked_edges.add((u, v))
            self.blocked_edges.add((v, u))
            self.save_blocked_edges()
            return len(self.blocked_edges) // 2

    def remove_blocked_edge(self, u: int, v: int) -> bool:
        with self._lock:
            removed = False
            if (u, v) in self.blocked_edges:
                self.blocked_edges.remove((u, v))
                removed = True
            if (v, u) in self.blocked_edges:
                self.blocked_edges.remove((v, u))
                removed = True
            if removed:
                self.save_blocked_edges()
            return removed

    def clear_all_blocked(self):
        with self._lock:
            self.blocked_edges.clear()
            self.save_blocked_edges()


GS = _GraphState()


def _require_graph():
    if not GS.ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Graph is not ready yet or is currently building in the background."
        )


# ══════════════════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class RouteIn(BaseModel):
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    end_lat: float = Field(..., ge=-90, le=90)
    end_lon: float = Field(..., ge=-180, le=180)
    algorithm: str = Field("astar", pattern=r"^(astar|dijkstra)$")


class RouteOut(BaseModel):
    found: bool
    algorithm: str
    path_coordinates: List[Tuple[float, float]] = []
    total_distance_m: float = 0.0
    exec_time_ms: float = 0.0
    node_count: int = 0
    error: Optional[str] = None


class BlockEdgeIn(BaseModel):
    u: int
    v: int


class BlockedEdgeInfo(BaseModel):
    u: int
    v: int
    u_lat: float
    u_lon: float
    v_lat: float
    v_lon: float
    name: str
    coords: List[Tuple[float, float]] = []


# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP & ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    GS.startup()
    yield

app = FastAPI(
    title="Boston Smart Route Finder API",
    description="High-performance urban navigation and traffic incident simulation API for Boston.",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", **GS.info()}


@app.post("/api/route", response_model=RouteOut, tags=["Route"])
def find_route(body: RouteIn):
    _require_graph()
    src = GS.nearest(body.start_lat, body.start_lon)
    dst = GS.nearest(body.end_lat, body.end_lon)

    if src == dst:
        return RouteOut(
            found=False,
            algorithm=body.algorithm,
            error="Origin and destination are too close (snapped to the same intersection node)."
        )

    fn = astar if body.algorithm == "astar" else dijkstra
    path, dist_m, exec_s = fn(GS.G, src, dst, blocked_edges=GS.blocked_edges)

    if not path:
        return RouteOut(
            found=False,
            algorithm=body.algorithm,
            error="No viable route found (target disconnected or paths blocked)."
        )

    return RouteOut(
        found=True,
        algorithm=body.algorithm,
        path_coordinates=path_to_coordinates(GS.G, path),
        total_distance_m=round(dist_m, 2),
        exec_time_ms=round(exec_s * 1000, 3),
        node_count=len(path),
    )


@app.get("/api/locations/presets", tags=["Locations"])
def get_presets():
    return {
        "locations": [
            {"name": k, "lat": v[0], "lon": v[1]}
            for k, v in PRESET_LOCATIONS.items()
        ]
    }


@app.get("/api/graph/info", tags=["Graph"])
def graph_info():
    return GS.info()


@app.post("/api/graph/build", tags=["Graph"])
def graph_build():
    if not os.path.exists(PBF_PATH):
        raise HTTPException(404, f"PBF file not found at: {PBF_PATH}")
    try:
        return {"success": True, "message": "Graph build initiated in background.", **GS.start_async_build()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/graph/reload", tags=["Graph"])
def graph_reload():
    if not os.path.exists(GRAPH_PATH):
        raise HTTPException(404, f"Graph cache file not found at: {GRAPH_PATH}")
    try:
        return {"success": True, "message": "Graph cache reloaded.", **GS.reload()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/graph/blocked", response_model=List[BlockedEdgeInfo], tags=["Graph"])
def get_blocked_edges():
    _require_graph()
    G = GS.G
    res = []
    seen = set()

    for u, v in list(GS.blocked_edges):
        if (v, u) in seen:
            continue
        seen.add((u, v))

        if u in G and v in G:
            edge_data = G.get_edge_data(u, v) or G.get_edge_data(v, u)
            _, highway, coords = extract_edge_attributes(edge_data, u, v, G)

            res.append(BlockedEdgeInfo(
                u=u, v=v,
                u_lat=G.nodes[u]["y"], u_lon=G.nodes[u]["x"],
                v_lat=G.nodes[v]["y"], v_lon=G.nodes[v]["x"],
                name=f"Road ({highway})",
                coords=coords
            ))
    return res


@app.post("/api/graph/blocked", tags=["Graph"])
def block_edge(body: BlockEdgeIn):
    _require_graph()
    u, v = body.u, body.v
    if u not in GS.G or v not in GS.G:
        raise HTTPException(404, f"Intersections ({u}, {v}) do not exist in graph.")

    blocked_count = GS.add_blocked_edge(u, v)
    return {
        "success": True,
        "message": f"Successfully blocked road segment connecting node {u} and {v}",
        "blocked_count": blocked_count
    }


@app.delete("/api/graph/blocked", tags=["Graph"])
def unblock_edge(u: int, v: int):
    _require_graph()
    removed = GS.remove_blocked_edge(u, v)
    if removed:
        return {"success": True, "message": f"Successfully unblocked road between {u} and {v}"}
    return {"success": False, "message": f"Road between {u} and {v} was not blocked."}


@app.post("/api/graph/blocked/clear", tags=["Graph"])
def clear_blocked_edges():
    GS.clear_all_blocked()
    return {"success": True, "message": "Successfully cleared all road blocks."}


@app.get("/api/graph/node-adjacent/{node_id}", tags=["Graph"])
def get_node_adjacent(node_id: int):
    _require_graph()
    G = GS.G
    if node_id not in G:
        raise HTTPException(404, f"Intersection node {node_id} not found in map.")

    adj_edges = []

    # Outgoing edges
    for v in G.neighbors(node_id):
        edge_data = G.get_edge_data(node_id, v)
        length_m, highway, coords = extract_edge_attributes(edge_data, node_id, v, G)

        adj_edges.append({
            "u": node_id,
            "v": v,
            "u_lat": G.nodes[node_id]["y"],
            "u_lon": G.nodes[node_id]["x"],
            "v_lat": G.nodes[v]["y"],
            "v_lon": G.nodes[v]["x"],
            "length_m": length_m,
            "highway": highway,
            "coords": coords,
            "direction": "out",
            "is_blocked": (node_id, v) in GS.blocked_edges or (v, node_id) in GS.blocked_edges
        })

    # Incoming edges (for directed components)
    if hasattr(G, "predecessors"):
        for u in G.predecessors(node_id):
            if u in G.neighbors(node_id):
                continue
            edge_data = G.get_edge_data(u, node_id)
            length_m, highway, coords = extract_edge_attributes(edge_data, u, node_id, G)

            adj_edges.append({
                "u": u,
                "v": node_id,
                "u_lat": G.nodes[u]["y"],
                "u_lon": G.nodes[u]["x"],
                "v_lat": G.nodes[node_id]["y"],
                "v_lon": G.nodes[node_id]["x"],
                "length_m": length_m,
                "highway": highway,
                "coords": coords,
                "direction": "in",
                "is_blocked": (u, node_id) in GS.blocked_edges or (node_id, u) in GS.blocked_edges
            })

    return {
        "node_id": node_id,
        "lat": G.nodes[node_id]["y"],
        "lon": G.nodes[node_id]["x"],
        "adjacent_edges": adj_edges
    }


@app.get("/api/graph/nearest", tags=["Graph"])
def get_nearest_node(lat: float, lon: float):
    _require_graph()
    try:
        node_id = GS.nearest(lat, lon)
        return {
            "node_id": node_id,
            "lat": float(GS.G.nodes[node_id]["y"]),
            "lon": float(GS.G.nodes[node_id]["x"])
        }
    except Exception as e:
        raise HTTPException(500, f"Error finding nearest node: {str(e)}")


@app.get("/api/graph/nearest-edge", tags=["Graph"])
def get_nearest_edge(lat: float, lon: float):
    _require_graph()
    try:
        u, v, k = GS.nearest_edge(lat, lon)
        G = GS.G
        edge_data = G.get_edge_data(u, v, k)
        length_m, highway, coords = extract_edge_attributes(edge_data, u, v, G)

        return {
            "u": u,
            "v": v,
            "key": k,
            "u_lat": float(G.nodes[u]["y"]),
            "u_lon": float(G.nodes[u]["x"]),
            "v_lat": float(G.nodes[v]["y"]),
            "v_lon": float(G.nodes[v]["x"]),
            "length_m": length_m,
            "highway": highway,
            "coords": coords,
            "is_blocked": (u, v) in GS.blocked_edges or (v, u) in GS.blocked_edges
        }
    except Exception as e:
        raise HTTPException(500, f"Error finding nearest edge: {str(e)}")
