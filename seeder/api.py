import time

import httpx


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
            resp.raise_for_status()
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
                  }
                }
              }
            }
            """,
            {"name": name_prefix, "perPage": per_page},
        )
        return data["tournaments"]["nodes"]

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
