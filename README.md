# seeder

CLI tool for seeding start.gg fighting game tournaments based on historical results.

Fetches recent standings from your tournament series, scores players by recency-weighted placements, and tries to avoid first-round rematches. Writes seeding directly to start.gg.

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
3. Pull standings from the last several editions of that series
4. Score players by placement, weighted toward recent results
5. Display the proposed seeding and flag any first-round rematch conflicts
6. Ask for confirmation before writing to start.gg

You can also pass a URL directly:

```bash
uv run seeder https://www.start.gg/tournament/your-tournament/event/your-event/
```

## How seeding works

- Players are scored using `sum(1/placement * 0.7^i)` across historical results, where `i=0` is the most recent tournament
- Only players registered for the current event are seeded
- The two most recent tournaments are used to detect potential first-round rematch conflicts
- Seeds 1–4 are locked by score; seeds 5+ are shuffled within groups of 4 to minimise conflicts
