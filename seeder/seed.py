import re


def extract_series_name(name: str) -> str:
    m = re.match(r"^(.*?)[\s\-#]+\d+\W*$", name)
    return m.group(1).strip() if m else name


def build_recent_matchups(
    all_standings: list[list[dict]], top_n: int = 32
) -> set[frozenset[str]]:
    matchups: set[frozenset[str]] = set()
    for standings in all_standings:
        top = sorted(standings, key=lambda x: x["placement"])[:top_n]
        tags = []
        for entry in top:
            try:
                tags.append(entry["entrant"]["participants"][0]["gamerTag"])
            except (KeyError, IndexError):
                continue
        for i in range(len(tags)):
            for j in range(i + 1, len(tags)):
                matchups.add(frozenset({tags[i], tags[j]}))
    return matchups


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


def _resolve_conflicts(
    ordered: list[str],
    matchups: set[frozenset[str]],
    bracket_size: int,
    entrant_count: int,
    locked: int = 2,
) -> list[str]:
    ordered = ordered[:]
    for _ in range(entrant_count * 2):
        # Find the first round-1 conflict among seeds locked+1 and beyond
        conflict = None
        for i in range(locked, entrant_count):
            j = bracket_round1_opponent(i + 1, bracket_size) - 1
            if locked <= j < entrant_count and frozenset({ordered[i], ordered[j]}) in matchups:
                conflict = (min(i, j), max(i, j))
                break

        if conflict is None:
            break

        a, b = conflict  # a = higher seed (lower index), b = lower seed
        # Try swapping b with other positions, nearest first to preserve score order
        candidates = sorted(
            [k for k in range(locked, entrant_count) if k != a and k != b],
            key=lambda k: abs(k - b),
        )

        swapped = False
        for k in candidates:
            ordered[b], ordered[k] = ordered[k], ordered[b]
            # Conflict at a resolved?
            a_ok = frozenset({ordered[a], ordered[b]}) not in matchups
            # New conflict created at k?
            k_opp_i = bracket_round1_opponent(k + 1, bracket_size) - 1
            k_ok = not (
                locked <= k_opp_i < entrant_count
                and frozenset({ordered[k], ordered[k_opp_i]}) in matchups
            )
            if a_ok and k_ok:
                swapped = True
                break
            ordered[b], ordered[k] = ordered[k], ordered[b]

        if not swapped:
            # Can't resolve this conflict without creating another — skip and continue
            # Move past this pair so we don't get stuck in an infinite loop
            break

    return ordered


def build_seed_list(
    scores: dict[str, float],
    player_placements: dict[str, list[int]],
    matchups: set[frozenset[str]],
    entrant_count: int,
) -> list[dict]:
    ordered = sorted(scores, key=lambda t: scores[t], reverse=True)
    bracket_size = next_power_of_two(entrant_count)

    ordered = _resolve_conflicts(ordered, matchups, bracket_size, entrant_count, locked=2)

    result = []
    for i, tag in enumerate(ordered):
        seed = i + 1
        opp_seed = bracket_round1_opponent(seed, bracket_size)
        conflicts: list[str] = []
        if 1 <= opp_seed <= entrant_count:
            opp_tag = ordered[opp_seed - 1]
            if frozenset({tag, opp_tag}) in matchups:
                conflicts = [opp_tag]
        result.append(
            {
                "seed": seed,
                "tag": tag,
                "score": scores[tag],
                "placements": player_placements.get(tag, []),
                "conflicts": conflicts,
            }
        )
    return result
