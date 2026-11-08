"""Policy: cluster first, route second, using a graph and breadth-first search (BFS).

Step 1 (seed): pick the most urgent parcel that a truck could deliver on its own.
Step 2 (graph): treat delivery locations as vertices of a directed graph. Each location
         is linked to its K_NEIGHBOURS nearest locations (an adjacency list, built only
         for the locations we actually visit).
Step 3 (queue + BFS): starting at the seed's location, BFS with a queue collects nearby
         locations, closest hops first, until the cluster holds MAX_CLUSTER_PARCELS parcels.
Step 4 (Greedy 2): cheapest insertion builds the route using ONLY the cluster's parcels.
Step 5: exact stop order for at most 8 stops (exhaustive search), otherwise 2-opt.

Because the cluster has a fixed maximum size, steps 4 and 5 cost a constant amount of
work however many parcels are waiting. Time: O(n) for the seed and grouping, O(n log n)
for sorting parcels inside each location, and at most O(n^2 log n) for BFS in the worst
case (each visited location sorts the other locations by distance). Typically only a few
locations are visited, so it is close to O(n log n). Space: O(n).
"""

from collections import deque
from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    HUB,
    available_parcel_ids,
    best_stop_order,
    build_cheapest_insertion_route,
    preferred_budget,
    two_opt_improve,
    urgency_key,
    worth_waiting,
)

K_NEIGHBOURS = 4  # each location is linked to this many nearest locations; try 3, 4, 6
MAX_CLUSTER_PARCELS = 40  # parcels handed to cheapest insertion; try 30, 40, 60
MAX_EXHAUSTIVE_STOPS = 8


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build one trip from a BFS cluster of parcels around the most urgent parcel."""

    distances = context["travel_distance"]
    capacity = context["capacity"]
    departure_time = context["current_time"] + context["departure_delay"]
    budget = preferred_budget(context)
    waiting = available_parcel_ids(parcel)

    # Step 1: seed = most urgent parcel that could be delivered alone (it fits, the round
    # trip is within budget, and the truck would not arrive before its window opens).
    # Parcels that can still be saved (slack >= 0) come before ones already late.
    seed = None
    for pid in waiting:
        record = parcel[pid]
        stop = record["delivery_location_id"]
        if record["size"] > capacity + 1e-9:
            continue
        if distances[HUB][stop] + distances[stop][HUB] > budget + 1e-9:
            continue
        if departure_time + distances[HUB][stop] < record["delivery_window_start"]:
            continue
        slack = urgency_key(pid, parcel, context)
        key = (slack < 0, slack, pid)
        if seed is None or key < seed[0]:
            seed = (key, pid)
    if seed is None:
        return []
    seed_id = seed[1]

    # Group the waiting parcels by location, most urgent first within each location.
    groups: Dict[str, List[str]] = {}
    for pid in waiting:
        groups.setdefault(parcel[pid]["delivery_location_id"], []).append(pid)
    for pids in groups.values():
        pids.sort(key=lambda p: (urgency_key(p, parcel, context), p))

    # Step 2: adjacency list of the nearest-neighbour graph, filled in only when needed.
    adjacency: Dict[str, List[str]] = {}

    def neighbours(location: str) -> List[str]:
        if location not in adjacency:
            others = [other for other in groups if other != location]
            others.sort(key=lambda other: (distances[location][other], other))
            adjacency[location] = others[:K_NEIGHBOURS]
        return adjacency[location]

    # Step 3: BFS with a queue collects the cluster, nearest hops first.
    seed_location = parcel[seed_id]["delivery_location_id"]
    cluster: List[str] = []
    queue = deque([seed_location])
    seen = {seed_location}
    while queue and len(cluster) < MAX_CLUSTER_PARCELS:
        location = queue.popleft()
        cluster.extend(groups[location])
        for neighbour in neighbours(location):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    cluster = cluster[:MAX_CLUSTER_PARCELS]
    if seed_id not in cluster:
        cluster.append(seed_id)

    # Step 4: cheapest insertion on the cluster only.
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=cluster, hold_early=True
    )
    if worth_waiting(route, parcel, context):
        return []

    # Step 5: exact order for small trips, 2-opt for larger ones.
    stops = {parcel[pid]["delivery_location_id"] for pid in route}
    if len(stops) <= MAX_EXHAUSTIVE_STOPS:
        return best_stop_order(
            route, parcel, distances, departure_time, budget, MAX_EXHAUSTIVE_STOPS
        )
    return two_opt_improve(route, parcel, distances, departure_time, budget, max_passes=3)
