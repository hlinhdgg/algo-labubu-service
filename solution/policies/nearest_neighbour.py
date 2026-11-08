"""Nearest neighbour: Greedy 1 on a heap shortlist of the most urgent parcels.

Step 1 (priority queue): heapq.nsmallest picks the TOP_K parcels with the earliest
         delivery_window_end, so the greedy only looks at parcels that matter soonest.
Step 2 (Greedy 1): start at the hub and repeatedly drive to the nearest shortlisted
         parcel that still fits (capacity, distance budget, 18:00 return). Parcels at
         the current stop are at distance 0, so they are picked up first.

Time: O(n log K) for the shortlist + O(m * K) for the greedy walk (m = parcels on the
route, m <= K). Space: O(n) for the list of available parcels.
"""

import heapq
from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    HUB,
    available_parcel_ids,
    preferred_budget,
    worth_waiting,
)

TOP_K = 30  # how many of the most urgent parcels the greedy may choose from


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build one route by always moving to the nearest feasible shortlisted parcel."""

    distances = context["travel_distance"]
    capacity = context["capacity"]
    budget = preferred_budget(context)

    shortlist = heapq.nsmallest(
        TOP_K,
        available_parcel_ids(parcel),
        key=lambda pid: (parcel[pid]["delivery_window_end"], pid),
    )
    remaining = set(shortlist)

    route: List[str] = []
    load = 0.0
    here = HUB
    travelled = 0.0
    while remaining:
        best = None  # (distance from here, parcel id)
        for pid in sorted(remaining):  # fixed order so ties resolve the same way each run
            record = parcel[pid]
            stop = record["delivery_location_id"]
            if load + record["size"] > capacity + 1e-9:
                continue
            step = distances[here][stop]
            if travelled + step + distances[stop][HUB] > budget + 1e-9:
                continue
            if best is None or step < best[0]:
                best = (step, pid)
        if best is None:  # nothing left fits
            break
        step, pid = best
        record = parcel[pid]
        route.append(pid)
        remaining.discard(pid)
        load += record["size"]
        travelled += step
        here = record["delivery_location_id"]

    if worth_waiting(route, parcel, context):
        return []
    return route
