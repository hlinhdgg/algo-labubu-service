"""Policy 4 (exhaustive search on small trips): greedy insertion, then the best stop order.

The parcels for the trip are chosen with greedy insertion (as in greedy_insertion.py).
If the trip has at most MAX_EXHAUSTIVE_STOPS different stops, every possible order of
those stops is tried and the one with the lowest route_cost (least service lost,
then shortest distance) is kept -- the exact best order, not a heuristic one. Bigger
trips keep the greedy order. See helpers.best_stop_order.

If the trip would leave nearly empty with nothing urgent on board, the truck waits
one planning round instead (helpers.worth_waiting).
"""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    best_stop_order,
    build_cheapest_insertion_route,
    preferred_budget,
    worth_waiting,
)

MAX_EXHAUSTIVE_STOPS = 8


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build one trip with greedy insertion; re-order small trips by trying every order."""

    departure_time = context["current_time"] + context["departure_delay"]
    budget = preferred_budget(context)
    route = build_cheapest_insertion_route(parcel, context, budget=budget)
    if worth_waiting(route, parcel, context):
        return []
    return best_stop_order(
        route, parcel, context["travel_distance"], departure_time, budget, MAX_EXHAUSTIVE_STOPS
    )
