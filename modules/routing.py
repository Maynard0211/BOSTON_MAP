import heapq
import time
import networkx as nx
from typing import List, Optional, Tuple


def _min_edge_length(edge_dict: dict) -> float:
    return min((d.get("length", 1.0) for d in edge_dict.values()), default=1.0)


# Dijkstra

def dijkstra(
    G: nx.MultiDiGraph,
    source: int,
    target: int,
) -> Tuple[Optional[List[int]], float, float]:
   
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
            if v in visited:
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


# Helpers

def _reconstruct_path(prev: dict, target: int) -> List[int]:
    """Truy vết ngược từ target về source để dựng lại lộ trình."""
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
    
#   Chuyển node_id thành [(lat, lon), ...]
    return [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]