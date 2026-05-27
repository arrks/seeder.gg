import time

import httpx


def _is_dq(set_node: dict) -> bool:
    """A set is a DQ if start.gg labels it 'DQ' or a slot's score is -1."""
    if (set_node.get("displayScore") or "").strip().upper() == "DQ":
        return True
    for slot in set_node.get("slots") or []:
        score = (((slot.get("standing") or {}).get("stats") or {}).get("score") or {}).get("value")
        if score == -1:
            return True
    return False


class StartGGClient:
    BASE_URL = "https://api.start.gg/gql/alpha"

    def __init__(self, token: str) -> None:
        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    def _query(self, query: str, variables: dict) -> dict:
        for attempt in range(2):
            resp = self._http.post(self.BASE_URL, json={"query": query, "variables": variables})
            if resp.status_code == 429 and attempt == 0:
                time.sleep(2)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"start.gg API {resp.status_code}: {resp.text[:500]}"
                )
            data = resp.json()
            if "errors" in data:
                raise RuntimeError(f"GraphQL error: {data['errors']}")
            return data["data"]
        resp.raise_for_status()
        return {}

    def get_current_user_with_tournaments(self, per_page: int = 20) -> dict:
        data = self._query(
            """
            query CurrentUserTournaments($perPage: Int!) {
              currentUser {
                name
                slug
                player { gamerTag }
                tournaments(query: { perPage: $perPage }) {
                  nodes {
                    id
                    name
                    slug
                    startAt
                    events {
                      id
                      name
                      type
                      videogame { id }
                      numEntrants
                    }
                  }
                }
              }
            }
            """,
            {"perPage": per_page},
        )
        return data["currentUser"]

    def get_tournament_and_events(self, tournament_slug: str) -> dict:
        data = self._query(
            """
            query TournamentEvents($slug: String!) {
              tournament(slug: $slug) {
                id
                name
                owner { id }
                events {
                  id
                  name
                  type
                  videogame { id }
                  numEntrants
                }
              }
            }
            """,
            {"slug": tournament_slug},
        )
        return data["tournament"]

    def search_tournaments_by_owner(self, owner_id: int, per_page: int = 6) -> list[dict]:
        data = self._query(
            """
            query TournamentsByOwner($ownerId: ID!, $perPage: Int!) {
              tournaments(query: {
                filter: { ownerId: $ownerId }
                perPage: $perPage
                sortBy: "startAt desc"
              }) {
                nodes {
                  id
                  name
                  slug
                  startAt
                  events {
                    id
                    name
                    type
                    videogame { id }
                    numEntrants
                  }
                }
              }
            }
            """,
            {"ownerId": owner_id, "perPage": per_page},
        )
        return data["tournaments"]["nodes"]

    def get_event_by_slug(self, full_slug: str) -> dict:
        data = self._query(
            """
            query EventBySlug($slug: String!) {
              event(slug: $slug) {
                id
                name
                type
                videogame { id }
              }
            }
            """,
            {"slug": full_slug},
        )
        return data["event"]

    def get_event_entrants(self, event_id: int, per_page: int = 64) -> list[dict]:
        all_nodes: list[dict] = []
        page = 1
        while True:
            data = self._query(
                """
                query EventEntrants($eventId: ID!, $page: Int!, $perPage: Int!) {
                  event(id: $eventId) {
                    entrants(query: { page: $page, perPage: $perPage }) {
                      nodes {
                        participants {
                          gamerTag
                          user { id }
                          player { id }
                        }
                      }
                    }
                  }
                }
                """,
                {"eventId": event_id, "page": page, "perPage": per_page},
            )
            nodes = data["event"]["entrants"]["nodes"]
            all_nodes.extend(nodes)
            if len(nodes) < per_page:
                break
            page += 1
        return all_nodes

    def get_event_phases(self, event_id: int) -> list[dict]:
        data = self._query(
            """
            query EventPhases($eventId: ID!) {
              event(id: $eventId) {
                phases {
                  id
                  name
                  numSeeds
                }
              }
            }
            """,
            {"eventId": event_id},
        )
        return data["event"]["phases"]

    def get_event_standings(self, event_id: int, per_page: int = 64) -> list[dict]:
        all_nodes: list[dict] = []
        page = 1
        while True:
            data = self._query(
                """
                query EventStandings($eventId: ID!, $page: Int!, $perPage: Int!) {
                  event(id: $eventId) {
                    standings(query: { page: $page, perPage: $perPage }) {
                      nodes {
                        placement
                        entrant {
                          participants {
                            gamerTag
                            user { id }
                          }
                        }
                      }
                    }
                  }
                }
                """,
                {"eventId": event_id, "page": page, "perPage": per_page},
            )
            nodes = data["event"]["standings"]["nodes"]
            all_nodes.extend(nodes)
            if len(nodes) < per_page:
                break
            page += 1
        return all_nodes

    def get_event_round1_sets(self, event_id: int, per_page: int = 32) -> list[dict]:
        """Return round-1 sets (winners round 1) that were actually played.

        Skips DQs — a round-1 no-show isn't a real match, so it shouldn't count
        as a rematch.
        """
        all_nodes: list[dict] = []
        page = 1
        while True:
            data = self._query(
                """
                query EventSets($eventId: ID!, $page: Int!, $perPage: Int!) {
                  event(id: $eventId) {
                    sets(page: $page, perPage: $perPage, sortType: STANDARD) {
                      nodes {
                        round
                        displayScore
                        slots {
                          standing { stats { score { value } } }
                          entrant {
                            participants {
                              gamerTag
                              user { id }
                            }
                          }
                        }
                      }
                    }
                  }
                }
                """,
                {"eventId": event_id, "page": page, "perPage": per_page},
            )
            sets = (data.get("event") or {}).get("sets")
            if not sets:
                break
            nodes = sets.get("nodes") or []
            all_nodes.extend(
                n for n in nodes if n.get("round") == 1 and not _is_dq(n)
            )
            if len(nodes) < per_page:
                break
            page += 1
        return all_nodes

    def search_tournaments_by_name(self, name_prefix: str, per_page: int = 6) -> list[dict]:
        data = self._query(
            """
            query TournamentSearch($name: String!, $perPage: Int!) {
              tournaments(query: {
                filter: { name: $name }
                perPage: $perPage
                sortBy: "startAt desc"
              }) {
                nodes {
                  id
                  name
                  slug
                  startAt
                  events {
                    id
                    name
                    type
                    videogame { id }
                    numEntrants
                  }
                }
              }
            }
            """,
            {"name": name_prefix, "perPage": per_page},
        )
        return data["tournaments"]["nodes"]

    def get_players_recent_standings(
        self,
        player_ids: list[int],
        videogame_id: int,
        limit: int = 10,
        chunk_size: int = 20,
    ) -> dict[int, list[dict]]:
        """Batched recent standings for many players at events of a given videogame.

        Uses GraphQL aliases to fetch up to `chunk_size` players per HTTP request.
        If start.gg rejects a chunk for exceeding query complexity, the chunk is
        split in half and each half retried — so callers don't need to tune
        `chunk_size` against a moving server-side limit. Returns
        {player_id: [{placement, event: {id, numEntrants, startAt}}, ...]} with
        only Event-container standings; players whose entry returned null are
        mapped to an empty list.
        """
        results: dict[int, list[dict]] = {pid: [] for pid in player_ids}

        def fetch(chunk: list[int]) -> None:
            if not chunk:
                return
            var_decls = ", ".join(f"$p{i}: ID!" for i in range(len(chunk)))
            fields = "\n".join(
                f"""
                p{i}: player(id: $p{i}) {{
                  recentStandings(videogameId: $videogameId, limit: $limit) {{
                    placement
                    container {{
                      __typename
                      ... on Event {{ id numEntrants startAt }}
                    }}
                  }}
                }}
                """
                for i in range(len(chunk))
            )
            query = (
                f"query PlayersRecent($videogameId: ID!, $limit: Int!, {var_decls}) "
                f"{{\n{fields}\n}}"
            )
            variables: dict = {"videogameId": videogame_id, "limit": limit}
            for i, pid in enumerate(chunk):
                variables[f"p{i}"] = pid
            try:
                data = self._query(query, variables)
            except RuntimeError as exc:
                if "complexity" in str(exc).lower() and len(chunk) > 1:
                    mid = len(chunk) // 2
                    fetch(chunk[:mid])
                    fetch(chunk[mid:])
                    return
                raise
            for i, pid in enumerate(chunk):
                player = data.get(f"p{i}") or {}
                standings = player.get("recentStandings") or []
                out: list[dict] = []
                for s in standings:
                    c = s.get("container") or {}
                    if c.get("__typename") != "Event":
                        continue
                    out.append(
                        {
                            "placement": s.get("placement"),
                            "event": {
                                "id": c.get("id"),
                                "numEntrants": c.get("numEntrants"),
                                "startAt": c.get("startAt"),
                            },
                        }
                    )
                results[pid] = out

        for start in range(0, len(player_ids), chunk_size):
            fetch(player_ids[start : start + chunk_size])
        return results

    def get_phase_seeds(self, phase_id: int, per_page: int = 64) -> list[dict]:
        all_nodes: list[dict] = []
        page = 1
        while True:
            data = self._query(
                """
                query PhaseSeeds($phaseId: ID!, $page: Int!, $perPage: Int!) {
                  phase(id: $phaseId) {
                    seeds(query: { page: $page, perPage: $perPage }) {
                      nodes {
                        id
                        seedNum
                        entrant {
                          name
                          participants {
                            gamerTag
                          }
                        }
                      }
                    }
                  }
                }
                """,
                {"phaseId": phase_id, "page": page, "perPage": per_page},
            )
            nodes = data["phase"]["seeds"]["nodes"]
            all_nodes.extend(nodes)
            if len(nodes) < per_page:
                break
            page += 1
        return all_nodes

    def update_phase_seeding(self, phase_id: int, seed_mapping: list[dict]) -> bool:
        data = self._query(
            """
            mutation UpdatePhaseSeeding($phaseId: ID!, $seedMapping: [UpdatePhaseSeedInfo]!) {
              updatePhaseSeeding(phaseId: $phaseId, seedMapping: $seedMapping) {
                id
              }
            }
            """,
            {"phaseId": phase_id, "seedMapping": seed_mapping},
        )
        return data.get("updatePhaseSeeding") is not None
