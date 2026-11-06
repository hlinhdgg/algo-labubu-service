"""Shared building blocks for our dispatch policies: feasibility checks, route-cost
measurement, cheapest-slot search, urgency ranking, a 2-opt cleanup pass, an
exhaustive stop-order search for small trips and the wait-if-nearly-empty rule.

Every policy in this package reuses these instead of repeating the same checks.
"""

import heapq
from itertools import permutations
from typing import Dict, List, Optional, Sequence, Tuple

from simulator.models import Parcel, SimulationContext

HUB = "HUB"

# Our own, tighter distance target (as a fraction of the real per-trip range), so a
# truck turns around and gets back to the hub sooner instead of always maxing out one
# long trip. Not a brief requirement -- just a tuned stopping condition for our own
# greedy-insertion loop. Tuned on days 1-10: 0.8 beat 0.9 there, but lost on the
# held-out days 11-20 for every policy tested, so 0.9 is kept (see README.md).
ROUTE_DISTANCE_BUDGET_FRACTION = 0.9

# Each insertion step only closely examines this many of the most urgent waiting
# parcels, instead of every single one -- keeps things fast even when hundreds of
# parcels are waiting. If none of them fit, we fall back to a full scan once before
# giving up, so this never silently strands parcels that would otherwise fit.
TOP_K = 50

# A truck stays at the hub for one planning round instead of leaving with less than
# WAIT_MIN_LOAD units, as long as every parcel it would carry has more than
# WAIT_SLACK minutes to spare (see worth_waiting). Tuned on days 1-10 with
# The waiting thresholds were tuned experimentally: 15, 20 and 25 help a lot,
# while 30 collapses;
# a slack of 30, 60 or 120 makes little difference.
WAIT_MIN_LOAD = 20.0
WAIT_SLACK = 60.0


def available_parcel_ids(parcel: Dict[str, Parcel]) -> List[str]:
    """Parcel IDs that haven't been handed to a vehicle yet."""

    return [parcel_id for parcel_id, record in parcel.items() if record["vehicle_assigned"] is None]


def effective_budget(context: SimulationContext, distance_fraction: float = 1.0) -> float:
    """The real distance budget for this trip: the tighter of range and time-to-cutoff.

    distance_fraction scales only the vehicle-range side, not the cutoff side, so we
    don't double-tighten a budget that's already shrinking naturally near the end of
    the day.
    """

    departure_time = context["current_time"] + context["departure_delay"]
    time_budget = context["return_cutoff"] - departure_time
    range_budget = context["max_trip_distance_km"] * distance_fraction
    return min(range_budget, time_budget)


def preferred_budget(context: SimulationContext) -> float:
    """Our own, tighter distance target -- see ROUTE_DISTANCE_BUDGET_FRACTION above."""

    return effective_budget(context, ROUTE_DISTANCE_BUDGET_FRACTION)


def route_distance(route: Sequence[str], parcel: Dict[str, Parcel], distances: Dict[str, Dict[str, float]]) -> float:
    """Total HUB -> ... -> HUB distance for a route (a list of parcel IDs)."""

    locations = [HUB] + [parcel[parcel_id]["delivery_location_id"] for parcel_id in route] + [HUB]
    return sum(distances[origin][destination] for origin, destination in zip(locations, locations[1:]))


def route_arrival_times(
    route: Sequence[str], parcel: Dict[str, Parcel], distances: Dict[str, Dict[str, float]], departure_time: float
) -> List[float]:
    """Delivery time (minutes after midnight) for every stop in route, in order."""

    times = []
    location = HUB
    time = departure_time
    for parcel_id in route:
        destination = parcel[parcel_id]["delivery_location_id"]
        time += distances[location][destination]
        times.append(time)
        location = destination
    return times


def window_violations(
    route: Sequence[str], parcel: Dict[str, Parcel], distances: Dict[str, Dict[str, float]], departure_time: float
) -> int:
    """How many stops in route would be delivered outside their preferred window."""

    violations = 0
    for parcel_id, arrival in zip(route, route_arrival_times(route, parcel, distances, departure_time)):
        record = parcel[parcel_id]
        if not (record["delivery_window_start"] <= arrival <= record["delivery_window_end"]):
            violations += 1
    return violations


def stop_service_lost(record: Parcel, arrival: float) -> float:
    """Service lost at one stop, as the metric scores it (0 = on time, 1 = no credit).

    Inside the window: 0. Early or late: minutes outside the window divided by the
    window's length, capped at 1 -- so the greedy minimises the same thing the
    service rate measures, instead of a plain count of missed windows.
    """

    start, end = record["delivery_window_start"], record["delivery_window_end"]
    if start <= arrival <= end:
        return 0.0
    minutes_off = arrival - end if arrival > end else start - arrival
    length = end - start
    return min(1.0, minutes_off / length) if length > 0 else 1.0


def service_lost(
    route: Sequence[str], parcel: Dict[str, Parcel], distances: Dict[str, Dict[str, float]], departure_time: float
) -> float:
    """Total service lost over every stop in route (see stop_service_lost)."""

    return sum(
        stop_service_lost(parcel[parcel_id], arrival)
        for parcel_id, arrival in zip(route, route_arrival_times(route, parcel, distances, departure_time))
    )


def route_cost(
    route: Sequence[str], parcel: Dict[str, Parcel], distances: Dict[str, Dict[str, float]], departure_time: float
) -> Tuple[float, float]:
    """Cost of one route, smaller is better: (service lost, total distance).

    Only compare this between routes that carry the SAME number of parcels (e.g. two
    orderings of the same stops, or one route with one more parcel inserted) -- it is
    not a fair way to compare routes of different lengths, since an empty route always
    looks "cheapest" by this measure.
    """

    return (service_lost(route, parcel, distances, departure_time), route_distance(route, parcel, distances))


def is_feasible(route: Sequence[str], parcel: Dict[str, Parcel], context: SimulationContext) -> bool:
    """Check capacity and the real (hard) distance budget for a candidate route."""

    total_size = sum(parcel[parcel_id]["size"] for parcel_id in route)
    if total_size > context["capacity"] + 1e-9:
        return False
    distance = route_distance(route, parcel, context["travel_distance"])
    return distance <= effective_budget(context) + 1e-9


def best_insertion_slot(
    route: Sequence[str],
    candidate_id: str,
    parcel: Dict[str, Parcel],
    distances: Dict[str, Dict[str, float]],
    departure_time: float,
    budget: float,
    capacity: float,
    max_violations: Optional[int] = None,
    hold_early: bool = False,
    max_detour: Optional[float] = None,
) -> Optional[Tuple[int, Tuple[float, float]]]:
    """Best position to insert candidate_id into route; None if it doesn't fit anywhere.

    "Best" means lowest route_cost among the len(route)+1 possible slots -- this is the
    classic TSP cheapest-insertion search, with the service lost (minutes outside each
    window, scaled by window length) as the primary thing to minimize, distance second.
    If max_violations is given, slots
    that would leave more than that many missed windows are not allowed. If hold_early
    is set, slots where the candidate itself would arrive before its window opens are
    not allowed either, so the parcel waits at the hub for a later trip instead. If
    max_detour is given, slots that would add more than that many km to a non-empty
    route are not allowed.
    """

    current_size = sum(parcel[parcel_id]["size"] for parcel_id in route)
    if current_size + parcel[candidate_id]["size"] > capacity + 1e-9:
        return None
    window_start = parcel[candidate_id]["delivery_window_start"]
    base_distance = route_distance(route, parcel, distances)
    best: Optional[Tuple[int, Tuple[float, float]]] = None
    for position in range(len(route) + 1):
        trial = route[:position] + [candidate_id] + route[position:]
        distance = route_distance(trial, parcel, distances)
        if distance > budget + 1e-9:
            continue
        if max_detour is not None and route and distance - base_distance > max_detour + 1e-9:
            continue
        times = route_arrival_times(trial, parcel, distances, departure_time)
        if hold_early and times[position] < window_start:
            continue
        if max_violations is not None:
            violations = sum(
                not (parcel[pid]["delivery_window_start"] <= time <= parcel[pid]["delivery_window_end"])
                for pid, time in zip(trial, times)
            )
            if violations > max_violations:
                continue
        cost = (sum(stop_service_lost(parcel[pid], time) for pid, time in zip(trial, times)), distance)
        if best is None or cost < best[1]:
            best = (position, cost)
    return best


def urgency_key(parcel_id: str, parcel: Dict[str, Parcel], context: SimulationContext) -> float:
    """Smaller = more urgent: minutes of slack left before the window closes.

    Measured against the PROJECTED delivery time (now + departure delay + the travel
    time from the hub straight to this parcel's stop), not the current time -- ignoring
    that lag would understate how urgent a parcel really is.
    """

    record = parcel[parcel_id]
    destination = record["delivery_location_id"]
    departure_time = context["current_time"] + context["departure_delay"]
    projected_arrival = departure_time + context["travel_distance"][HUB][destination]
    return record["delivery_window_end"] - projected_arrival


def _best_candidate(
    pool: Sequence[str],
    route: List[str],
    parcel: Dict[str, Parcel],
    distances: Dict[str, Dict[str, float]],
    departure_time: float,
    budget: float,
    capacity: float,
    max_violations: Optional[int] = None,
    hold_early: bool = False,
    max_detour: Optional[float] = None,
) -> Optional[Tuple[Tuple[float, float], str, int]]:
    """Among pool, the (cost, parcel_id, position) of the single cheapest insertion.

    pool is always walked in a fixed (sorted) order by the caller, and we only ever
    replace the running best on a strict improvement, so a tie always resolves to
    whichever candidate came first in that fixed order -- the result never depends on
    set/dict iteration order, which Python does not guarantee stays the same across
    equal-content collections built in a different sequence.
    """

    best = None
    for parcel_id in pool:
        result = best_insertion_slot(
            route, parcel_id, parcel, distances, departure_time, budget, capacity,
            max_violations, hold_early, max_detour
        )
        if result is None:
            continue
        position, cost = result
        if best is None or cost < best[0]:
            best = (cost, parcel_id, position)
    return best


def build_cheapest_insertion_route(
    parcel: Dict[str, Parcel],
    context: SimulationContext,
    candidate_ids: Optional[Sequence[str]] = None,
    top_k: int = TOP_K,
    start_route: Optional[List[str]] = None,
    budget: Optional[float] = None,
    max_new_violations: Optional[int] = None,
    hold_early: bool = False,
    shortlist_by: str = "urgency",
    max_detour: Optional[float] = None,
) -> List[str]:
    """Build one route with the TSP-style cheapest-insertion greedy.

    Repeatedly insert whichever remaining candidate has the single cheapest slot in
    the route-in-progress, until nothing more fits. Each step only closely checks the
    top_k most urgent remaining candidates (via a heap) to stay fast when hundreds of
    parcels are waiting; if none of those fit, we fall back to checking everyone once
    before giving up on this route, so a parcel that would genuinely fit is never
    skipped just because it wasn't among the most urgent.

    candidate_ids, if given, restricts which waiting parcels to consider (it does not
    fix an order -- every round re-ranks by urgency regardless of input order).

    Every round walks candidates in a fixed (sorted-by-ID) order so that ties always
    resolve the same way no matter how the candidate set was built -- see
    _best_candidate's docstring for why that matters.

    start_route continues an existing partial route instead of starting empty; budget
    overrides the default distance limit (preferred_budget); max_new_violations caps how
    many missed windows one insertion may add (0 = none); hold_early forbids slots where
    the new parcel would arrive before its window opens. shortlist_by="nearby" picks the
    top_k candidates by how close they are to a stop already on the route, instead of
    by urgency. max_detour limits how many km one insertion may add to a non-empty route.
    """

    distances = context["travel_distance"]
    departure_time = context["current_time"] + context["departure_delay"]
    if budget is None:
        budget = preferred_budget(context)
    capacity = context["capacity"]

    remaining = set(candidate_ids) if candidate_ids is not None else set(available_parcel_ids(parcel))
    route: List[str] = list(start_route) if start_route else []
    remaining.difference_update(route)

    while remaining:
        max_violations = (
            window_violations(route, parcel, distances, departure_time) + max_new_violations
            if max_new_violations is not None
            else None
        )
        pool = sorted(remaining)
        if shortlist_by == "nearby":
            stops = {HUB} | {parcel[pid]["delivery_location_id"] for pid in route}
            key = lambda pid: min(distances[stop][parcel[pid]["delivery_location_id"]] for stop in stops)
        else:
            key = lambda pid: urgency_key(pid, parcel, context)
        shortlist = heapq.nsmallest(top_k, pool, key=key)
        choice = _best_candidate(
            shortlist, route, parcel, distances, departure_time, budget, capacity,
            max_violations, hold_early, max_detour
        )
        if choice is None and len(remaining) > len(shortlist):
            choice = _best_candidate(
                pool, route, parcel, distances, departure_time, budget, capacity,
                max_violations, hold_early, max_detour
            )
        if choice is None:
            break
        _, parcel_id, position = choice
        route = route[:position] + [parcel_id] + route[position:]
        remaining.discard(parcel_id)
    return route


def two_opt_improve(
    route: List[str],
    parcel: Dict[str, Parcel],
    distances: Dict[str, Dict[str, float]],
    departure_time: float,
    budget: float,
    max_passes: int = 3,
) -> List[str]:
    """Clean up a route by reversing segments that reduce service lost/distance.

    Classic 2-opt: pick two points in the route, try reversing everything between
    them, keep the change only if route_cost improves and the route still fits the
    distance budget. Repeat up to max_passes times, stopping early once a full pass
    finds no improvement.

    The budget check matters because distances are directed (A->B can differ from
    B->A), so a reversal that reduces service lost can still make the trip longer.
    """

    best_route = list(route)
    best_cost = route_cost(best_route, parcel, distances, departure_time)
    for _ in range(max_passes):
        improved = False
        for i in range(len(best_route) - 1):
            for j in range(i + 1, len(best_route)):
                trial = best_route[:i] + best_route[i : j + 1][::-1] + best_route[j + 1 :]
                cost = route_cost(trial, parcel, distances, departure_time)
                if cost < best_cost and cost[1] <= budget + 1e-9:
                    best_route, best_cost = trial, cost
                    improved = True
        if not improved:
            break
    return best_route


def best_stop_order(
    route: List[str],
    parcel: Dict[str, Parcel],
    distances: Dict[str, Dict[str, float]],
    departure_time: float,
    budget: float,
    max_stops: int,
) -> List[str]:
    """Try every order of the route's stops and return the one with the lowest route_cost.

    All parcels for one stop are dropped together, so orders are tried over stops, not
    parcels. Routes with more than max_stops stops are returned unchanged, because the
    number of orders grows as stops! (8 stops = 40,320 orders, 10 = 3,628,800).
    """

    by_location: Dict[str, List[str]] = {}
    for parcel_id in route:
        by_location.setdefault(parcel[parcel_id]["delivery_location_id"], []).append(parcel_id)
    if len(by_location) > max_stops:
        return route

    best_route, best_cost = route, route_cost(route, parcel, distances, departure_time)
    # by_location keeps the order of first visits, so permutations() always walks
    # orders in the same sequence and ties keep the earlier (original-first) one.
    for order in permutations(by_location):
        trial = [parcel_id for stop in order for parcel_id in by_location[stop]]
        cost = route_cost(trial, parcel, distances, departure_time)
        if cost < best_cost and cost[1] <= budget + 1e-9:
            best_route, best_cost = trial, cost
    return best_route


def worth_waiting(route: Sequence[str], parcel: Dict[str, Parcel], context: SimulationContext) -> bool:
    """True if the truck should stay at the hub this round instead of leaving with route.

    Waits only when the trip is nearly empty (less than WAIT_MIN_LOAD units on board)
    and every parcel on it still has more than WAIT_SLACK minutes to spare. Slack is
    measured for a direct trip from the hub, so this is a safety margin, not a
    guarantee: over 20 days a handful of held parcels still ended up late or were
    left out of the next round's trip and never delivered. Leaving with a tiny
    load ties a truck up on a short trip just before the next wave of parcels arrives;
    waiting lets it leave fuller and keeps it ready at the hub.
    """

    if not route:
        return False
    load = sum(parcel[parcel_id]["size"] for parcel_id in route)
    if load >= WAIT_MIN_LOAD:
        return False
    return min(urgency_key(parcel_id, parcel, context) for parcel_id in route) > WAIT_SLACK
