"""Calculate performance metrics from one simulation run's event log."""

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from simulator.loaders import day_input_paths, parse_time


def calculate_metrics(
    parcels: List[Dict[str, str]],
    distances: List[Dict[str, str]],
    config: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return a JSON-serializable dictionary for the chosen performance metric.

    Chosen metric (service_rate): the average service score over every parcel
    that arrived during the day. A parcel delivered inside its preferred window
    (boundaries included) scores 1. A parcel delivered early or late scores
    1 - (minutes outside the window / window length), and 0 once it is off by a
    whole window length or more, so being 15 minutes late costs more for a
    30-minute window than for a 3-hour one. A parcel never delivered scores 0,
    so a policy cannot raise the metric by skipping hard parcels.

    Parcels that arrive too late in the day for any truck to reach them score 0
    for every policy, so the best possible value is below 1.0. The strict
    on_time_rate (on-time deliveries out of every parcel), delivered_rate and
    on_time_rate_delivered (on-time deliveries out of the parcels delivered)
    are reported alongside it.

    parcels and distances are the rows of the day's CSV files, config is the
    contents of config.json, and events are the records from the run's log.
    CSV values are strings, so convert them before calculating. In particular,
    parcel times are "HH:MM" strings while event times are minutes after
    midnight: "17:00" is 17 * 60 = 1020.
    """

    windows = {
        row["parcel_id"]: (parse_time(row["delivery_window_start"]), parse_time(row["delivery_window_end"]))
        for row in parcels
    }

    delivery_time: Dict[str, float] = {}
    number_of_trips = 0
    for event in events:
        if event["event_type"] == "delivery":
            delivery_time[event["parcel_id"]] = event["time"]
        elif event["event_type"] == "hub_departure":
            number_of_trips += 1

    on_time_count = 0
    late_count = 0
    early_count = 0
    lateness_total = 0.0
    service_total = 0.0
    for parcel_id, (window_start, window_end) in windows.items():
        time = delivery_time.get(parcel_id)
        if time is None:
            continue
        if window_start <= time <= window_end:
            on_time_count += 1
            service_total += 1.0
            continue
        if time > window_end:
            late_count += 1
            lateness_total += time - window_end
            minutes_off = time - window_end
        else:
            early_count += 1
            minutes_off = window_start - time
        window_length = window_end - window_start
        if window_length > 0:
            service_total += max(0.0, 1.0 - minutes_off / window_length)

    total_parcels = len(windows)
    delivered_count = len(delivery_time)
    return {
        "service_rate": service_total / total_parcels if total_parcels else 0.0,
        "on_time_rate": on_time_count / total_parcels if total_parcels else 0.0,
        "delivered_rate": delivered_count / total_parcels if total_parcels else 0.0,
        "on_time_rate_delivered": on_time_count / delivered_count if delivered_count else 0.0,
        "on_time_count": on_time_count,
        "delivered_count": delivered_count,
        "total_parcels": total_parcels,
        "late_count": late_count,
        "early_count": early_count,
        "avg_lateness_minutes": lateness_total / late_count if late_count else 0.0,
        "number_of_trips": number_of_trips,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Load one day's inputs and event log, then write the metrics report."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"),
                        help="directory containing dist.csv, config.json and demand/")
    parser.add_argument("--day", required=True, help="day identifier, for example day_001")
    parser.add_argument("--log", type=Path, required=True,
                        help="event log from a simulator run")
    parser.add_argument("--output", type=Path,
                        help="JSON report (default: metrics.json beside the selected log)")
    args = parser.parse_args(argv)
    try:
        parcel_path, distance_path, config_path = day_input_paths(args.data, args.day)
        output = args.output if args.output is not None else args.log.with_name("metrics.json")
        # The input files all live in the data directory, so this also protects them.
        if output.resolve() == args.data.resolve() or args.data.resolve() in output.resolve().parents:
            raise ValueError("report output must be outside the input data directory")
        if output.resolve() == args.log.resolve():
            raise ValueError("report output must not overwrite the log")
        with parcel_path.open(newline="", encoding="utf-8-sig") as stream:
            parcels = list(csv.DictReader(stream))
        with distance_path.open(newline="", encoding="utf-8-sig") as stream:
            distances = list(csv.DictReader(stream))
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        with args.log.open(encoding="utf-8") as stream:
            events = [json.loads(line) for line in stream if line.strip()]
        metrics = calculate_metrics(parcels, distances, config, events)
        report = json.dumps(metrics, indent=2, allow_nan=False) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Metrics report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
