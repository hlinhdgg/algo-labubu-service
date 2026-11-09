"""Policy 5: hash map of parcels per stop + heap of stops by deadline.

Step 1 (hash map): group the unassigned parcels by delivery_location_id in a dict, so
         every parcel for the same stop is delivered together (zero extra distance).
Step 2 (heap): push (earliest deadline in the group, location) for every group and pop
         the most urgent location first. Load as many of that stop's parcels as fit,
         most urgent first. Skip a stop if driving there would break the distance budget.
Step 3 (exhaustive search): if the trip has at most 8 stops, re-order the stops with
         helpers.best_stop_order (it keeps the original order when that is already best).

Time: O(n) grouping + O(L log L) heap over L locations + O(n log n) sorting inside the
groups + O(8! * n) exhaustive search (constant factor) = O(n log n). Space: O(n).
"""

import heapq
from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    HUB,
    available_parcel_ids,
    best_stop_order,
    preferred_budget,
    worth_waiting,
)

MAX_EXHAUSTIVE_STOPS = 8


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Group parcels by stop, visit stops in deadline order, then tidy small routes."""

    distances = context["travel_distance"]
    capacity = context["capacity"]
    departure_time = context["current_time"] + context["departure_delay"]
    budget = preferred_budget(context)

    # Hash map: location id -> parcel ids waiting for that location.
    groups: Dict[str, List[str]] = {}
    for pid in available_parcel_ids(parcel):
        groups.setdefault(parcel[pid]["delivery_location_id"], []).append(pid)

    # Heap of locations keyed by the earliest deadline among their parcels.
    heap = [
        (min(parcel[pid]["delivery_window_end"] for pid in pids), location)
        for location, pids in groups.items()
    ]
    heapq.heapify(heap)

    route: List[str] = []
    load = 0.0
    here = HUB
    travelled = 0.0
    while heap:
        _, location = heapq.heappop(heap)
        out = travelled + distances[here][location]
        if out + distances[location][HUB] > budget + 1e-9:
            continue
        added = False
        for pid in sorted(groups[location], key=lambda p: (parcel[p]["delivery_window_end"], p)):
            size = parcel[pid]["size"]
            if load + size <= capacity + 1e-9:
                route.append(pid)
                load += size
                added = True
        if added:  # only move the truck if we actually loaded something here
            here = location
            travelled = out

    if worth_waiting(route, parcel, context):
        return []
    return best_stop_order(
        route, parcel, distances, departure_time, budget, MAX_EXHAUSTIVE_STOPS
    )
