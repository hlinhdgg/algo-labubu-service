"""Policy 2: cheapest insertion in fleet-aware stages, then a recursive search for the best stop order.

Each truck builds one trip, adding the parcels most at risk first:

1. must-take parcels: no truck coming back could still deliver them on time;
2. other tight parcels: at most SLACK_THRESHOLD minutes to spare;
3. relaxed parcels as filler: only if no stop misses its window.

A parcel is never placed where the truck would arrive before its window opens. A nearly
empty truck may wait one round so it stays free for later parcels. Trips with at most
MAX_EXHAUSTIVE_STOPS stops are then put in the exact best order by a recursive function
that tries every stop order; longer trips are improved with 2-opt instead. Unlike
Policy 1, there is no last-chance stage and no end-of-day waiting rule.
"""

from typing import Dict, List, Tuple

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    available_parcel_ids,
    build_cheapest_insertion_route,
    effective_budget,
    next_truck_gap,
    route_cost,
    two_opt_improve,
    urgency_key,
    worth_waiting,
)


MAX_EXHAUSTIVE_STOPS = 8
SLACK_THRESHOLD = 180.0


def _urgent_groups(
    parcel: Dict[str, Parcel], context: SimulationContext
) -> Tuple[List[str], List[str], List[str]]:
    """Classify parcels by urgency and fleet availability."""

    gap = next_truck_gap(context)
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
    return must_take, tight, relaxed


def _recursive_order(
    prefix: List[str],
    remaining: set[str],
    parcel_by_location: Dict[str, List[str]],
    parcel: Dict[str, Parcel],
    context: SimulationContext,
    departure: float,
    budget: float,
    best: Dict[str, object],
) -> None:
    """Recursively enumerate every stop order for a small route."""

    if not remaining:
        route = [pid for location in prefix for pid in parcel_by_location[location]]
        loss, distance = route_cost(route, parcel, context["travel_distance"], departure)
        if distance <= budget + 1e-9:
            current = best.get("value")
            value = (loss, distance)
            if current is None or value < current:
                best["value"] = value
                best["route"] = route
        return

    for location in sorted(remaining):
        prefix.append(location)
        remaining.remove(location)
        _recursive_order(
            prefix,
            remaining,
            parcel_by_location,
            parcel,
            context,
            departure,
            budget,
            best,
        )
        remaining.add(location)
        prefix.pop()


def _order_route(
    route: List[str], parcel: Dict[str, Parcel], context: SimulationContext
) -> List[str]:
    """Use recursive exhaustive search for small routes and 2-opt otherwise."""

    distances = context["travel_distance"]
    departure = context["current_time"] + context["departure_delay"]
    budget = effective_budget(context)

    by_location: Dict[str, List[str]] = {}
    for parcel_id in route:
        by_location.setdefault(parcel[parcel_id]["delivery_location_id"], []).append(parcel_id)

    if len(by_location) <= MAX_EXHAUSTIVE_STOPS:
        result: Dict[str, object] = {}
        _recursive_order(
            [],
            set(by_location),
            by_location,
            parcel,
            context,
            departure,
            budget,
            result,
        )
        if result.get("route") is not None:
            return list(result["route"])

    return two_opt_improve(route, parcel, distances, departure, budget, max_passes=3)


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Construct and improve one fleet-aware trip."""

    must_take, tight, relaxed = _urgent_groups(parcel, context)

    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=must_take, hold_early=True
    )
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=tight, start_route=route, hold_early=True
    )
    route = build_cheapest_insertion_route(
        parcel,
        context,
        candidate_ids=relaxed,
        start_route=route,
        max_new_violations=0,
        hold_early=True,
    )

    if worth_waiting(route, parcel, context):
        return []
    return _order_route(route, parcel, context)
