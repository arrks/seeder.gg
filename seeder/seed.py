import re


def extract_series_name(name: str) -> str:
    m = re.match(r"^(.*?)[\s\-#]+\d+\W*$", name)
    return m.group(1).strip() if m else name


def compute_scores(
    player_placements: dict[str, list[int]], decay: float = 0.7
) -> dict[str, float]:
    return {
        tag: sum((1 / p) * (decay**i) for i, p in enumerate(placements))
        for tag, placements in player_placements.items()
    }


def next_power_of_two(n: int) -> int:
    return 1 << (n - 1).bit_length()


def bracket_round1_opponent(seed: int, bracket_size: int) -> int:
    return bracket_size + 1 - seed


_NO_REMATCH = (10**9, 0)

# Largest contiguous seat block we'll cyclically rotate to break a rematch. This is a
# performance bound, not a tuning knob — score deviation decides which move actually wins.
_MAX_ROTATION_BLOCK = 5


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
            if pair in matchups and pair not in irreducible:
                pairs.append((freshness_key(pair), seats[0], seats[1]))
        if not pairs:
            break
        pairs.sort(reverse=True)
        target_key, a, b = pairs[0]
        target_pair = frozenset({ordered[a], ordered[b]})
        gap = -target_key[0]
        log(
            f"conflict: seed {a + 1} ({ordered[a]}) vs seed {b + 1} ({ordered[b]}) "
            f"— played in R1 before (gap={gap})"
        )

        # Try a move set — any-distance pairwise swaps plus cyclic rotations of short
        # contiguous blocks — and pick the least-disruptive one that strictly reduces the
        # freshest conflict. Cost: avoid leaving a fresh rematch among touched seats, then
        # minimise total score deviation from the ideal profile, then total seat movement.
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

        def apply_rot(lo: int, hi: int, direction: int) -> None:
            seg = ordered[lo : hi + 1]
            ordered[lo : hi + 1] = (
                [seg[-1]] + seg[:-1] if direction == 1 else seg[1:] + [seg[0]]
            )

        # best = (cost, kind, params); params re-apply the move on the unmutated `ordered`.
        best: tuple[tuple[int, float, int, tuple[int, int]], str, tuple] | None = None
        conflict_seats = [s for s in (a, b) if s >= locked]

        def offer(cost, kind: str, params: tuple) -> None:
            nonlocal best
            if cost is not None and (best is None or cost < best[0]):
                best = (cost, kind, params)

        # Pairwise swaps: relocate a movable side of the conflict anywhere.
        for anchor in conflict_seats:
            for k in range(locked, entrant_count):
                if k == a or k == b:
                    continue
                apply_swap(anchor, k)
                cost = evaluate((anchor, k))
                apply_swap(anchor, k)
                offer(cost, "swap", (anchor, k))

        # Cyclic rotations of a short contiguous block that includes a conflict seat —
        # lets a chain of near-equal players each shift one spot instead of one player
        # absorbing the whole move.
        for size in range(3, min(_MAX_ROTATION_BLOCK, entrant_count - locked) + 1):
            for lo in range(locked, entrant_count - size + 1):
                hi = lo + size - 1
                if not any(lo <= cs <= hi for cs in conflict_seats):
                    continue
                for direction in (1, -1):
                    apply_rot(lo, hi, direction)
                    cost = evaluate(tuple(range(lo, hi + 1)))
                    apply_rot(lo, hi, -direction)
                    offer(cost, "rot", (lo, hi, direction))

        if best is None:
            # This pair can't be improved without making things worse; leave it and
            # move on to the next-freshest pair.
            irreducible.add(target_pair)
            x, y = tuple(target_pair)
            log(f"  → could not break without a fresher conflict; left {x} vs {y}")
            continue

        (_, score_dev, _, _), kind, params = best
        if kind == "swap":
            i, k = params
            members = f"{ordered[i]} (seed {i + 1}) ↔ {ordered[k]} (seed {k + 1})"
            apply_swap(i, k)
        else:
            lo, hi, direction = params
            arrow = "↓" if direction == 1 else "↑"
            members = f"seeds {lo + 1}-{hi + 1} ({arrow})"
            apply_rot(lo, hi, direction)
        log(f"  → {members}; score deviation {score_dev:.3f}")

    return ordered


def build_seed_list(
    scores: dict[str, float],
    player_placements: dict[str, list[int]],
    matchups: dict[frozenset[str], list[int]],
    player_attendance: dict[str, list[int]],
    entrant_count: int,
    trace: list[str] | None = None,
) -> list[dict]:
    ordered = sorted(scores, key=lambda t: scores[t], reverse=True)
    bracket_size = next_power_of_two(entrant_count)

    ordered = _resolve_conflicts(
        ordered, scores, matchups, player_attendance, bracket_size, entrant_count,
        locked=2, trace=trace,
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
        result.append(
            {
                "seed": seed,
                "tag": tag,
                "score": scores[tag],
                "placements": player_placements.get(tag, []),
                "rematches": rematches,
            }
        )
    return result
