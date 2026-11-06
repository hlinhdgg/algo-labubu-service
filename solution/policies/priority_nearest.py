"""Urgency-heap plus nearby greedy insertion policy.

Approved techniques used:
* binary-heap priority queue for urgency;
* greedy cheapest insertion;
* nearest/nearby stop selection through the helper's shortlist;
* 2-opt local search;
* lists, dictionaries and sets.
"""

import heapq
from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    available_parcel_ids,
    build_cheapest_insertion_route,
    effective_budget,
    two_opt_improve,
    urgency_key,
    worth_waiting,
)


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build a route by urgency first, then by nearby greedy insertion."""

    heap = []
    for parcel_id in available_parcel_ids(parcel):
        heapq.heappush(heap, (urgency_key(parcel_id, parcel, context), parcel_id))

    candidates = []
    while heap:
        _, parcel_id = heapq.heappop(heap)
        candidates.append(parcel_id)

    route = build_cheapest_insertion_route(
        parcel,
        context,
        candidate_ids=candidates,
        shortlist_by="nearby",
        hold_early=True,
    )

    departure = context["current_time"] + context["departure_delay"]
    route = two_opt_improve(
        route,
        parcel,
        context["travel_distance"],
        departure,
        effective_budget(context),
        max_passes=3,
    )

    if worth_waiting(route, parcel, context):
        return []
    return route
