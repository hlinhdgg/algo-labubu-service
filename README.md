# IS115 Last-Mile Delivery Planning

Six policies decide which parcels each of 10 trucks carries on its next trip. **`fleet_aware` is recommended**, with a service rate of 95.99% against a best possible 96.46%.

The project needs Python 3.9 or newer and only the standard library. Run all commands from the project root. The code was run on Python 3.13.

## Run it

One policy on one day:

```bash
python3 -m simulator --policy solution.policies.fleet_aware --data data --day day_001 --output results/fleet_aware/day_001
python3 -m solution.performance_monitor --data data --day day_001 --log results/fleet_aware/day_001/log.txt
```

Everything (on Windows, use `python` and run the same commands for each policy and day):

```bash
for policy in baseline fleet_aware recursive_fleet local_search priority_nearest exhaustive_small; do
  for n in $(seq -w 1 20); do
    day="day_0$n"
    python3 -m simulator --policy solution.policies.$policy \
        --data data --day "$day" --output "results/$policy/$day"
    python3 -m solution.performance_monitor \
        --data data --day "$day" --log "results/$policy/$day/log.txt"
  done
done
```

Each run writes `log.txt` and `metrics.json` to `results/<policy>/<day>/`. All policies are deterministic, so re-running gives identical logs.

## Results over 20 days

| Policy | Service rate | Std dev | Worst day | Days 1-10 | Days 11-20 | Strict on-time | Delivered rate | On-time / delivered | Trips/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `fleet_aware` | **95.99%** | 0.48% | 95.13% | 95.96% | 96.01% | 94.63% | 96.35% | 98.22% | 32 |
| `recursive_fleet` | 93.87% | 2.23% | 87.92% | 94.07% | 93.66% | 91.41% | 96.17% | 95.05% | 31 |
| `priority_nearest` | 92.63% | 3.28% | 84.36% | 92.90% | 92.36% | 90.12% | 96.19% | 93.70% | 31 |
| `exhaustive_small` | 91.95% | 2.28% | 88.11% | 92.23% | 91.67% | 86.95% | 95.73% | 90.82% | 30 |
| `local_search` | 91.69% | 1.99% | 87.70% | 92.09% | 91.29% | 87.09% | 95.81% | 90.90% | 30 |
| `baseline` | 27.41% | 1.61% | 24.75% | 27.23% | 27.58% | 27.41% | 40.47% | 67.73% | 21 |

`fleet_aware` is just below the 96% acceptance target and 0.47 points below the 96.46% ceiling. Delivered rate and on-time / delivered are pooled over all parcels; the other columns are averages of daily values.

## Metric: service rate

The service rate is the average score over every parcel that arrived that day:

- delivered inside its window (boundaries included): **1**;
- delivered early or late: **1 − minutes outside the window ÷ window length**, and never below 0;
- never delivered: **0**.

Near-misses earn partial credit, and a policy cannot raise its score by skipping hard parcels. The best possible score is 96.46%: 15,306 of the 15,867 parcels can be delivered on time, and the other 561 arrive too late for any truck to reach them and return by 18:00.

`metrics.json` also records the strict on-time rate, delivered rate, on-time rate among delivered parcels, early and late counts, average lateness and number of trips.

## Policies

| Module | Approach |
|---|---|
| `solution.policies.baseline` | Greedy first-fit dispatch in arrival order with capacity, range, and cutoff checks |
| `solution.policies.fleet_aware` | Fleet-aware greedy insertion with last-chance prioritization, endgame waiting, detour-limited filler, and exhaustive ordering for small trips |
| `solution.policies.exhaustive_small` | Greedy insertion followed by exhaustive stop ordering for trips with at most 8 stops |
| `solution.policies.priority_nearest` | Binary-heap urgency ordering, greedy nearby insertion, and 2-opt local search |
| `solution.policies.local_search` | Greedy insertion, then exhaustive stop ordering for trips with at most 8 stops and bounded 2-opt for larger trips |
| `solution.policies.recursive_fleet` | Binary-heap urgency ordering, greedy insertion, recursive exhaustive ordering for small trips, and 2-opt for larger trips |

Shared code is in `solution/policies/helpers.py`, and the metric is in `solution/performance_monitor.py`. All policies respect capacity, range and the 18:00 return. Apart from `baseline`, trips are compared by service lost first and distance second, using the metric's own formula.

## How `fleet_aware` works

Each truck builds one trip with cheapest insertion, adding the parcels most at risk first:

1. **Last-chance parcels:** on time if sent now, but a direct trip one round later could not return by the cut-off.
2. **Must-take parcels:** no truck coming back could still deliver them on time.
3. **Other tight parcels:** at most 180 minutes to spare.
4. **Relaxed parcels as filler:** only if no stop misses its window and the parcel adds at most 20 km.

A parcel is never placed where the truck would arrive before its window opens. The truck then waits one round if it carries under 20 units and every parcel has over 60 minutes to spare. In the last 150 minutes, it also waits if the trip would still fit and every parcel would still be on time. Trips of up to 8 stops are then put in the exact best order.

Each rule came from a failure traced in the logs:

| Change | Problem it fixed | Days 1–10 | Days 11–20 |
|---|---|---|---|
| Trip cost uses service lost | A parcel 2 minutes late cost the same as one 3 hours late | 93.3% → 93.6% | 92.8% → 93.5% |
| 20 km filler limit | Long morning trips left trucks away for the next wave (day 20: 170 → 79 minutes, late parcels 99 → 4) | 93.6% → 95.69% | 93.5% → 95.58% |
| Last chance and end-of-day waiting | Trucks waited while parcels ran out of time (day 1, 16:00: three trucks waited and three parcels were lost) | 95.69% → 95.96% | 95.58% → 96.01% |

The last rules improved 18 of 20 days and worsened none. Last chance gives most of the gain alone (95.79% and 95.89%). End-of-day waiting alone is mixed (95.71% on days 1–10, 95.49% on days 11–20), and it isn't free: added to last chance, it gains 27 parcels and loses 4.

## Settings

| Setting | Value | What it does | Evidence |
|---|---|---|---|
| `ROUTE_DISTANCE_BUDGET_FRACTION` | 0.9 | Trips stop growing at 90% of the 320 km range | 0.8 won on days 1–10 but lost on days 11–20 |
| `TOP_K` | 50 | Most urgent parcels checked closely at each step | If none fit, all waiting parcels are checked |
| `WAIT_MIN_LOAD`, `WAIT_SLACK` | 20, 60 | The waiting rule | Load 15 is clearly worse (worst day 89.07%); load 25 is lower (95.91%, 95.92%) |
| `MAX_EXHAUSTIVE_STOPS` | 8 | Trip size for trying every stop order | 8! = 40,320 orders; 10 stops would be 3.6 million |
| `SLACK_THRESHOLD` | 180 | Minutes to spare for a parcel to be tight | 150 is slightly higher (96.02%, 96.03%) but its worst day is lower (94.83% vs 95.13%) |
| `FILLER_MAX_DETOUR` | 20 | Most km one filler parcel may add | 15–30 tie at 95.7% on days 1–10 (not fully explained); no limit gives 93.6% |
| `ENDGAME_MINUTES` | 150 | How long before the cut-off end-of-day waiting applies | Beats 120 on one day only, and 150–240 tie, so the exact value has little evidence |

## Ideas tried and dropped

Service rate unless stated; “÷ delivered” means on-time ÷ delivered, used earlier in the project.

| Idea | Result | Why dropped |
|---|---|---|
| Relocate moves after fleet-stage insertion (`relocate_local`) | 93.78%, worst day 86.53% | Outside our syllabus list, and below `fleet_aware` |
| Stop waiting if a last-chance parcel exists, without loading it | 95.69% → 95.63% (days 1–10) | The truck leaves without those parcels |
| Block re-ordering that causes early arrivals | Early 64 → 0, late 36 → 111, 95.69% → 95.62% (days 1–10) | A few minutes early costs little under this metric |
| Shorter distance limit (0.8) | `exhaustive_small` 91.0% → 91.5% on days 1–10, 90.6% → 90.2% on days 11–20 | Only looked better on the tuning days |
| Morning reserve truck (÷ delivered) | `fleet_aware` 95.5% → 94.4% on days 1–10, 95.4% → 94.5% on days 11–20 | One held truck cannot cover a wave needing about three |
| Booking parcels on returning trucks by capacity (strict on-time) | About 5 points below `fleet_aware` | Breaks up compact routes |
| Shorter trips late in the day (÷ delivered) | 87.6% → 87.8% on days 1–10, 86.5% → 86.4% on days 11–20 | Short trips cannot reach far stops |
| Must-take list including late parcels | 93.6% → 93.9% on days 1–10, 93.5% → 93.4% on days 11–20 | Did not hold on days 11–20 |
| Allowing slightly early arrivals (before the filler limit) | 93.5%, 93.1%, 93.0% vs 93.6% (days 1–10) | Lower |
| Shortlist of 100 instead of 50 | 93.6%, no gain | No benefit |

## Limits of these results

- `fleet_aware`'s settings were tuned on days 1–10 and checked on days 11–20. Those are **validation days, not unseen data**, because their scores influenced decisions.
- The results cover 20 days at one depot, so they may not carry over to other demand patterns.
- Older figures above were measured before later rules were added, so they show the effect of each change at the time.
