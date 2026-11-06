"""Fleet-aware greedy dispatch policy with last-chance and endgame handling."""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    HUB, WAIT_MIN_LOAD, available_parcel_ids, best_stop_order,
    build_cheapest_insertion_route, preferred_budget, route_arrival_times,
    route_distance, urgency_key, worth_waiting,
)

MAX_EXHAUSTIVE_STOPS = 8
SLACK_THRESHOLD = 180.0
FILLER_MAX_DETOUR = 20.0
ENDGAME_MINUTES = 150.0
PLANNING_ROUND = 10.0


def _wait_for_next_truck(context: SimulationContext) -> float:
    """Return minutes until another busy truck could depart."""
    now = context["current_time"]
    delay = context["departure_delay"]
    next_departures = [
        vehicle["available_at"] + delay
        for vehicle_id, vehicle in context["fleet"].items()
        if vehicle_id != context["vehicle_id"] and vehicle["available_at"] > now
    ]
    if not next_departures:
        return float("inf")
    return min(next_departures) - (now + delay)


def _last_chance_parcels(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Find parcels that can be on time now but not if delayed one round."""
    distances = context["travel_distance"]
    cutoff = context["return_cutoff"]
    departure = context["current_time"] + context["departure_delay"]
    last_chance = []
    for parcel_id in available_parcel_ids(parcel):
        stop = parcel[parcel_id]["delivery_location_id"]
        trip = distances[HUB][stop] + distances[stop][HUB]
        arrival = departure + distances[HUB][stop]
        if (
            departure + trip <= cutoff < departure + PLANNING_ROUND + trip
            and parcel[parcel_id]["delivery_window_start"] <= arrival <= parcel[parcel_id]["delivery_window_end"]
        ):
            last_chance.append(parcel_id)
    return last_chance


def _endgame_wait(route: List[str], parcel: Dict[str, Parcel], context: SimulationContext) -> bool:
    """Return whether a small late-day route can safely wait one round."""
    if not route or context["return_cutoff"] - context["current_time"] > ENDGAME_MINUTES:
        return False
    if sum(parcel[parcel_id]["size"] for parcel_id in route) >= WAIT_MIN_LOAD:
        return False
    distances = context["travel_distance"]
    later = context["current_time"] + context["departure_delay"] + PLANNING_ROUND
    if later + route_distance(route, parcel, distances) > context["return_cutoff"]:
        return False
    arrivals = route_arrival_times(route, parcel, distances, later)
    return all(
        parcel[parcel_id]["delivery_window_start"] <= arrival <= parcel[parcel_id]["delivery_window_end"]
        for parcel_id, arrival in zip(route, arrivals)
    )


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build one route with last-chance, fleet-aware, and safe filler ordering."""
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=_last_chance_parcels(parcel, context), hold_early=True
    )
    gap = _wait_for_next_truck(context)
    must_take, tight, relaxed = [], [], []
    for parcel_id in available_parcel_ids(parcel):
        if parcel_id in route:
            continue
        slack = urgency_key(parcel_id, parcel, context)
        if 0 <= slack < gap and slack <= SLACK_THRESHOLD:
            must_take.append(parcel_id)
        elif slack <= SLACK_THRESHOLD:
            tight.append(parcel_id)
        else:
            relaxed.append(parcel_id)

    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=must_take, start_route=route, hold_early=True
    )
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=tight, start_route=route, hold_early=True
    )
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=relaxed, start_route=route,
        max_new_violations=0, hold_early=True, max_detour=FILLER_MAX_DETOUR,
    )
    if worth_waiting(route, parcel, context) or _endgame_wait(route, parcel, context):
        return []
    departure_time = context["current_time"] + context["departure_delay"]
    return best_stop_order(
        route, parcel, context["travel_distance"], departure_time,
        preferred_budget(context), MAX_EXHAUSTIVE_STOPS
    )
