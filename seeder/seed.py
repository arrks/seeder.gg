import re
from math import log2


def extract_series_name(name: str) -> str:
    m = re.match(r"^(.*?)[\s\-#]+\d+\W*$", name)
    return m.group(1).strip() if m else name


def compute_scores(
    player_history: dict[str, list[tuple[int, int, int]]],
    decay: float = 0.7,
) -> dict[str, float]:
    """Recency-weighted log2(attendance/placement), floored at 0.

    Each history entry is (placement, attendance, ts). Bigger fields are
    worth more; mid-pack finishes at large events don't drag a player down
    below zero. Entries are decayed by index after sorting most-recent-first.
    """
    scores: dict[str, float] = {}
    for tag, history in player_history.items():
        ordered = sorted(history, key=lambda x: x[2], reverse=True)
        total = 0.0
        for i, (p, n, _) in enumerate(ordered):
            if not p or not n or p <= 0 or n <= 0:
                continue
            total += max(0.0, log2(n / p)) * (decay ** i)
        scores[tag] = total
    return scores


def next_power_of_two(n: int) -> int:
    return 1 << (n - 1).bit_length()


def bracket_round1_opponent(seed: int, bracket_size: int) -> int:
    return bracket_size + 1 - seed


_NO_REMATCH = (10**9, 0)

# A rematch where both players have attended this many or more other tournaments
# since last meeting is treated as no longer competitively fresh — neither player
# walked in last week expecting to face the other, so forcing a swap to break it
# only costs score deviation for marginal benefit.
_STALE_GAP = 6


def pair_freshness(
    pair: frozenset[str],
    matchups: dict[frozenset[str], list[int]],
    player_attendance: dict[str, list[int]],
) -> tuple[int, int]:
    """Returns (min_gap, last_shared_ts). Lower = fresher.

    min_gap = the fewest past tournaments either player has attended *since* their
    last shared appearance. 0 means at least one player's most recent appearance
    was with this opponent.
    """
    dates = matchups.get(pair)
    if not dates:
        return _NO_REMATCH
    last_shared = max(dates)
    a, b = tuple(pair)
    gap_a = sum(1 for t in player_attendance.get(a, []) if t > last_shared)
    gap_b = sum(1 for t in player_attendance.get(b, []) if t > last_shared)
    return (min(gap_a, gap_b), last_shared)


def _resolve_conflicts(
    ordered: list[str],
    scores: dict[str, float],
    matchups: dict[frozenset[str], list[int]],
    player_attendance: dict[str, list[int]],
    bracket_size: int,
    entrant_count: int,
    locked: int = 2,
    trace: list[str] | None = None,
) -> list[str]:
    def log(msg: str) -> None:
        if trace is not None:
            trace.append(msg)

    def freshness_key(pair: frozenset[str]) -> tuple[int, int]:
        # For sorting: fresher should sort "larger" (handled first).
        # Lower min_gap = fresher → negate. Higher last_shared = fresher within same gap.
        min_gap, last_shared = pair_freshness(pair, matchups, player_attendance)
        return (-min_gap, last_shared)

    ordered = ordered[:]
    # Natural (score-based) seed index for each player, plus the ideal score for each
    # seat. Disruption is measured in *score* terms — how far a player's score is from
    # the score that "belongs" in the seat they land in — so swapping near-tied players
    # (or no-history 0.0 players) is nearly free, while crossing a real skill gap is not.
    # Seed-index distance is kept only as a deterministic tiebreak for exact score ties.
    natural = {tag: i for i, tag in enumerate(ordered)}
    ideal_at_seat = [scores[t] for t in ordered]
    sentinel = (-_NO_REMATCH[0], _NO_REMATCH[1])
    irreducible: set[frozenset[str]] = set()
    # Pairs whose last R1 meeting is far enough back that we no longer treat them
    # as a competitive freshness concern. Computed once: freshness depends only on
    # matchups + attendance, both immutable across passes.
    stale_pairs: set[frozenset[str]] = {
        pair for pair in matchups
        if -pair_freshness(pair, matchups, player_attendance)[0] >= _STALE_GAP
    }
    if trace is not None and stale_pairs:
        initial_stale: list[tuple[int, str, str]] = []
        seen_stale_seats: set[tuple[int, int]] = set()
        for i in range(locked, entrant_count):
            j = bracket_round1_opponent(i + 1, bracket_size) - 1
            if not (0 <= j < entrant_count):
                continue
            seats = (min(i, j), max(i, j))
            if seats in seen_stale_seats:
                continue
            seen_stale_seats.add(seats)
            pair = frozenset({ordered[i], ordered[j]})
            if pair in stale_pairs:
                gap = -pair_freshness(pair, matchups, player_attendance)[0]
                initial_stale.append((gap, ordered[i], ordered[j]))
        if initial_stale:
            log(
                f"ignoring {len(initial_stale)} stale R1 rematch(es) at initial "
                f"seeding (gap >= {_STALE_GAP}):"
            )
            for g, x, y in sorted(initial_stale, reverse=True):
                log(f"    {x} vs {y} (gap={g})")
    for _ in range(entrant_count * 4):
        # A movable seat (>= locked) facing a rematch counts as a conflict even when its
        # R1 opponent is a locked top seed — we just can't move the locked side to fix it.
        pairs: list[tuple[tuple[int, int], int, int]] = []
        seen_seats: set[tuple[int, int]] = set()
        for i in range(locked, entrant_count):
            j = bracket_round1_opponent(i + 1, bracket_size) - 1
            if not (0 <= j < entrant_count):
                continue
            seats = (min(i, j), max(i, j))
            if seats in seen_seats:
                continue
            seen_seats.add(seats)
            pair = frozenset({ordered[i], ordered[j]})
            if pair in matchups and pair not in irreducible and pair not in stale_pairs:
                pairs.append((freshness_key(pair), seats[0], seats[1]))
        if not pairs:
            break
        pairs.sort(reverse=True)
        target_key, a, b = pairs[0]
        target_pair = frozenset({ordered[a], ordered[b]})
        gap = -target_key[0]
        log(
            f"pass: {len(pairs)} conflict(s) remaining; "
            f"freshest = seed {a + 1} ({ordered[a]}) vs seed {b + 1} ({ordered[b]}) "
            f"(gap={gap})"
        )

        # Try every pairwise swap involving a movable side of the conflict and pick
        # the least-disruptive one that strictly reduces the freshest conflict. Cost:
        # avoid leaving a fresh rematch among touched seats, then minimise total
        # score deviation from the ideal profile, then total seat movement.
        def evaluate(touched: tuple[int, ...]) -> tuple[int, float, int, tuple[int, int]] | None:
            # `ordered` is already mutated. Only touched seats changed occupants, so only
            # their R1 pairs can have changed — checking those covers target breakage too.
            worst_after = sentinel
            for p in touched:
                q = bracket_round1_opponent(p + 1, bracket_size) - 1
                if 0 <= q < entrant_count:
                    worst_after = max(worst_after, freshness_key(frozenset({ordered[p], ordered[q]})))
            if not (worst_after < target_key):
                return None
            creates = 0 if worst_after == sentinel else 1
            score_dev = round(
                sum(abs(scores[ordered[s]] - ideal_at_seat[s]) for s in range(entrant_count)), 6
            )
            index_disp = sum(abs(s - natural[ordered[s]]) for s in range(entrant_count))
            return (creates, score_dev, index_disp, worst_after)

        def apply_swap(i: int, k: int) -> None:
            ordered[i], ordered[k] = ordered[k], ordered[i]

        # best = (cost, (i, k)); params re-apply the swap on the unmutated `ordered`.
        best: tuple[tuple[int, float, int, tuple[int, int]], tuple[int, int]] | None = None
        conflict_seats = [s for s in (a, b) if s >= locked]
        # Trace-only bookkeeping: collect every viable candidate so we can report
        # the runners-up alongside the winner.
        candidates: list[tuple[tuple[int, float, int, tuple[int, int]], tuple[int, int]]] = []
        swap_tried = swap_viable = 0

        def describe(params: tuple[int, int]) -> str:
            i, k = params
            return (
                f"swap {ordered[i]} (seed {i + 1}) ↔ "
                f"{ordered[k]} (seed {k + 1})"
            )

        def offer(cost, params: tuple[int, int]) -> None:
            nonlocal best
            if cost is None:
                return
            if best is None or cost < best[0]:
                best = (cost, params)
            if trace is not None:
                candidates.append((cost, params))

        # Pairwise swaps: relocate a movable side of the conflict anywhere.
        for anchor in conflict_seats:
            for k in range(locked, entrant_count):
                if k == a or k == b:
                    continue
                swap_tried += 1
                apply_swap(anchor, k)
                cost = evaluate((anchor, k))
                apply_swap(anchor, k)
                if cost is not None:
                    swap_viable += 1
                offer(cost, (anchor, k))

        if trace is not None:
            log(f"  candidates: {swap_viable}/{swap_tried} swaps viable")
            if candidates:
                candidates.sort(key=lambda c: c[0])
                shown = min(3, len(candidates))
                log(f"  top {shown} by cost (creates_new, score_dev, idx_disp):")
                for cost, params in candidates[:shown]:
                    creates, sd, idx, _ = cost
                    log(f"    [{creates}, {sd:.3f}, {idx}] {describe(params)}")

        if best is None:
            # This pair can't be improved without making things worse; leave it and
            # move on to the next-freshest pair.
            irreducible.add(target_pair)
            x, y = tuple(target_pair)
            log(
                f"  → irreducible: no candidate strictly improves over the target "
                f"freshness; left {x} vs {y} in place"
            )
            continue

        (creates, score_dev, idx_disp, _), params = best
        move_desc = describe(params)
        apply_swap(*params)
        log(
            f"  → chose {move_desc} "
            f"(creates_new={creates}, score_dev={score_dev:.3f}, idx_disp={idx_disp})"
        )

    return ordered


def build_seed_list(
    scores: dict[str, float],
    player_history: dict[str, list[tuple[int, int, int]]],
    matchups: dict[frozenset[str], list[int]],
    player_attendance: dict[str, list[int]],
    entrant_count: int,
    trace: list[str] | None = None,
) -> list[dict]:
    ordered = sorted(scores, key=lambda t: scores[t], reverse=True)
    bracket_size = next_power_of_two(entrant_count)

    ordered = _resolve_conflicts(
        ordered, scores, matchups, player_attendance, bracket_size, entrant_count,
        locked=3, trace=trace,
    )

    result = []
    for i, tag in enumerate(ordered):
        seed = i + 1
        opp_seed = bracket_round1_opponent(seed, bracket_size)
        rematches: list[dict] = []
        if 1 <= opp_seed <= entrant_count:
            opp_tag = ordered[opp_seed - 1]
            pair = frozenset({tag, opp_tag})
            if pair in matchups:
                min_gap, last_shared = pair_freshness(pair, matchups, player_attendance)
                last_for = [
                    p
                    for p in (tag, opp_tag)
                    if sum(1 for t in player_attendance.get(p, []) if t > last_shared) == 0
                ]
                rematches.append(
                    {
                        "opponent": opp_tag,
                        "dates": sorted(matchups[pair], reverse=True),
                        "min_gap": min_gap,
                        "last_shared": last_shared,
                        "last_for": last_for,
                    }
                )
        history = sorted(player_history.get(tag, []), key=lambda x: x[2], reverse=True)
        placements = [p for p, _, _ in history]
        result.append(
            {
                "seed": seed,
                "tag": tag,
                "score": scores[tag],
                "placements": placements,
                "rematches": rematches,
            }
        )
    return result
