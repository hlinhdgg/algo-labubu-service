"""Recommended policy: cheapest insertion in priority stages, using the fleet's return times.

Each truck builds one trip, adding the parcels most at risk first:

1. last-chance parcels: this is the last round they can be sent and still return in time;
2. must-take parcels: no truck coming back could still deliver them on time;
3. other tight parcels: at most SLACK_THRESHOLD minutes to spare;
4. relaxed parcels as filler: only if no stop misses its window and the detour is small.

A parcel is never placed where the truck would arrive before its window opens. A nearly
empty truck may wait one round so it stays free for later parcels. Trips with at most
MAX_EXHAUSTIVE_STOPS stops are then put in the exact best order.
"""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    HUB, WAIT_MIN_LOAD, available_parcel_ids, best_stop_order,
    build_cheapest_insertion_route, next_truck_gap, preferred_budget, route_arrival_times,
    route_distance, urgency_key, worth_waiting,
)

MAX_EXHAUSTIVE_STOPS = 8  # 8! = 40,320 orders; 10 stops would be about 3.6 million.
SLACK_THRESHOLD = 180.0  # A parcel with at most this many minutes to spare is "tight".
FILLER_MAX_DETOUR = 20.0  # Most km one filler parcel may add, so morning trips stay short.
ENDGAME_MINUTES = 150.0  # How long before the cut-off end-of-day waiting applies.
PLANNING_ROUND = 10.0  # Minutes between planning rounds (fixed by the brief).


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
    # Stage 1: without this, trucks could wait while these parcels ran out of time.
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=_last_chance_parcels(parcel, context), hold_early=True
    )

    # Sort the other parcels into stages 2 to 4.
    gap = next_truck_gap(context)
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

    # Stages 2 and 3.
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=must_take, start_route=route, hold_early=True
    )
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=tight, start_route=route, hold_early=True
    )
    # Stage 4: filler must not make any stop miss its window.
    route = build_cheapest_insertion_route(
        parcel, context, candidate_ids=relaxed, start_route=route,
        max_new_violations=0, hold_early=True, max_detour=FILLER_MAX_DETOUR,
    )
    # Wait one round if the trip is nearly empty and nothing on it is at risk.
    if worth_waiting(route, parcel, context) or _endgame_wait(route, parcel, context):
        return []
    departure_time = context["current_time"] + context["departure_delay"]
    return best_stop_order(
        route, parcel, context["travel_distance"], departure_time,
        preferred_budget(context), MAX_EXHAUSTIVE_STOPS
    )
