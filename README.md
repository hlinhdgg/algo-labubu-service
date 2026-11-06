# IS115 Project README

Last-mile delivery dispatch. The main metric is `service_rate`, the average service score over every parcel that arrived during the day:

- delivered inside its preferred window: `1`;
- delivered early or late: `1 - minutes outside the window / window length`, capped at `0`;
- never delivered: `0`.

This gives partial credit to near-misses and prevents a policy from improving its score by skipping difficult parcels. Approximately 3.5% of parcels are too late for any truck to reach on time, so the estimated unlimited-truck ceiling is about 96.5%.

`metrics.json` also records strict `on_time_rate`, `delivered_rate`, `on_time_rate_delivered`, early and late counts, average lateness, and number of trips.

The project requires Python 3.9+ and uses the standard library only. Run commands from the project root.

## Retained policies

Only the retained policies with reasonable complexity are kept:

| Module | Approach |
|---|---|
| `solution.policies.baseline` | Greedy first-fit dispatch in arrival order with capacity, range, and cutoff checks |
| `solution.policies.fleet_aware` | Fleet-aware greedy insertion with last-chance prioritization, endgame waiting, detour-limited filler, and exhaustive ordering for small trips |
| `solution.policies.exhaustive_small` | Greedy insertion followed by exhaustive stop ordering for trips with at most 8 stops |
| `solution.policies.priority_nearest` | Binary-heap urgency ordering, greedy nearby insertion, and 2-opt local search |
| `solution.policies.relocate_local` | Fleet-aware greedy insertion followed by relocate-move local search and 2-opt |
| `solution.policies.recursive_fleet` | Binary-heap urgency ordering, greedy insertion, recursive exhaustive ordering for small trips, and 2-opt for larger trips |

All retained policies respect capacity, vehicle range, and the 18:00 return cutoff. They use service loss as the primary route objective and distance as a secondary consideration. The shared waiting rule is in `solution/policies/helpers.py`.

## Results over 20 days

| Policy | Service rate | Std dev | Worst day | Days 1-10 | Days 11-20 | Strict on-time | Delivered rate | On-time / delivered | Trips/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `fleet_aware` | **95.99%** | — | — | — | — | — | — | — | — |
| `recursive_fleet` | **93.91%** | 2.12% | 87.92% | 94.15% | 93.67% | 91.41% | 96.17% | 95.06% | 30.85 |
| `relocate_local` | 93.79% | 2.21% | 87.39% | 93.99% | 93.58% | 91.23% | 96.16% | 94.87% | 30.80 |
| `priority_nearest` | 92.61% | 3.10% | 84.80% | 92.85% | 92.38% | 89.72% | 96.17% | 93.30% | 30.95 |
| `exhaustive_small` | 92.0% | 2.3% | 88.1% | 92.2% | 91.7% | 87.0% | 95.7% | 90.8% | 30 |

`recursive_fleet` is the best retained policy at 93.91%, but it does not reach the 96% acceptance target. Delivered rate and on-time / delivered are pooled over all parcels; the other columns are averages of daily values.

## Reproduce the retained-policy results

PowerShell:

```powershell
$policies = @("baseline", "fleet_aware", "recursive_fleet", "relocate_local", "priority_nearest", "exhaustive_small")

foreach ($policy in $policies) {
    foreach ($n in 1..20) {
        $day = "day_{0:D3}" -f $n
        $output = "results\$policy\$day"
        python -m simulator --policy "solution.policies.$policy" --data data --day $day --output $output
        python -m solution.performance_monitor --data data --day $day --log "$output\log.txt"
    }
}
```

Each run writes `log.txt` and `metrics.json` under `results/<policy>/<day>/`.

## Metric-aligned routing

The retained insertion and local-search policies compare routes using service loss first and distance second. Service loss at a stop is the same scaled penalty used by `service_rate`, so a small near-miss is preferred to a much larger miss when other constraints are equal.

Small routes are exhaustively ordered because 8 stops require 40,320 orders; larger routes use bounded 2-opt or relocate local search. Heap-based urgency ordering limits the number of candidates examined at each greedy insertion step.
