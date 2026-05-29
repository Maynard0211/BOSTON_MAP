import os
import pickle
import logging
import numpy as np
import networkx as nx

logger = logging.getLogger(__name__)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách thực tế trên mặt cầu Trái Đất (mét)."""
    R = 6_371_000.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi   = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))

# Spatial Data Parsing

def parse_osm_network(pbf_path: str):
    """
    Đọc file .pbf, trích xuất mạng lưới driving.
    Trả về (nodes GeoDataFrame, edges GeoDataFrame).
    """
    try:
        import pyrosm
    except ImportError:
        raise ImportError("Thư viện pyrosm chưa được cài. Chạy: pip install pyrosm")

    logger.info("Đang đọc file PBF: %s", pbf_path)
    osm = pyrosm.OSM(pbf_path)

    logger.info("Trích xuất mạng lưới driving...")
    nodes, edges = osm.get_network(network_type="driving", nodes=True)

    if nodes is None or edges is None or len(nodes) == 0:
        raise ValueError("Không trích xuất được mạng lưới từ file PBF.")

    logger.info("Thô: %d nodes, %d edges", len(nodes), len(edges))
    return nodes, edges

# Graph Modeling

def _safe_float(val, default=0.0):
    try:
        v = float(val)
        return v if np.isfinite(v) and v >= 0 else default
    except (TypeError, ValueError):
        return default


def _is_oneway(val) -> bool:
    return val in (True, 1, "yes", "true", "1", "-1", "Yes")


def build_graph(nodes, edges) -> nx.MultiDiGraph:
    """
    Chuyển đổi GeoDataFrame -> NetworkX MultiDiGraph.
    Trọng số cạnh = chiều dài đoạn đường (Haversine, đơn vị mét).
    """
    G = nx.MultiDiGraph()

    # Nodes
    for _, row in nodes.iterrows():
        nid = int(row["id"])
        if "lon" in row and "lat" in row:
            x, y = float(row["lon"]), float(row["lat"])
        else:                                         # lấy từ geometry
            x, y = row["geometry"].x, row["geometry"].y
        G.add_node(nid, x=x, y=y)

    node_set = set(G.nodes())

    # Edges
    for _, row in edges.iterrows():
        u = int(row["u"])
        v = int(row["v"])
        if u not in node_set or v not in node_set:
            continue

        # Chiều dài
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

    # Làm sạch
    # Loại bỏ node cô lập
    isolated = list(nx.isolates(G))
    G.remove_nodes_from(isolated)
    logger.info("Loại %d isolated nodes", len(isolated))

    # Chỉ giữ thành phần liên thông lớn nhất
    if G.number_of_nodes() > 0:
        wcc = max(nx.weakly_connected_components(G), key=len)
        G = G.subgraph(wcc).copy()

    logger.info("Đồ thị sạch: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def build_and_save_graph(pbf_path: str, output_path: str = "boston_graph.pkl") -> nx.MultiDiGraph:
    """Pipeline đầy đủ: Parse PBF → Build Graph → Lưu .pkl."""
    nodes, edges = parse_osm_network(pbf_path)
    G = build_graph(nodes, edges)
    with open(output_path, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Đã lưu đồ thị vào %s", output_path)
    return G


def load_graph(graph_path: str) -> nx.MultiDiGraph:
    with open(graph_path, "rb") as f:
        return pickle.load(f)

# Node Lookup Helpers

def get_node_arrays(G: nx.MultiDiGraph):
    """
    Trả về numpy arrays (node_ids, lats, lons) để tìm node nhanh.
    Gọi một lần sau khi load đồ thị rồi cache kết quả.
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
    """Tìm node gần nhất với tọa độ (lat, lon) bằng vectorized Haversine."""
    dlat = np.radians(lats - lat)
    dlon = np.radians(lons - lon)
    a = (np.sin(dlat / 2) ** 2
         + np.cos(np.radians(lat)) * np.cos(np.radians(lats)) * np.sin(dlon / 2) ** 2)
    distances = 2 * 6_371_000.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return int(node_ids[np.argmin(distances)])
