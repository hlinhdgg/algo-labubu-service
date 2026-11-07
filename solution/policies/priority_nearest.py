"""Cheapest insertion that shortlists parcels near the route, then a 2-opt pass."""

from typing import Dict, List

from simulator.models import Parcel, SimulationContext
from solution.policies.helpers import (
    build_cheapest_insertion_route,
    effective_budget,
    two_opt_improve,
    worth_waiting,
)


def dispatch(parcel: Dict[str, Parcel], context: SimulationContext) -> List[str]:
    """Build a route from a heap shortlist of nearby parcels, then improve it with 2-opt."""

    route = build_cheapest_insertion_route(
        parcel,
        context,
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
