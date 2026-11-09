# IS115 Last-Mile Delivery Planning

We built dispatch policies for the delivery simulation and compared them using the **service rate** (defined below). **Recommended policy: `fleet_aware`**, with a service rate of 95.99% against a best possible 96.46%. Tested on Python 3.13.

## How to run

All commands are run from the project root. On Windows, use `python` instead of `python3`.

One policy, one day (simulator, then performance monitor):

```bash
python3 -m simulator --policy solution.policies.fleet_aware --data data --day day_001 --output results/fleet_aware/day_001
python3 -m solution.performance_monitor --data data --day day_001 --log results/fleet_aware/day_001/log.txt
```

All policies, all 20 days:

```bash
for policy in baseline fleet_aware recursive_fleet exhaustive_small bfs_cluster location_grouping local_search priority_nearest; do
  for n in $(seq -w 1 20); do
    day="day_0$n"
    python3 -m simulator --policy solution.policies.$policy \
        --data data --day "$day" --output "results/$policy/$day"
    python3 -m solution.performance_monitor \
        --data data --day "$day" --log "results/$policy/$day/log.txt"
  done
done
```

On Windows, run the two commands above once for each policy and day. All policies are deterministic, so rerunning gives identical results. `local_search` and `priority_nearest` were explored earlier and are not in the final comparison; they are in the loop so their results in `results/` can be reproduced.

## Metric: service rate

Each parcel gets a score, and the service rate is the average score over all parcels that arrived that day:

- delivered inside its preferred window: **1**
- delivered early or late: **1 − (minutes outside the window ÷ window length)**, never below 0
- never delivered: **0**

Near-misses still earn partial credit, and a policy cannot raise its score by skipping hard parcels. The best possible score is 96.46%, because 561 of the 15,867 parcels arrive too late for any truck to deliver them and return by 18:00.

## Policies

| Policy | How it works | Data structures |
|---|---|---|
| `fleet_aware` | Builds each trip by cheapest insertion, adding the most urgent parcels first, then finds the best stop order | Heap |
| `recursive_fleet` | Same parcel groups as `fleet_aware`, but the stop order comes from a recursive search (2-opt for more than 8 stops) | Heap, recursion |
| `exhaustive_small` | Cheapest insertion over all waiting parcels, then tries every stop order for trips with at most 8 stops | Heap |
| `bfs_cluster` | Finds parcels near the most urgent one with a breadth-first search, then builds the trip from only those parcels | Graph, queue |
| `location_grouping` | Groups parcels by location and visits locations in order of earliest deadline | Hash map, heap |

The heap picks the 50 most urgent waiting parcels to check first at each insertion step. Shared code is in `solution/policies/helpers.py`.

### How `fleet_aware` works

Each truck builds one trip with cheapest insertion, adding parcels in this order:

1. **Last-chance parcels:** can be on time if sent now, but not if the truck waits one more planning round.
2. **Must-take parcels:** no other truck returning in time could deliver them on time.
3. **Tight parcels:** at most 180 minutes of slack (time left before the window closes).
4. **Relaxed parcels, as extras only:** added if no stop misses its window and the parcel adds at most 20 km.

A parcel is never placed where the truck would arrive before its window opens. A truck carrying less than 20 units waits one round if every parcel has more than 60 minutes of slack. In the last 150 minutes before 18:00, a small trip also waits if all its parcels would still be on time. Trips with at most 8 stops are then put in the exact best order by trying every order.

## Results over 20 days

| Policy | Service rate | Std dev | Worst day | Strict on-time | Delivered rate |
|---|---:|---:|---:|---:|---:|
| `fleet_aware` | **95.99%** | 0.48% | 95.13% | 94.63% | 96.35% |
| `recursive_fleet` | 93.87% | 2.23% | 87.92% | 91.41% | 96.17% |
| `bfs_cluster` | 92.11% | 2.78% | 87.05% | 91.18% | 96.08% |
| `exhaustive_small` | 91.95% | 2.28% | 88.11% | 86.95% | 95.73% |
| `location_grouping` | 83.97% | 3.67% | 77.07% | 75.64% | 93.74% |
| `baseline` | 27.41% | 1.61% | 24.75% | 27.41% | 40.47% |

Service rate, std dev and worst day are calculated from the 20 daily values. Strict on-time counts only parcels delivered inside their window.

## Key settings

| Setting | Value | Meaning |
|---|---|---|
| `ROUTE_DISTANCE_BUDGET_FRACTION` | 0.9 | Trips stop growing at 90% of the 320 km range |
| `TOP_K` | 50 | Number of urgent parcels checked first at each insertion step |
| `MAX_EXHAUSTIVE_STOPS` | 8 | Largest trip where every stop order is tried (8! = 40,320 orders) |
| `WAIT_MIN_LOAD`, `WAIT_SLACK` | 20, 60 | A truck with less than 20 units waits if every parcel has over 60 minutes of slack |
| `SLACK_THRESHOLD` | 180 | Minutes of slack at or below which a parcel counts as tight |
| `FILLER_MAX_DETOUR` | 20 | Most km one extra (relaxed) parcel may add to a trip |
| `ENDGAME_MINUTES` | 150 | How long before 18:00 the end-of-day waiting rule applies |
| `K_NEIGHBOURS`, `MAX_CLUSTER_PARCELS` | 4, 40 | `bfs_cluster` only: neighbours per location and parcels per cluster |

## Limitations

- The `fleet_aware` settings were tuned on days 1-10 and checked on days 11-20. Because those scores influenced our choices, days 11-20 are validation days, not unseen data.
- `bfs_cluster` and `location_grouping` were added later and have not been tuned.
- The results cover 20 days at one depot, so they may not carry over to other demand patterns.
