"""Greedy fleet-aware policy with relocate-move local search.

Approved techniques used:
* heap-based urgency ordering through the shared greedy builder;
* greedy cheapest insertion;
* local search by relocating one stop at a time;
* 2-opt local search;
* lists, dictionaries and sets.
"""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    available_parcel_ids,
    build_cheapest_insertion_route,
    effective_budget,
    is_feasible,
    route_cost,
    two_opt_improve,
    urgency_key,
    worth_waiting,
)


SLACK_THRESHOLD = 180.0


def _next_truck_gap(context: SimulationContext) -> float:
    now = context["current_time"]
    delay = context["departure_delay"]
    departures = [
        vehicle["available_at"] + delay
        for vehicle_id, vehicle in context["fleet"].items()
        if vehicle_id != context["vehicle_id"] and vehicle["available_at"] > now
    ]
    if not departures:
        return float("inf")
    return min(departures) - (now + delay)


def _build_route(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    gap = _next_truck_gap(context)
    must_take: List[str] = []
    tight: List[str] = []
    relaxed: List[str] = []

    for parcel_id in available_parcel_ids(parcel):
        slack = urgency_key(parcel_id, parcel, context)
        if 0 <= slack < gap and slack <= SLACK_THRESHOLD:
            must_take.append(parcel_id)
        elif slack <= SLACK_THRESHOLD:
            tight.append(parcel_id)
        else:
            relaxed.append(parcel_id)

    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=must_take, hold_early=True
    )
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=tight, start_route=route, hold_early=True
    )
    return build_cheapest_insertion_route(
        parcel,
        context,
        candidate_ids=relaxed,
        start_route=route,
        max_new_violations=0,
        hold_early=True,
    )


def _relocate_once(
    route: List[str], parcel: Dict[str, Parcel], context: SimulationContext
) -> List[str]:
    """Apply improving single-stop relocations until one pass finds none."""

    departure = context["current_time"] + context["departure_delay"]
    distances = context["travel_distance"]
    budget = effective_budget(context)
    current = list(route)
    current_cost = route_cost(current, parcel, distances, departure)

    for _ in range(3):
        improved = False
        for source in range(len(current)):
            stop = current[source]
            without = current[:source] + current[source + 1:]
            for target in range(len(without) + 1):
                candidate = without[:target] + [stop] + without[target:]
                if not is_feasible(candidate, parcel, context):
                    continue
                candidate_cost = route_cost(candidate, parcel, distances, departure)
                if candidate_cost < current_cost:
                    current = candidate
                    current_cost = candidate_cost
                    improved = True
        if not improved:
            break
    return current


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build a fleet-aware route and improve it with relocate and 2-opt moves."""

    route = _build_route(parcel, context)
    route = _relocate_once(route, parcel, context)

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
