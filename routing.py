"""
Task 3: Cài đặt thuật toán tìm đường
  - Dijkstra  : Priority Queue, tìm đường ngắn nhất tuyệt đối
  - A* (A-Star): Dijkstra + Hàm heuristic Haversine để hướng thẳng về đích
"""

import heapq
import time
import numpy as np
import networkx as nx
from typing import List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Haversine heuristic (dùng chung cho A*)
# ──────────────────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _min_edge_length(edge_dict: dict) -> float:
    """Lấy trọng số nhỏ nhất trong tập multi-edge giữa hai node."""
    return min((d.get("length", 1.0) for d in edge_dict.values()), default=1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Dijkstra
# ──────────────────────────────────────────────────────────────────────────────

def dijkstra(
    G: nx.MultiDiGraph,
    source: int,
    target: int,
) -> Tuple[Optional[List[int]], float, float]:
    """
    Thuật toán Dijkstra với min-heap.

    Returns
    -------
    path        : danh sách node_id từ source → target  (None nếu không có đường)
    total_dist  : tổng chiều dài (mét)
    exec_time   : thời gian xử lý (giây)
    """
    t0 = time.perf_counter()

    dist = {source: 0.0}
    prev: dict[int, Optional[int]] = {source: None}
    visited: set[int] = set()
    pq: list[tuple[float, int]] = [(0.0, source)]

    while pq:
        cost, u = heapq.heappop(pq)

        if u in visited:
            continue
        visited.add(u)

        if u == target:
            break

        for v in G.neighbors(u):
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


# ──────────────────────────────────────────────────────────────────────────────
# A* (A-Star)
# ──────────────────────────────────────────────────────────────────────────────

def astar(
    G: nx.MultiDiGraph,
    source: int,
    target: int,
) -> Tuple[Optional[List[int]], float, float]:
    """
    Thuật toán A* với heuristic Haversine.

    h(n) = khoảng cách đường chim bay từ n → target (mét).
    Admissible vì Haversine ≤ khoảng cách đường bộ thực tế.

    Returns
    -------
    path, total_dist, exec_time   (cùng quy ước với dijkstra)
    """
    t0 = time.perf_counter()

    # Tọa độ đích để tính heuristic
    tgt_y = G.nodes[target]["y"]
    tgt_x = G.nodes[target]["x"]

    def h(node: int) -> float:
        nd = G.nodes[node]
        return _haversine(nd["y"], nd["x"], tgt_y, tgt_x)

    g_score: dict[int, float] = {source: 0.0}
    prev: dict[int, Optional[int]] = {source: None}
    visited: set[int] = set()
    # heap entry: (f, tie-breaker-counter, node)
    counter = 0
    pq: list[tuple[float, int, int]] = [(h(source), counter, source)]

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


# ──────────────────────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────────────────────

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
    """Chuyển danh sách node_id thành [(lat, lon), ...] để vẽ PolyLine."""
    return [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]
