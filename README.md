# IS115 Project README

Last-mile delivery dispatch. The main metric is `service_rate`, the average service score over every parcel that arrived during the day:

- delivered inside its preferred window: `1`;
- delivered early or late: `1 - minutes outside the window / window length`, capped at `0`;
- never delivered: `0`.

This gives partial credit to near-misses and prevents a policy from improving its score by skipping difficult parcels. Approximately 3.5% of parcels are too late for any truck to reach on time, so the estimated unlimited-truck ceiling is about 96.5%.

The best possible service rate is 96.46%: 15,306 of the 15,867 parcels can be delivered on time, and the other 561 arrive too late for any truck to reach them and return by 18:00.

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
| `fleet_aware` | **95.99%** | 0.48% | 95.13% | 95.96% | 96.01% | 94.63% | 96.35% | 98.22% | 32 |
| `recursive_fleet` | 93.91% | 2.12% | 87.92% | 94.15% | 93.67% | 91.41% | 96.17% | 95.06% | 30.85 |
| `relocate_local` | 93.79% | 2.21% | 87.39% | 93.99% | 93.58% | 91.23% | 96.16% | 94.87% | 30.80 |
| `priority_nearest` | 92.61% | 3.10% | 84.80% | 92.85% | 92.38% | 89.72% | 96.17% | 93.30% | 30.95 |
| `exhaustive_small` | 91.95% | 2.28% | 88.11% | 92.23% | 91.67% | 86.95% | 95.73% | 90.82% | 30 |

`fleet_aware` is the best retained policy at 95.99%, just below the 96% acceptance target and 0.47 points below the 96.46% ceiling. Delivered rate and on-time / delivered are pooled over all parcels; the other columns are averages of daily values.

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

Bash:

```bash
for policy in baseline fleet_aware recursive_fleet relocate_local priority_nearest exhaustive_small; do
  for n in $(seq -w 1 20); do
    day="day_0$n"
    python3 -m simulator --policy solution.policies.$policy \
        --data data --day "$day" --output "results/$policy/$day"
    python3 -m solution.performance_monitor \
        --data data --day "$day" --log "results/$policy/$day/log.txt"
  done
done
```

Each run writes `log.txt` and `metrics.json` under `results/<policy>/<day>/`.

## Metric-aligned routing

The retained insertion and local-search policies compare routes using service loss first and distance second. Service loss at a stop is the same scaled penalty used by `service_rate`, so a small near-miss is preferred to a much larger miss when other constraints are equal.

Small routes are exhaustively ordered because 8 stops require 40,320 orders; larger routes use bounded 2-opt or relocate local search. Heap-based urgency ordering limits the number of candidates examined at each greedy insertion step.

## Notes on `fleet_aware` and `exhaustive_small`

Older figures below say which metric they used: "on-time ÷ delivered" and "strict on-time" were used before the final switch to the service rate.

### Trip cost matches the metric

Insertion, exhaustive ordering and 2-opt compare trips by (service lost, distance), where the service lost at a stop is min(1, minutes outside the window ÷ window length). An earlier version counted missed windows, so a parcel 2 minutes late cost the same as one 3 hours late. Service rate before → after that change:

| Policy | Days 1–10 | Days 11–20 | Days better (1–10 / 11–20) | Days 11–20 worst day |
|---|---|---|---|---|
| exhaustive_small | 91.0% → 92.2% | 90.6% → 91.7% | 9 / 8 | 84.7% → 88.1% |
| fleet_aware | 93.3% → 93.6% | 92.8% → 93.5% | 7 / 7 | 84.7% → 87.0% |

The `fleet_aware` figures are before the filler limit below. The trade-off is that strict on-time can fall (`exhaustive_small` 89.2% → 86.4% on days 11–20), because the greedy accepts several small near-misses instead of one large miss. This should be re-tested if the metric changes.

An extreme waiting rule shows why the metric counts all parcels: if `fleet_aware` leaves only when something is urgent (`WAIT_MIN_LOAD` above the capacity), 97.95% of delivered parcels are on time, but only 84.69% of parcels are delivered.

### Filler detour limit in `fleet_aware`

(Figures in this section are before the last-chance rule below.) `fleet_aware` adds relaxed parcels as filler once urgent ones are on board. A filler parcel may add at most `FILLER_MAX_DETOUR = 20` km to the trip; before this, filler turned morning trips into long tours, so trucks were still out when later parcels needed them.

| `fleet_aware` | Days 1–10 | Days 11–20 |
|---|---|---|
| Service rate | 93.6% → 95.7% | 93.5% → 95.6% |
| Worst day | 90.7% → 95.0% | 87.0% → 94.3% |
| Strict on-time | 91.2% → 94.8% | 91.4% → 93.8% |
| Late parcels | 384 → 36 | 351 → 93 |
| Early parcels | 1 → 64 | 19 → 80 |
| Undelivered parcels | 319 → 316 | 305 → 318 |
| Days better / worse | 8 / 1 | 8 / 1 |

The two worst days show why (trips leaving before 11:00; before → after):

| Day | Mean trip length | Stops per trip | Trucks home at 13:00 | Late parcels |
|---|---|---|---|---|
| 20 | 170 → 79 min | 12.8 → 4.6 | 6 → 10 | 99 → 4 |
| 19 | 187 → 90 min | 13.2 → 6.4 | 6 → 9 | 98 → 1 |

So those days were largely caused by the policy's own long trips, not only by the fleet size. On days 11–20 the gain is uneven: days 19 and 20 gain +7.6 and +8.7 and the other eight average about +0.6.

### Last-chance parcels and end-of-day waiting in `fleet_aware`

Trucks were waiting at the hub while parcels ran out of time. On day 1 at 16:00, trucks 6, 7 and 8 were all free. Cheapest insertion picked the nearest parcel, adding any of the three parcels on their last round would have broken the 90 km of time left, and `worth_waiting` looks only at parcels on the route, so all three trucks waited and those parcels were lost. Two rules were added:

- **Last chance first:** a parcel that is on time if sent now, but whose direct trip could not get back by the cut-off if it left one round later, goes on the trip before anything else.
- **End-of-day waiting:** in the last `ENDGAME_MINUTES = 150` before the cut-off, a truck with less than `WAIT_MIN_LOAD` units waits one round if the trip would still fit and every parcel on it would still be on time. This keeps it free for parcels that have not arrived yet.

| `fleet_aware` | Days 1–10 | Days 11–20 |
|---|---|---|
| Service rate | 95.69% → 95.96% | 95.58% → 96.01% |
| Worst day | 95.0% → 95.1% | 94.3% → 95.3% |
| Strict on-time | 94.8% → 95.1% | 93.8% → 94.2% |
| Late parcels | 36 → 35 | 93 → 93 |
| Early parcels | 64 → 64 | 80 → 80 |
| Undelivered parcels | 316 → 295 | 318 → 284 |
| Days better / worse | 10 / 0 | 8 / 0 |

Of the parcels that any truck could have reached on time, 73 were never delivered before these rules and 18 now. The last-chance rule gives most of the gain alone (95.79% and 95.89%). End-of-day waiting alone is mixed (95.69% → 95.71% on days 1–10, 95.58% → 95.49% on days 11–20), but it adds to the last-chance rule. It is not free: compared with last chance alone, it gains 27 parcels and loses 4.

### Effect of the waiting rule

Measured before the final metric, so these on-time figures are on-time ÷ delivered:

| Policy | On-time, no waiting | Days 11–20, no waiting | Delivered, no waiting | → On-time with waiting |
|---|---|---|---|---|
| exhaustive_small | 83.5% | 83.4% | 95.2% | 92.7% |
| fleet_aware (no exhaustive ordering, no early hold, tight ≤ 240) | 87.0% | 86.5% | 95.4% | 92.7% (94.3% with early hold, 95.5% with tight ≤ 180) |

Parcels arrive in waves. Without waiting, a truck leaves as soon as it is free, so the whole fleet leaves in the first hour and no truck is free for the next parcels. In an earlier greedy insertion policy, every one of the 683 parcels arriving in the 09:00 hour missed its window without waiting, and only 75 missed with it.

### Tuning constants

Settings were tuned on days 1–10 and then checked on days 11–20. Days 11–20 are **validation days, not unseen test days**: their scores influenced decisions and may be slightly optimistic.

The settings were re-checked on the final `fleet_aware` (days 1–10 / days 11–20 / worst day; current 95.96% / 96.01% / 95.13%):

| Setting | Days 1–10 | Days 11–20 | Worst day |
|---|---|---|---|
| `SLACK_THRESHOLD` 150 | 96.02% | 96.03% | 94.83% |
| `SLACK_THRESHOLD` 210 | 95.91% | 95.99% | 94.85% |
| `WAIT_MIN_LOAD` 15 | 95.87% | 94.88% | 89.07% |
| `WAIT_MIN_LOAD` 25 | 95.91% | 95.92% | 94.65% |

`SLACK_THRESHOLD` 150 is slightly higher on average but has a lower worst day, so 180 is kept.

- `ROUTE_DISTANCE_BUDGET_FRACTION = 0.9` — trips stop growing at 90% of the 320 km range. A limit of 0.8 looked better on days 1–10 but lost on days 11–20 (`exhaustive_small` 90.6% → 90.2% on the service rate), so 0.9 was kept.
- `TOP_K = 50` — how many of the most urgent parcels are fully checked at each insertion step. If none of them fit, every waiting parcel is checked before the route is closed.
- `WAIT_MIN_LOAD = 20`, `WAIT_SLACK = 60` — the waiting rule.
- `MAX_EXHAUSTIVE_STOPS = 8` — 8! = 40,320 orders; 10 stops would be 3.6 million per trip.
- `SLACK_THRESHOLD = 180` — a parcel is "tight" if it has at most 180 minutes to spare.
- `ENDGAME_MINUTES = 150` — how long before the cut-off end-of-day waiting applies. With the last-chance rule, days 1–10: 95.79% with no end-of-day waiting, 95.80% at 90, 95.90% at 120, 95.96% at 150 and 180. On days 11–20, 120, 150, 180 and 240 give the same mean, and 150 beats 120 on one day only, so the exact value has little evidence behind it. On this data it means from 15:30.
- `FILLER_MAX_DETOUR = 20` — how many km one filler parcel may add to a trip. Days 1–10, service rate, before the last-chance rule: 89.9% at 0, 94.3% at 5, 94.7% at 10, 95.7% at 15, 20, 25 and 30, 95.0% at 40, 94.3% at 60, 93.6% with no limit. Why 15–30 give identical scores is not fully explained.

### Ideas tried and dropped

Tested on days 1–10 and not in `solution/`, except where noted. Each says which metric it used:

- **Never arrive early.** Dropped for `exhaustive_small` (on-time ÷ delivered: 92.5% → 92.7% on days 1–10, 92.8% → 92.5% on days 11–20), but kept for `fleet_aware`.
- **Booking parcels onto returning trucks by capacity** (strict on-time): about 5 points below `fleet_aware`. Forcing a large group onto a trip first breaks up compact routes.
- **Shorter trips during a rush** (on-time ÷ delivered): the best setting for `fleet_aware` gave +0.2 on days 1–10 and +0.4 on days 11–20, but the validation gain came from a single day.
- **Never wait when a big pile is waiting** (on-time ÷ delivered): no change for `exhaustive_small`, 0.7–3.0 points worse for `fleet_aware`.
- **Shorter trips late in the day** (on-time ÷ delivered): 87.8% vs 87.6% for `fleet_aware` on days 1–10, but 86.4% vs 86.5% on days 11–20.
- **Reserve truck in the morning** (on-time ÷ delivered): `fleet_aware` 95.5% → 94.4% on days 1–10 and 95.4% → 94.5% on days 11–20. One held truck does not close the gap when a wave needs about three truckloads.
- **`fleet_aware`'s must-take list including late parcels that can still earn credit** (service rate, before the filler limit): 93.6% → 93.9% on days 1–10, but 93.5% → 93.4% on days 11–20.
- **`fleet_aware`'s filler rule using service lost** (service rate, days 1–10): logs identical to the current rule at every setting, so it would add code with no effect.
- **Allowing slightly early arrivals in `fleet_aware`** (service rate, days 1–10, before the filler limit): 93.5%, 93.1% and 93.0% vs 93.6%. **Shortlist of 100 instead of 50**: no gain (93.6%).
- **Trimming long trips in the morning** (on-time ÷ delivered, days 1–10): `fleet_aware` 95.5% → 64.0–94.6%, `exhaustive_small` 92.5% → 74.6–91.1%. The filler limit later achieved this aim while the trip is being built.
- **Only stopping the truck from waiting when a last-chance parcel exists** (service rate, days 1–10): 95.69% → 95.63%. The truck leaves, but the last-chance parcels are still not on it.
- **Stopping `best_stop_order` from creating early arrivals** (service rate, days 1–10): early parcels 64 → 0, but late parcels 36 → 111 and 95.69% → 95.62%. Arriving a few minutes early costs little under the service rate, so these re-orders are kept.
