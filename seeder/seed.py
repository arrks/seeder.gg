import re
from itertools import permutations


def extract_series_name(name: str) -> str:
    m = re.match(r"^(.*?)[\s\-#]+\d+\s*$", name)
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


def _count_conflicts(
    ordered: list[str],
    group_start: int,
    group_end: int,
    matchups: set[frozenset[str]],
    bracket_size: int,
) -> int:
    seen: set[frozenset[str]] = set()
    for seed in range(group_start, group_end + 1):
        opp = bracket_round1_opponent(seed, bracket_size)
        if group_start <= opp <= group_end:
            pair = frozenset({ordered[seed - 1], ordered[opp - 1]})
            if pair in matchups:
                seen.add(pair)
    return len(seen)


def optimize_group(
    ordered: list[str],
    group_start: int,
    group_end: int,
    matchups: set[frozenset[str]],
    bracket_size: int,
) -> list[str]:
    group = ordered[group_start - 1 : group_end]
    best = group[:]
    best_count = _count_conflicts(ordered, group_start, group_end, matchups, bracket_size)
    if best_count == 0:
        return ordered

    for perm in permutations(group):
        candidate = ordered[: group_start - 1] + list(perm) + ordered[group_end:]
        count = _count_conflicts(candidate, group_start, group_end, matchups, bracket_size)
        if count < best_count:
            best_count = count
            best = list(perm)
            if best_count == 0:
                break

    return ordered[: group_start - 1] + best + ordered[group_end:]


def build_seed_list(
    scores: dict[str, float],
    player_placements: dict[str, list[int]],
    matchups: set[frozenset[str]],
    entrant_count: int,
) -> list[dict]:
    ordered = sorted(scores, key=lambda t: scores[t], reverse=True)
    bracket_size = next_power_of_two(entrant_count)

    # Seeds 1-4 are fixed; optimize groups of 4 from seed 5 onward
    g = 5
    while g <= entrant_count:
        end = min(g + 3, entrant_count)
        ordered = optimize_group(ordered, g, end, matchups, bracket_size)
        g += 4

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
