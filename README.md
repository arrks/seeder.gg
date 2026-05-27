# seeder

CLI tool for seeding start.gg fighting game tournaments based on historical results.

Scores each entrant from their recent placements across every tournament of the same game on start.gg, weights those results by field size, and seeds the bracket while minimising first-round rematches against opponents they've recently played in this series. Writes seeding directly to start.gg.

## Install

```bash
git clone https://github.com/arrks/seeder.gg
cd seeder
uv sync
```

## Setup

```bash
cp .env.example .env
```

Edit `.env` and add your start.gg API token. You can generate one at [start.gg/admin/profile/developer](https://start.gg/admin/profile/developer).

```
STARTGG_TOKEN=your_token_here
```

Optionally, set a default tournament URL to skip the tournament/event picker:

```
STARTGG_URL=https://www.start.gg/tournament/your-tournament/event/your-event/
```

## Usage

```bash
uv run seeder
```

The tool will:

1. Fetch your recent tournaments and prompt you to pick one
2. Prompt you to pick an event
3. Pull each entrant's recent placements for that game from across start.gg, plus the last several editions of this series (for rematch detection)
4. Score players by placement weighted by field size and recency
5. Display the proposed seeding and flag any first-round rematch conflicts
6. Ask for confirmation before writing to start.gg

You can also pass a URL directly:

```bash
uv run seeder https://www.start.gg/tournament/your-tournament/event/your-event/
```

## How seeding works

- Only entrants registered for the chosen event are seeded.
- Each player's history is pulled from `player.recentStandings(videogameId)` — every recent event of the same game on start.gg, not just this series. Entrants without a linked start.gg account fall back to whatever results they have in prior editions of this series.
- Score per result: `max(0, log2(numEntrants / placement))`, summed across results with a `0.7^i` recency decay (most recent first). Bigger fields are worth more; mid-pack finishes at large events don't drag a player below zero.
- Historical editions of this series (matched by tournament series name + the event's `(videogame, type)`) are fetched separately and used to detect first-round rematches. Freshness of a rematch is measured in tournaments-since-last-meeting, not calendar time. Pairs whose last meeting is more than 6 tournaments back for both players are no longer considered competitively fresh and won't trigger swaps.
- The top three seeds are locked. For the rest, the seeder iteratively finds the freshest R1 rematch and tries every pairwise swap that touches one side of the conflict, picking the move that minimises total score deviation from the ideal score-per-seat profile. Near-equal players reshuffle freely; crossing a real skill gap is expensive.
