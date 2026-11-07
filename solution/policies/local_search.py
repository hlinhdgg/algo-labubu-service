"""Policy 3 (local search): cheapest-insertion construction, then improve the stop order.

Builds a route with cheapest insertion, then improves its order:

- small trips (at most MAX_EXHAUSTIVE_STOPS stops) get the exact best order by trying
  every order (helpers.best_stop_order, as in exhaustive_small.py);
- bigger trips, where trying every order is too slow, get a 2-opt local search:
  reverse segments of the route to un-cross tangled stops, keeping a reversal only
  when it reduces service lost or distance.

Both only ever accept an improvement, so a single decision can never score worse
than the unimproved trip for the same parcels -- any difference over a full 20-day
run comes from how a changed trip changes when a truck gets back to the hub.

If the trip would leave nearly empty with nothing urgent on board, the truck waits
one planning round instead (helpers.worth_waiting).
"""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    best_stop_order,
    build_cheapest_insertion_route,
    preferred_budget,
    two_opt_improve,
    worth_waiting,
)

MAX_2OPT_PASSES = 3
MAX_EXHAUSTIVE_STOPS = 8


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build one trip, then improve its order: exact for small trips, 2-opt for big ones."""

    distances = context["travel_distance"]
    departure_time = context["current_time"] + context["departure_delay"]
    budget = preferred_budget(context)
    route = build_cheapest_insertion_route(parcel, context, budget=budget)
    if worth_waiting(route, parcel, context):
        return []
    if len({parcel[parcel_id]["delivery_location_id"] for parcel_id in route}) <= MAX_EXHAUSTIVE_STOPS:
        return best_stop_order(route, parcel, distances, departure_time, budget, MAX_EXHAUSTIVE_STOPS)
    return two_opt_improve(route, parcel, distances, departure_time, budget, max_passes=MAX_2OPT_PASSES)
