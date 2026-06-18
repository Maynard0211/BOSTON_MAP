import heapq
import time
import math
import networkx as nx
from typing import List, Optional, Tuple, Dict, Set

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Tính khoảng cách thực tế trên mặt cầu Trái Đất (mét) sử dụng math (tốc độ cao)."""
    R = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    a = max(0.0, min(1.0, a))
    return 2 * R * math.asin(math.sqrt(a))


def _min_edge_length(edge_data) -> float:
    """Lấy trọng số (độ dài) nhỏ nhất của cạnh, hỗ trợ cả DiGraph và MultiDiGraph."""
    if edge_data is None:
        return 1.0
    
    # Trường hợp DiGraph (edge_data chứa trực tiếp thuộc tính cạnh)
    if "length" in edge_data:
        try:
            return float(edge_data["length"])
        except (TypeError, ValueError):
            return 1.0
            
    # Trường hợp MultiDiGraph (edge_data chứa các dict con đại diện cho các cạnh song song)
    if isinstance(edge_data, dict):
        lengths = []
        for d in edge_data.values():
            if isinstance(d, dict) and "length" in d:
                try:
                    lengths.append(float(d["length"]))
                except (TypeError, ValueError):
                    continue
        if lengths:
            return min(lengths)
            
    return 1.0


def dijkstra(
    G: nx.MultiDiGraph,
    source: int,
    target: int,
    blocked_edges: Set[Tuple[int, int]] = None
) -> Tuple[Optional[List[int]], float, float]:
    """
    Thuật toán Dijkstra tìm đường đi ngắn nhất.
    Hỗ trợ bỏ qua các cạnh có trong blocked_edges.
    """
    t0 = time.perf_counter()
    if blocked_edges is None:
        blocked_edges = set()

    dist = {source: 0.0}
    prev: Dict[int, Optional[int]] = {source: None}
    visited: Set[int] = set()
    pq: List[Tuple[float, int]] = [(0.0, source)]

    while pq:
        cost, u = heapq.heappop(pq)

        if u in visited:
            continue
        visited.add(u)

        if u == target:
            break

        for v in G.neighbors(u):
            # Kiểm tra xem cạnh u -> v có bị chặn hay không
            if (u, v) in blocked_edges or (v, u) in blocked_edges:
                continue
                
            w = _min_edge_length(G.get_edge_data(u, v))
            new_cost = cost + w
            if new_cost < dist.get(v, float("inf")):
                dist[v] = new_cost
                prev[v] = u
                heapq.heappush(pq, (new_cost, v))

    exec_time = time.perf_counter() - t0

    if target not in dist:
        return None, float("inf"), exec_time

    path = _reconstruct_path(prev, target)
    return path, dist[target], exec_time


def astar(
    G: nx.MultiDiGraph,
    source: int,
    target: int,
    blocked_edges: Set[Tuple[int, int]] = None
) -> Tuple[Optional[List[int]], float, float]:
    """
    Thuật toán A* tìm đường đi ngắn nhất sử dụng hàm heuristic Haversine.
    Hỗ trợ bỏ qua các cạnh có trong blocked_edges.
    """
    t0 = time.perf_counter()
    if blocked_edges is None:
        blocked_edges = set()

    # Tọa độ đích để tính heuristic
    tgt_y = G.nodes[target]["y"]
    tgt_x = G.nodes[target]["x"]

    def h(node: int) -> float:
        nd = G.nodes[node]
        return _haversine(nd["y"], nd["x"], tgt_y, tgt_x)

    g_score: Dict[int, float] = {source: 0.0}
    prev: Dict[int, Optional[int]] = {source: None}
    visited: Set[int] = set()
    counter = 0
    pq: List[Tuple[float, int, int]] = [(h(source), counter, source)]

    while pq:
        _, _, u = heapq.heappop(pq)

        if u in visited:
            continue
        visited.add(u)

        if u == target:
            break

        g_u = g_score[u]

        for v in G.neighbors(u):
            if v in visited:
                continue
                
            # Kiểm tra xem cạnh u -> v có bị chặn hay không
            if (u, v) in blocked_edges or (v, u) in blocked_edges:
                continue

            w = _min_edge_length(G.get_edge_data(u, v))
            tentative_g = g_u + w

            if tentative_g < g_score.get(v, float("inf")):
                g_score[v] = tentative_g
                prev[v] = u
                f_v = tentative_g + h(v)
                counter += 1
                heapq.heappush(pq, (f_v, counter, v))

    exec_time = time.perf_counter() - t0

    if target not in g_score:
        return None, float("inf"), exec_time

    path = _reconstruct_path(prev, target)
    return path, g_score[target], exec_time



def _reconstruct_path(prev: dict, target: int) -> List[int]:
    path: List[int] = []
    node: Optional[int] = target
    while node is not None:
        path.append(node)
        node = prev.get(node)
    path.reverse()
    return path


def path_to_coordinates(
    G: nx.MultiDiGraph, path: List[int]
) -> List[Tuple[float, float]]:
    """
    Chuyển danh sách node_id thành [(lat, lon), ...] dọc theo đường đi thực tế.
    Hàm này cố gắng lấy thuộc tính 'geometry' (LineString) của các cạnh để vẽ đường cong 
    mềm mại trên bản đồ. Nếu không có geometry, nó tự động nối thẳng giữa hai node kề nhau.
    """
    coords = []
    if not path:
        return coords

    # Thêm tọa độ của node xuất phát
    coords.append((G.nodes[path[0]]["y"], G.nodes[path[0]]["x"]))

    for i in range(len(path) - 1):
        u = path[i]
        v = path[i + 1]
        edge_data = G.get_edge_data(u, v)
        
        best_geom = None
        if edge_data is not None:
            # TH DiGraph (edge_data là dict thuộc tính)
            if "geometry" in edge_data:
                best_geom = edge_data["geometry"]
            # TH MultiDiGraph (edge_data chứa các cạnh song song)
            elif isinstance(edge_data, dict):
                min_len = float('inf')
                for d in edge_data.values():
                    if isinstance(d, dict):
                        length = d.get("length", 1.0)
                        if length < min_len:
                            min_len = length
                            best_geom = d.get("geometry", None)

        if best_geom is not None:
            try:
                # Nếu là đối tượng Shapely LineString, ta lấy danh sách coords
                if hasattr(best_geom, "coords"):
                    geom_coords = list(best_geom.coords)
                elif isinstance(best_geom, list):
                    geom_coords = best_geom
                else:
                    geom_coords = []
                
                # Chuyển đổi từ (lon, lat) của GIS/Shapely sang (lat, lon) cho Folium
                for pt in geom_coords:
                    lat, lon = float(pt[1]), float(pt[0])
                    # Tránh thêm trùng lặp tọa độ ngã rẽ trùng với ngã rẽ trước
                    if not coords or (lat, lon) != coords[-1]:
                        coords.append((lat, lon))
            except Exception:
                coords.append((G.nodes[v]["y"], G.nodes[v]["x"]))
        else:
            coords.append((G.nodes[v]["y"], G.nodes[v]["x"]))

    return coords

