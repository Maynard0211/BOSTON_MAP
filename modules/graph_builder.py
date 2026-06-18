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
    """Pipeline đầy đủ: Parse PBF → Build Graph → Lưu .pkl. Fallback về đồ thị mô phỏng (Dummy Graph) nếu lỗi pyrosm."""
    try:
        nodes, edges = parse_osm_network(pbf_path)
        G = build_graph(nodes, edges)
        logger.info("Tạo lập đồ thị thực tế từ PBF thành công.")
    except Exception as e:
        logger.warning("Không tạo lập được đồ thị thực tế (lỗi: %s). Hệ thống tự động chuyển sang tạo đồ thị mô phỏng (Dummy Graph) Boston để chạy thử ứng dụng...", str(e))
        G = build_dummy_graph()

    with open(output_path, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Đã lưu đồ thị vào %s", output_path)
    return G


def build_dummy_graph() -> nx.MultiDiGraph:
    """Tạo đồ thị mô phỏng liên thông giữa các địa điểm nổi tiếng ở Boston."""
    G = nx.MultiDiGraph()
    
    # 1. Các địa điểm presets và tọa độ của chúng
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
        
        # Một số nút giao trung gian để tạo đường vòng
        13: ("Cambridge St Intersection",  42.3700, -71.1050),
        14: ("Broadway Crossing",          42.3650, -71.0950),
        15: ("Charles River Bridge East",  42.3610, -71.0750),
        16: ("Charles River Bridge West",  42.3590, -71.0850),
        17: ("Commonwealth Ave Junc",      42.3490, -71.0850),
        18: ("Downtown Crossing",          42.3550, -71.0600),
    }
    
    # Thêm nodes
    for nid, (name, lat, lon) in locations.items():
        G.add_node(nid, x=lon, y=lat, name=name)
        
    # 2. Định nghĩa các cạnh nối và thuộc tính
    # Cấu trúc: (u, v, highway)
    edges_to_add = [
        # Tuyến phía Bắc (Harvard - Cambridge - Broadway - MIT)
        (1, 13, "primary"), (13, 14, "primary"), (14, 2, "primary"),
        # Đường vòng phụ qua Charles River West
        (1, 16, "secondary"), (16, 2, "secondary"),
        # MIT sang Charles River East sang Boston Common/City Hall
        (2, 15, "primary"), (15, 3, "primary"), (15, 18, "primary"),
        # Charles River West nối sang Charles River East
        (16, 15, "secondary"),
        # Boston Common - City Hall - Quincy Market - Logan Airport
        (3, 18, "primary"), (18, 6, "primary"), (6, 7, "primary"), 
        (7, 4, "motorway"), (18, 4, "motorway"),
        # MIT sang Fenway Park
        (2, 5, "primary"),
        # Fenway Park sang Northeastern sang MFA
        (5, 17, "secondary"), (17, 8, "primary"), (8, 12, "primary"),
        # MFA sang Children's Hospital
        (12, 9, "secondary"),
        # Children's Hospital sang Tufts Medical
        (9, 11, "secondary"),
        # Tufts Medical sang South Station sang Boston Common
        (11, 10, "primary"), (10, 3, "primary"), (10, 18, "primary"),
        # Northeastern sang Tufts Medical
        (8, 11, "primary"),
        # Boston Common sang Fenway Park trực tiếp
        (3, 17, "secondary"),
        # Logan Airport sang South Station qua đường ngầm
        (4, 10, "motorway")
    ]
    
    # Add các cạnh vào đồ thị (2 chiều)
    for u, v, hw in edges_to_add:
        ud = G.nodes[u]
        vd = G.nodes[v]
        dist = haversine_distance(ud["y"], ud["x"], vd["y"], vd["x"])
        attrs = {
            "length": dist,
            "highway": hw,
            "oneway": False
        }
        G.add_edge(u, v, **attrs)
        G.add_edge(v, u, **attrs)
        
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
