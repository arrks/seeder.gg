import os
import re
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from seeder import seed as seed_module
from seeder.api import StartGGClient


def _load_dotenv() -> None:
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def parse_start_gg_url(url: str) -> tuple[str, str | None]:
    m = re.match(
        r"https?://(?:www\.)?start\.gg/tournament/([^/]+)(?:/event/([^/?#]+))?",
        url.strip(),
    )
    if not m:
        print(f"Error: not a valid start.gg tournament URL: {url}", file=sys.stderr)
        sys.exit(1)
    return m.group(1), m.group(2)


def prompt_pick(console: Console, items: list[dict], fmt=None) -> dict:
    for i, item in enumerate(items, 1):
        label = fmt(item) if fmt else item["name"]
        console.print(f"  [bold]{i}.[/bold] {label}")
    while True:
        raw = Prompt.ask("Pick number")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(items):
                return items[idx]
        except ValueError:
            pass
        console.print("[red]Invalid choice, try again.[/red]")


def _format_ago(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    days = seconds // 86400
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days} days ago"
    if days < 365:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


def _fmt_tournament(t: dict) -> str:
    date = datetime.fromtimestamp(t["startAt"]).strftime("%b %d") if t.get("startAt") else ""
    return f"{t['name']}  [dim]{date}[/dim]"


def main() -> None:
    try:
        _main()
    except KeyboardInterrupt:
        print("\nAborting.")


def _main() -> None:
    _load_dotenv()
    console = Console()
    from importlib.metadata import version
    v = version("seeder-gg")
    console.print(f"[bold magenta]seeder.gg[/bold magenta] [dim]v{v}[/dim]\n")

    token = os.environ.get("STARTGG_TOKEN") or Prompt.ask("API token", password=True)
    client = StartGGClient(token)

    positional = [a for a in sys.argv[1:] if a not in ("-v", "--verbose")]
    verbose = any(a in ("-v", "--verbose") for a in sys.argv[1:])
    url = (positional[0] if positional else None) or os.environ.get("STARTGG_URL")

    if not url:
        # Use the token owner's tournaments
        with console.status("Fetching your tournaments..."):
            user = client.get_current_user_with_tournaments(per_page=20)

        display_name = (
            user.get("name")
            or (user.get("player") or {}).get("gamerTag")
            or user.get("slug")
            or "unknown"
        )
        candidates = (user.get("tournaments") or {}).get("nodes") or []
        console.print(f"Welcome, [cyan]{display_name}[/cyan]!\n")

        if not candidates:
            console.print("[red]No recent tournaments found. Try passing a URL instead.[/red]")
            sys.exit(1)

        if len(candidates) == 1:
            tournament = candidates[0]
        else:
            console.print("\nRecent tournaments:")
            tournament = prompt_pick(console, candidates[:6], fmt=_fmt_tournament)

        historical = [t for t in candidates if t["id"] != tournament["id"]]
        series_name = seed_module.extract_series_name(tournament["name"])
        events = tournament.get("events") or []


    else:
        # URL-based flow
        if not url:
            url = Prompt.ask("[bold]Tournament URL[/bold]")
        tournament_slug, event_slug = parse_start_gg_url(url)

        with console.status("Fetching tournament..."):
            tournament = client.get_tournament_and_events(tournament_slug)

        owner_id = (tournament.get("owner") or {}).get("id")

        if event_slug:
            full_slug = f"tournament/{tournament_slug}/event/{event_slug}"
            with console.status("Fetching event..."):
                chosen_event = client.get_event_by_slug(full_slug)
            console.print(f"Tournament: [cyan]{tournament['name']}[/cyan]")
            console.print(f"Event:      [cyan]{chosen_event['name']}[/cyan]\n")

            series_name = seed_module.extract_series_name(tournament["name"])
            console.print(f"Searching series: [dim]{series_name}[/dim] (owner {owner_id})")
            historical = _fetch_historical(console, client, owner_id, series_name)

            # Jump straight to standings — event already resolved
            _run_seeding(
                console, client, tournament, chosen_event, historical, series_name, verbose
            )
            return

        series_name = seed_module.extract_series_name(tournament["name"])
        console.print(f"Searching series: [dim]{series_name}[/dim] (owner {owner_id})")
        historical = _fetch_historical(console, client, owner_id, series_name)

        events = tournament.get("events") or []

    console.print(f"Tournament: [cyan]{tournament['name']}[/cyan]")

    if not events:
        console.print("[red]No events found for this tournament.[/red]")
        sys.exit(1)

    if len(events) == 1:
        chosen_event = events[0]
    else:
        console.print("\nEvents:")
        chosen_event = prompt_pick(console, events)

    console.print(f"Event:      [cyan]{chosen_event['name']}[/cyan]\n")

    _run_seeding(
        console, client, tournament, chosen_event, historical, series_name, verbose
    )


def _fetch_historical(
    console: Console,
    client: StartGGClient,
    owner_id: int | None,
    series_name: str,
) -> list[dict]:
    if owner_id:
        with console.status("Fetching historical tournaments (by owner)..."):
            results = client.search_tournaments_by_owner(int(owner_id), per_page=20)
        if results:
            return results
        console.print("[yellow]Owner lookup returned nothing, falling back to name search.[/yellow]")
    with console.status("Fetching historical tournaments (by name)..."):
        return client.search_tournaments_by_name(series_name, per_page=20)


def _run_seeding(
    console: Console,
    client: StartGGClient,
    tournament: dict,
    chosen_event: dict,
    historical: list[dict],
    series_name: str,
    verbose: bool = False,
) -> None:
    def vprint(msg: str) -> None:
        if verbose:
            console.print(f"[dim cyan]│[/dim cyan] {msg}")
    historical = [
        t for t in historical
        if t["name"].lower().startswith(series_name.lower())
    ]

    with console.status("Fetching registered entrants..."):
        entrants = client.get_event_entrants(chosen_event["id"])

    entrant_tags: set[str] = set()
    user_id_to_tag: dict[int, str] = {}
    for entrant in entrants:
        try:
            p = entrant["participants"][0]
            tag = p["gamerTag"]
            entrant_tags.add(tag)
            user_id = (p.get("user") or {}).get("id")
            if user_id:
                user_id_to_tag[user_id] = tag
        except (KeyError, IndexError):
            continue

    if not entrant_tags:
        console.print("[red]No entrants found for this event.[/red]")
        sys.exit(1)

    console.print(f"Entrants: [bold]{len(entrant_tags)}[/bold]")

    # Build a name key for the chosen event: strip time/parenthetical suffix
    # e.g. "Game Title (19h/7pm)" -> "game title"
    chosen_base = re.split(r"[\(\|]", chosen_event["name"])[0].strip().lower()

    def _match_hist_event(events: list[dict]) -> dict | None:
        return next(
            (e for e in events if e["name"].lower().startswith(chosen_base)),
            None,
        )

    def _map_tag(p: dict) -> str | None:
        # Prefer user ID match (handles tag changes), fall back to tag.
        hist_tag = p.get("gamerTag")
        user_id = (p.get("user") or {}).get("id")
        return user_id_to_tag.get(user_id) or (hist_tag if hist_tag in entrant_tags else None)

    player_placements: dict[str, list[int]] = {}
    player_attendance: dict[str, list[int]] = {}
    matchups: dict[frozenset[str], list[int]] = {}
    ts_to_name: dict[int, str] = {}

    console.print(f"Series tournaments found: [dim]{', '.join(h['name'] for h in historical)}[/dim]")

    hist_log: list[str] = []
    with console.status("Fetching historical standings & brackets..."):
        for hist in historical:
            if hist["id"] == tournament["id"]:
                continue
            matching = _match_hist_event(hist.get("events") or [])
            if matching is None:
                hist_log.append(f"[dim]{hist['name']}: no matching event[/dim]")
                continue
            standings = client.get_event_standings(matching["id"])
            if not standings:
                hist_log.append(f"[dim]{hist['name']}: no standings[/dim]")
                continue
            hist_ts = hist.get("startAt") or 0
            ts_to_name[hist_ts] = hist["name"]
            for entry in standings:
                try:
                    tag = _map_tag(entry["entrant"]["participants"][0])
                except (KeyError, IndexError):
                    continue
                if tag is None:
                    continue
                player_placements.setdefault(tag, []).append(entry["placement"])
                player_attendance.setdefault(tag, []).append(hist_ts)

            # Actual round-1 matchups from the bracket.
            r1_sets = client.get_event_round1_sets(matching["id"])
            r1_count = 0
            for s in r1_sets:
                tags = []
                for slot in s.get("slots") or []:
                    entrant = slot.get("entrant") or {}
                    parts = entrant.get("participants") or []
                    if parts and (mapped := _map_tag(parts[0])):
                        tags.append(mapped)
                if len(tags) == 2 and tags[0] != tags[1]:
                    matchups.setdefault(frozenset(tags), []).append(hist_ts)
                    r1_count += 1
                    vprint(
                        f"R1 match in [b]{hist['name']}[/b]: {tags[0]} vs {tags[1]}"
                    )
            hist_log.append(f"{hist['name']}: {len(standings)} results, {r1_count} R1 matches")

    for line in hist_log:
        console.print(f"  {line}")

    event_count = len({ts for tss in player_attendance.values() for ts in tss})

    # Keep only current entrants; give unranked players an empty history
    player_placements = {tag: player_placements.get(tag, []) for tag in entrant_tags}

    console.print(
        f"Found [bold]{event_count}[/bold] historical event(s), "
        f"[bold]{sum(1 for v in player_placements.values() if v)}[/bold] with history.\n"
    )

    scores = seed_module.compute_scores(player_placements)

    if verbose:
        console.print("[bold cyan]── verbose ──[/bold cyan]")
        vprint(f"Flagged R1 rematch pairs ([b]{len(matchups)}[/b], DQs excluded):")
        for pair, dates in sorted(matchups.items(), key=lambda kv: max(kv[1]), reverse=True):
            x, y = tuple(pair)
            when = ", ".join(ts_to_name.get(d, "?") for d in sorted(dates, reverse=True))
            vprint(f"    {x} vs {y} — {when}")
        vprint("Score order before rematch avoidance:")
        for i, t in enumerate(sorted(scores, key=lambda t: scores[t], reverse=True), 1):
            vprint(f"    {i:>2}. {t} ([dim]{scores[t]:.3f}[/dim])")
        vprint("Resolving R1 conflicts (seeds 1-2 locked):")

    trace: list[str] | None = [] if verbose else None
    seed_list = seed_module.build_seed_list(
        scores,
        player_placements,
        matchups,
        player_attendance,
        len(player_placements),
        trace=trace,
    )

    if trace is not None:
        for line in trace:
            vprint(f"    {line}")
        console.print("[bold cyan]─────────────[/bold cyan]\n")

    table = Table(title="Proposed Seeding", header_style="bold magenta")
    table.add_column("Seed", style="bold", width=6)
    table.add_column("Player", min_width=20)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Recent Placements", min_width=18)

    for entry in seed_list:
        placements_str = ", ".join(
            f"[green]{p}[/green]" if p == 1 else str(p)
            for p in entry["placements"][:5]
        )
        table.add_row(
            str(entry["seed"]),
            entry["tag"],
            f"{entry['score']:.3f}",
            placements_str,
        )

    console.print(table)

    now = int(datetime.now().timestamp())
    week_ago = now - 7 * 86400
    seen: set[frozenset[str]] = set()
    rematch_lines: list[tuple[tuple[int, int], str]] = []
    for entry in seed_list:
        for r in entry["rematches"]:
            pair = frozenset({entry["tag"], r["opponent"]})
            if pair in seen:
                continue
            seen.add(pair)
            last_shared = r["last_shared"]
            ago = _format_ago(now - last_shared) if last_shared else "unknown"
            min_gap = r["min_gap"]
            last_for = r["last_for"]
            both_recent = all(
                max(player_attendance.get(p, []), default=0) >= week_ago
                for p in (entry["tag"], r["opponent"])
            )
            if both_recent:
                tail = ""
            elif len(last_for) == 1:
                tail = f" — {last_for[0]}'s last appearance"
            elif len(last_for) == 2:
                tail = " — both players' last appearance"
            else:
                tail = ""
            rematch_lines.append(
                ((-min_gap, last_shared), f"{entry['tag']} vs {r['opponent']} ({ago}){tail}")
            )

    if rematch_lines:
        console.print("\n[bold]R1 rematches:[/bold]")
        for _, line in sorted(rematch_lines, reverse=True):
            console.print(f"  [red]{line}[/red]")
    else:
        console.print("\n[green]No R1 rematches.[/green]")

    if not Confirm.ask("\nApply this seeding to start.gg?", default=False):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    with console.status("Fetching phases..."):
        phases = client.get_event_phases(chosen_event["id"])

    if not phases:
        console.print("[red]No phases found for this event.[/red]")
        sys.exit(1)

    phase = phases[0] if len(phases) == 1 else prompt_pick(console, phases)
    console.print(f"Phase: [cyan]{phase['name']}[/cyan]")

    with console.status("Fetching current seeds..."):
        phase_seeds = client.get_phase_seeds(phase["id"])

    tag_to_seed_id: dict[str, str] = {}
    for ps in phase_seeds:
        try:
            tag = ps["entrant"]["participants"][0]["gamerTag"]
            tag_to_seed_id[tag] = str(ps["id"])
        except (KeyError, IndexError):
            continue

    seed_mapping = []
    missing = []
    for entry in seed_list:
        seed_id = tag_to_seed_id.get(entry["tag"])
        if seed_id is None:
            missing.append(entry["tag"])
            continue
        seed_mapping.append({"seedId": seed_id, "seedNum": entry["seed"]})

    if missing:
        console.print(
            f"[yellow]Warning: {len(missing)} player(s) not found in phase seeds "
            f"and will be skipped: {', '.join(missing[:5])}[/yellow]"
        )

    with console.status("Writing seeding to start.gg..."):
        success = client.update_phase_seeding(phase["id"], seed_mapping)

    if success:
        console.print("[bold green]Seeding updated successfully![/bold green]")
    else:
        console.print("[bold red]Seeding update failed.[/bold red]")
        sys.exit(1)
