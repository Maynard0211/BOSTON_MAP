"""
server.py — FastAPI Backend (all-in-one)
=========================================
Chạy:  uvicorn modules.server:app --reload --port 8000
Docs:  http://localhost:8000/docs
"""

import os
import threading
import pickle
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Tuple, Set, List

import numpy as np
import networkx as nx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from modules.graph_builder import build_and_save_graph, load_graph, get_node_arrays, find_nearest_node
from modules.routing import dijkstra, astar, path_to_coordinates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

MODULES_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(MODULES_DIR)
PBF_PATH   = os.getenv("PBF_PATH",   os.path.join(MODULES_DIR, "boston_massachusetts.osm.pbf"))
GRAPH_PATH = os.getenv("GRAPH_PATH", os.path.join(BASE_DIR, "boston_graph.pkl"))
BLOCKED_PATH = os.path.join(BASE_DIR, "blocked_edges.pkl")

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


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH SINGLETON
# ══════════════════════════════════════════════════════════════════════════════

class _GraphState:
    """Thread-safe singleton: load graph bất đồng bộ, hỗ trợ chặn đường."""
    _lock = threading.Lock()

    def __init__(self):
        self.G:        nx.MultiDiGraph | None = None
        self.node_ids: np.ndarray | None = None
        self.lats:     np.ndarray | None = None
        self.lons:     np.ndarray | None = None
        
        # Mảng cạnh phục vụ tìm kiếm cạnh gần nhất
        self.edge_us:   np.ndarray | None = None
        self.edge_vs:   np.ndarray | None = None
        self.edge_keys: np.ndarray | None = None
        self.edge_lats: np.ndarray | None = None
        self.edge_lons: np.ndarray | None = None
        
        # Quản lý luồng build
        self.build_status = "idle"  # idle, building, success, error
        self.build_error: Optional[str] = None
        self.build_thread: Optional[threading.Thread] = None
        
        # Tập hợp các cạnh bị chặn: Set[Tuple[u_node_id, v_node_id]]
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
                        edge_lats.append(pt[1])  # pt là (lon, lat) hoặc [lon, lat]
                        edge_lons.append(pt[0])
                else:
                    u_data, v_data = self.G.nodes[u], self.G.nodes[v]
                    # Đầu u
                    edge_us.append(u)
                    edge_vs.append(v)
                    edge_keys.append(k)
                    edge_lats.append(u_data["y"])
                    edge_lons.append(u_data["x"])
                    # Đầu v
                    edge_us.append(u)
                    edge_vs.append(v)
                    edge_keys.append(k)
                    edge_lats.append(v_data["y"])
                    edge_lons.append(v_data["x"])
                    
        self.edge_us = np.array(edge_us, dtype=np.int64)
        self.edge_vs = np.array(edge_vs, dtype=np.int64)
        self.edge_keys = np.array(edge_keys, dtype=np.int64)
        self.edge_lats = np.array(edge_lats)
        self.edge_lons = np.array(edge_lons)

    def startup(self):
        # 1. Tải danh sách cạnh bị chặn đã lưu từ trước
        self.load_blocked_edges()

        # 2. Tải đồ thị (nếu có sẵn file cache .pkl)
        if os.path.exists(GRAPH_PATH):
            try:
                logger.info("Tìm thấy file cache đồ thị. Đang load...")
                self.G = load_graph(GRAPH_PATH)
                self._refresh_arrays()
                self.build_status = "success"
                logger.info("Đã load đồ thị thành công vào RAM.")
            except Exception as e:
                logger.error("Lỗi khi đọc file cache đồ thị: %s", str(e))
                self.build_status = "error"
                self.build_error = f"Lỗi đọc file cache: {str(e)}"
        else:
            logger.info("Không tìm thấy file cache đồ thị (%s). Tự động kích hoạt khởi tạo ngầm...", GRAPH_PATH)
            self.start_async_build()

    def start_async_build(self):
        with self._lock:
            if self.build_status == "building":
                return self.info()

            self.build_status = "building"
            self.build_error = None

            def _worker():
                try:
                    logger.info("Bắt đầu build đồ thị từ file PBF dưới nền...")
                    # Gọi pipeline build và lưu file
                    self.G = build_and_save_graph(PBF_PATH, GRAPH_PATH)
                    self._refresh_arrays()
                    self.build_status = "success"
                    logger.info("Build đồ thị thành công và đã load vào RAM.")
                except Exception as e:
                    self.build_status = "error"
                    self.build_error = str(e)
                    logger.error("Lỗi khi build đồ thị: %s", str(e))

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
            "loaded":        self.ready,
            "node_count":    self.G.number_of_nodes() if self.G else 0,
            "edge_count":    self.G.number_of_edges() if self.G else 0,
            "pbf_path":      PBF_PATH,
            "graph_path":    GRAPH_PATH,
            "build_status":  self.build_status,
            "build_error":   self.build_error,
            "blocked_count": len(self.blocked_edges) // 2  # Chia 2 vì lưu cả 2 chiều (u, v) và (v, u)
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

    # ── Chặn đường ────────────────────────────────────────────────────────────

    def load_blocked_edges(self):
        if os.path.exists(BLOCKED_PATH):
            try:
                with open(BLOCKED_PATH, "rb") as f:
                    self.blocked_edges = pickle.load(f)
                logger.info("Đã load %d cạnh bị chặn từ %s", len(self.blocked_edges), BLOCKED_PATH)
            except Exception as e:
                logger.error("Lỗi khi load blocked edges: %s", str(e))
                self.blocked_edges = set()
        else:
            self.blocked_edges = set()

    def save_blocked_edges(self):
        try:
            with open(BLOCKED_PATH, "wb") as f:
                pickle.dump(self.blocked_edges, f)
            logger.info("Đã lưu %d cạnh bị chặn vào %s", len(self.blocked_edges), BLOCKED_PATH)
        except Exception as e:
            logger.error("Lỗi khi lưu blocked edges: %s", str(e))


GS = _GraphState()

def _require_graph():
    if not GS.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Đồ thị chưa sẵn sàng hoặc đang build dưới nền. Vui lòng đợi hoặc build từ Admin.")


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class RouteIn(BaseModel):
    start_lat: float = Field(..., ge=-90,  le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    end_lat:   float = Field(..., ge=-90,  le=90)
    end_lon:   float = Field(..., ge=-180, le=180)
    algorithm: str   = Field("astar", pattern=r"^(astar|dijkstra)$")

class RouteOut(BaseModel):
    found:            bool
    algorithm:        str
    path_coordinates: List[Tuple[float, float]] = []
    total_distance_m: float = 0.0
    exec_time_ms:     float = 0.0
    node_count:       int   = 0
    error:            Optional[str] = None

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
# APP
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    GS.startup()
    yield

app = FastAPI(
    title="Boston Route Finder API",
    description="Backend API tìm đường đi trên bản đồ Boston và quản lý chặn đường giao thông.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", **GS.info()}


# ── Route ─────────────────────────────────────────────────────────────────────

@app.post("/api/route", response_model=RouteOut, tags=["Route"])
def find_route(body: RouteIn):
    _require_graph()
    src = GS.nearest(body.start_lat, body.start_lon)
    dst = GS.nearest(body.end_lat,   body.end_lon)

    if src == dst:
        return RouteOut(found=False, algorithm=body.algorithm,
                        error="Điểm xuất phát và đích quá gần (cùng node).")

    fn = astar if body.algorithm == "astar" else dijkstra
    
    # Truyền danh sách blocked_edges của hệ thống vào thuật toán tìm đường
    path, dist_m, exec_s = fn(GS.G, src, dst, blocked_edges=GS.blocked_edges)

    if not path:
        return RouteOut(found=False, algorithm=body.algorithm,
                        error="Không tìm được đường đi khả thi (đường đi bị chặn hoặc không liên thông).")

    return RouteOut(
        found=True, algorithm=body.algorithm,
        path_coordinates=path_to_coordinates(GS.G, path),
        total_distance_m=round(dist_m, 2),
        exec_time_ms=round(exec_s * 1000, 3),
        node_count=len(path),
    )


# ── Locations ─────────────────────────────────────────────────────────────────

@app.get("/api/locations/presets", tags=["Locations"])
def get_presets():
    return {"locations": [{"name": k, "lat": v[0], "lon": v[1]}
                           for k, v in PRESET_LOCATIONS.items()]}


# ── Graph Management ─────────────────────────────────────────────────────────

@app.get("/api/graph/info", tags=["Graph"])
def graph_info():
    return GS.info()

@app.post("/api/graph/build", tags=["Graph"])
def graph_build():
    if not os.path.exists(PBF_PATH):
        raise HTTPException(404, f"Không tìm thấy file PBF: {PBF_PATH}")
    try:
        # Build bất đồng bộ dưới nền để tránh treo server
        return {"success": True, "message": "Bắt đầu build đồ thị ở background.", **GS.start_async_build()}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/graph/reload", tags=["Graph"])
def graph_reload():
    if not os.path.exists(GRAPH_PATH):
        raise HTTPException(404, f"Không tìm thấy file PKL: {GRAPH_PATH}")
    try:
        return {"success": True, "message": "Reload thành công.", **GS.reload()}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Chặn tuyến đường (Blocked Edges) ──────────────────────────────────────────

@app.get("/api/graph/blocked", response_model=List[BlockedEdgeInfo], tags=["Graph"])
def get_blocked_edges():
    _require_graph()
    G = GS.G
    res = []
    
    # Chỉ lặp qua một chiều của cạnh bị chặn để tránh hiển thị trùng lặp trên UI
    seen = set()
    for u, v in list(GS.blocked_edges):
        if (v, u) in seen:
            continue
        seen.add((u, v))
        
        if u in G and v in G:
            edge_data = G.get_edge_data(u, v)
            if edge_data is None:
                edge_data = G.get_edge_data(v, u)
            highway = "unknown"
            coords = []
            
            if edge_data is not None:
                if "highway" in edge_data:
                    highway = edge_data["highway"]
                elif isinstance(edge_data, dict):
                    for d in edge_data.values():
                        if isinstance(d, dict) and "highway" in d:
                            highway = d["highway"]
                            break
                            
                best_geom = None
                if "geometry" in edge_data:
                    best_geom = edge_data["geometry"]
                elif isinstance(edge_data, dict):
                    for d in edge_data.values():
                        if isinstance(d, dict) and "geometry" in d:
                            best_geom = d["geometry"]
                            break
                            
                if best_geom is not None:
                    try:
                        if hasattr(best_geom, "coords"):
                            coords = [(float(pt[1]), float(pt[0])) for pt in best_geom.coords]
                        elif isinstance(best_geom, list):
                            coords = [(float(pt[1]), float(pt[0])) for pt in best_geom]
                    except Exception:
                        pass
            
            if not coords:
                coords = [(G.nodes[u]["y"], G.nodes[u]["x"]), (G.nodes[v]["y"], G.nodes[v]["x"])]
                
            res.append(BlockedEdgeInfo(
                u=u, v=v,
                u_lat=G.nodes[u]["y"], u_lon=G.nodes[u]["x"],
                v_lat=G.nodes[v]["y"], v_lon=G.nodes[v]["x"],
                name=f"Đoạn đường ({highway})",
                coords=coords
            ))
    return res

@app.post("/api/graph/blocked", tags=["Graph"])
def block_edge(body: BlockEdgeIn):
    _require_graph()
    G = GS.G
    u, v = body.u, body.v
    if u not in G or v not in G:
        raise HTTPException(404, f"Một hoặc cả hai giao lộ ({u}, {v}) không tồn tại trong bản đồ.")
    
    # Chặn cả hai chiều để đảm bảo xe không đi được cả 2 hướng
    GS.blocked_edges.add((u, v))
    GS.blocked_edges.add((v, u))
    GS.save_blocked_edges()
    return {"success": True, "message": f"Đã chặn đoạn đường nối node {u} và {v}", "blocked_count": len(GS.blocked_edges) // 2}

@app.delete("/api/graph/blocked", tags=["Graph"])
def unblock_edge(u: int, v: int):
    _require_graph()
    removed = False
    if (u, v) in GS.blocked_edges:
        GS.blocked_edges.remove((u, v))
        removed = True
    if (v, u) in GS.blocked_edges:
        GS.blocked_edges.remove((v, u))
        removed = True
        
    if removed:
        GS.save_blocked_edges()
        return {"success": True, "message": f"Đã mở chặn đoạn đường nối node {u} và {v}"}
    return {"success": False, "message": f"Đoạn đường nối node {u} và {v} chưa bị chặn."}

@app.post("/api/graph/blocked/clear", tags=["Graph"])
def clear_blocked_edges():
    GS.blocked_edges.clear()
    GS.save_blocked_edges()
    return {"success": True, "message": "Đã mở chặn toàn bộ bản đồ."}


# ── Lấy các cạnh kề của 1 node (để hiển thị chọn chặn đường) ─────────────────

@app.get("/api/graph/node-adjacent/{node_id}", tags=["Graph"])
def get_node_adjacent(node_id: int):
    _require_graph()
    G = GS.G
    if node_id not in G:
        raise HTTPException(404, f"Không tìm thấy nút giao {node_id} trên bản đồ.")
    
    adj_edges = []
    
    # 1. Các cạnh đi ra từ node_id
    for v in G.neighbors(node_id):
        edge_data = G.get_edge_data(node_id, v)
        
        # Sửa lỗi lấy trọng số tối thiểu
        # Lấy length
        length = 1.0
        if edge_data is not None:
            if "length" in edge_data:
                length = float(edge_data["length"])
            elif isinstance(edge_data, dict):
                lengths = []
                for d in edge_data.values():
                    if isinstance(d, dict) and "length" in d:
                        lengths.append(float(d["length"]))
                if lengths:
                    length = min(lengths)
        
        highway = "unknown"
        if edge_data is not None:
            if "highway" in edge_data:
                highway = edge_data["highway"]
            elif isinstance(edge_data, dict):
                for d in edge_data.values():
                    if isinstance(d, dict) and "highway" in d:
                        highway = d["highway"]
                        break
        
        # Thử lấy geometry
        coords = []
        best_geom = None
        if edge_data is not None:
            if "geometry" in edge_data:
                best_geom = edge_data["geometry"]
            elif isinstance(edge_data, dict):
                for d in edge_data.values():
                    if isinstance(d, dict) and "geometry" in d:
                        best_geom = d["geometry"]
                        break
                        
        if best_geom is not None:
            try:
                if hasattr(best_geom, "coords"):
                    coords = [(float(pt[1]), float(pt[0])) for pt in best_geom.coords]
                elif isinstance(best_geom, list):
                    coords = [(float(pt[1]), float(pt[0])) for pt in best_geom]
            except Exception:
                pass
        
        if not coords:
            coords = [
                (G.nodes[node_id]["y"], G.nodes[node_id]["x"]),
                (G.nodes[v]["y"], G.nodes[v]["x"])
            ]
            
        adj_edges.append({
            "u": node_id,
            "v": v,
            "u_lat": G.nodes[node_id]["y"],
            "u_lon": G.nodes[node_id]["x"],
            "v_lat": G.nodes[v]["y"],
            "v_lon": G.nodes[v]["x"],
            "length_m": round(length, 1),
            "highway": str(highway),
            "coords": coords,
            "direction": "out",
            "is_blocked": (node_id, v) in GS.blocked_edges or (v, node_id) in GS.blocked_edges
        })
        
    # 2. Các cạnh đi vào node_id (cho đồ thị có hướng)
    if hasattr(G, "predecessors"):
        for u in G.predecessors(node_id):
            # Tránh trùng lặp nếu là đường 2 chiều đã nằm trong danh sách đi ra
            if u in G.neighbors(node_id):
                continue
                
            edge_data = G.get_edge_data(u, node_id)
            
            length = 1.0
            if edge_data is not None:
                if "length" in edge_data:
                    length = float(edge_data["length"])
                elif isinstance(edge_data, dict):
                    lengths = []
                    for d in edge_data.values():
                        if isinstance(d, dict) and "length" in d:
                            lengths.append(float(d["length"]))
                    if lengths:
                        length = min(lengths)
            
            highway = "unknown"
            if edge_data is not None:
                if "highway" in edge_data:
                    highway = edge_data["highway"]
                elif isinstance(edge_data, dict):
                    for d in edge_data.values():
                        if isinstance(d, dict) and "highway" in d:
                            highway = d["highway"]
                            break
            
            coords = []
            best_geom = None
            if edge_data is not None:
                if "geometry" in edge_data:
                    best_geom = edge_data["geometry"]
                elif isinstance(edge_data, dict):
                    for d in edge_data.values():
                        if isinstance(d, dict) and "geometry" in d:
                            best_geom = d["geometry"]
                            break
                            
            if best_geom is not None:
                try:
                    if hasattr(best_geom, "coords"):
                        coords = [(float(pt[1]), float(pt[0])) for pt in best_geom.coords]
                    elif isinstance(best_geom, list):
                        coords = [(float(pt[1]), float(pt[0])) for pt in best_geom]
                except Exception:
                    pass
            
            if not coords:
                coords = [
                    (G.nodes[u]["y"], G.nodes[u]["x"]),
                    (G.nodes[node_id]["y"], G.nodes[node_id]["x"])
                ]
                
            adj_edges.append({
                "u": u,
                "v": node_id,
                "u_lat": G.nodes[u]["y"],
                "u_lon": G.nodes[u]["x"],
                "v_lat": G.nodes[node_id]["y"],
                "v_lon": G.nodes[node_id]["x"],
                "length_m": round(length, 1),
                "highway": str(highway),
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


# ── API tìm nút giao gần nhất ────────────────────────────────────────────────

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
        raise HTTPException(500, f"Lỗi tìm nút giao gần nhất: {str(e)}")


@app.get("/api/graph/nearest-edge", tags=["Graph"])
def get_nearest_edge(lat: float, lon: float):
    _require_graph()
    try:
        u, v, k = GS.nearest_edge(lat, lon)
        G = GS.G
        edge_data = G.get_edge_data(u, v, k)
        
        length = float(edge_data.get("length", 1.0))
        highway = str(edge_data.get("highway", "unknown"))
        
        coords = []
        best_geom = edge_data.get("geometry")
        if best_geom is not None:
            try:
                if hasattr(best_geom, "coords"):
                    coords = [(float(pt[1]), float(pt[0])) for pt in best_geom.coords]
                elif isinstance(best_geom, list):
                    coords = [(float(pt[1]), float(pt[0])) for pt in best_geom]
            except Exception:
                pass
                
        if not coords:
            coords = [
                (G.nodes[u]["y"], G.nodes[u]["x"]),
                (G.nodes[v]["y"], G.nodes[v]["x"])
            ]
            
        return {
            "u": u,
            "v": v,
            "key": k,
            "u_lat": float(G.nodes[u]["y"]),
            "u_lon": float(G.nodes[u]["x"]),
            "v_lat": float(G.nodes[v]["y"]),
            "v_lon": float(G.nodes[v]["x"]),
            "length_m": round(length, 1),
            "highway": highway,
            "coords": coords,
            "is_blocked": (u, v) in GS.blocked_edges or (v, u) in GS.blocked_edges
        }
    except Exception as e:
        raise HTTPException(500, f"Lỗi tìm cạnh gần nhất: {str(e)}")

