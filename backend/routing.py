"""
backend/routing.py — Shortest Path Algorithms (Dijkstra & A*)
============================================================
Provides Dijkstra and A* pathfinding implementations with dynamic road blocking
and detailed geometric coordinates reconstruction for map rendering.
"""

import heapq
import time
import math
from typing import List, Optional, Tuple, Dict, Set
import networkx as nx


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """High-speed Haversine distance using math standard library (meters)."""
    R = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    a = max(0.0, min(1.0, a))
    return 2 * R * math.asin(math.sqrt(a))


def _min_edge_length(edge_data) -> float:
    """Extracts minimum valid length from edge data (supports DiGraph & MultiDiGraph)."""
    if edge_data is None:
        return 1.0

    # DiGraph case
    if "length" in edge_data:
        try:
            return float(edge_data["length"])
        except (TypeError, ValueError):
            return 1.0

    # MultiDiGraph case (dictionary of parallel edge attributes)
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
    Dijkstra shortest path algorithm.
    Skips edges present in blocked_edges.
    Returns: (path_node_ids, total_distance_m, execution_time_s)
    """
    t0 = time.perf_counter()
    if blocked_edges is None:
        blocked_edges = set()

    dist: Dict[int, float] = {source: 0.0}
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
    A* algorithm using Haversine admissible heuristic to guide search.
    Skips edges present in blocked_edges.
    Returns: (path_node_ids, total_distance_m, execution_time_s)
    """
    t0 = time.perf_counter()
    if blocked_edges is None:
        blocked_edges = set()

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
    Transforms sequence of node IDs into high-resolution [(lat, lon), ...] coordinates.
    Utilizes GIS LineString geometry if available, falling back to node endpoints.
    """
    coords = []
    if not path:
        return coords

    # Start node coordinate
    coords.append((G.nodes[path[0]]["y"], G.nodes[path[0]]["x"]))

    for i in range(len(path) - 1):
        u = path[i]
        v = path[i + 1]
        edge_data = G.get_edge_data(u, v)

        best_geom = None
        if edge_data is not None:
            if "geometry" in edge_data:
                best_geom = edge_data["geometry"]
            elif isinstance(edge_data, dict):
                min_len = float("inf")
                for d in edge_data.values():
                    if isinstance(d, dict):
                        length = d.get("length", 1.0)
                        if length < min_len:
                            min_len = length
                            best_geom = d.get("geometry", None)

        if best_geom is not None:
            try:
                if hasattr(best_geom, "coords"):
                    geom_coords = list(best_geom.coords)
                elif isinstance(best_geom, list):
                    geom_coords = best_geom
                else:
                    geom_coords = []

                for pt in geom_coords:
                    lat, lon = float(pt[1]), float(pt[0])
                    if not coords or (lat, lon) != coords[-1]:
                        coords.append((lat, lon))
            except Exception:
                coords.append((G.nodes[v]["y"], G.nodes[v]["x"]))
        else:
            coords.append((G.nodes[v]["y"], G.nodes[v]["x"]))

    return coords
