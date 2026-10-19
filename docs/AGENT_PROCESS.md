# Agent process graph

How work gets done on QuantDesk with multiple agents. The orchestrator, the main Claude session,
doesn't write the plan, ownership rules and review steps from scratch each time. They live here as
two graphs.

## 1. The repo graph: `docs/agent-graph.json`

Nodes are **modules**. Each one has:

- `paths`: the files and directories it covers.
- `agents_md`: the guide an agent reads before touching it.
- `depends_on`: what it builds on. Reverse these edges to see what a change could break.
- `tests`: what to run when it changes.
- `hotspot: true`: files many features need, such as `main.py`, `models.py` and `api.ts`.

`shared_resources` lists things only one agent may use at a time: the Docker image build, `frontend/.next`,
the dev database, and the hotspot files.

**Keep it current:** a new module gets a node in the same PR that adds it. Every file in the repo should match exactly
one module path (a path ending in `/` is a directory prefix), and each module lists its own test files in `paths`, so a
planner can hand out ownership without gaps or overlaps. The `tooling` module covers `scripts/` (incl. `reproduce.sh`),
`.claude/workflows/`, `scripts/start.ps1`, the `Makefile`, both compose files (`docker-compose.yml` with its `web` profile, and the
optional, for-later `docker-compose.prod.yml`), the api and web
Dockerfiles, CI (`.github/`), ignore/attributes files and pytest config. Check coverage after adding files: every path from
`git ls-files --cached --others --exclude-standard` must match exactly one module path.

`.github/workflows/ci.yml` runs on every push and PR (backend pytest, frontend tsc + lint + `next build`, both images built,
never pushed). It runs on GitHub's machines, so it does not touch the local shared resources; it does not replace the
Verify node.

## 2. The process graph: `.claude/workflows/feature-graph.js`

```
            ┌──────────┐
 goal ───▶  │  Plan    │  planner agent → work items {id, modules, owned_paths, depends_on, acceptance}
            └────┬─────┘
                 ▼
          schedule (plain code, no agent)
          • add an edge B→A when A and B own overlapping paths  ← no two builders share a file
          • topological levels → waves
                 ▼
   ┌──────────── wave 1 ─────────────┐      ┌──── wave 2 ────┐
   │ item a: Build → Review×2 → Fix↺ │      │ item c: ...    │
   │ item b: Build → Review×2 → Fix↺ │ ───▶ │                │ ───▶ ...
   └───────────────┬─────────────────┘      └───────┬────────┘
                   ▼                                ▼
            Verify (exclusive)               Verify (exclusive)
            image build, full pytest,        …
            tsc, live endpoint curls
            failures → targeted fix → re-verify
                                                   ▼
                                               Critic → gaps + next items
```

### Node rules

| Node | Who | Rules |
|---|---|---|
| Plan | 1 agent | 1–6 items. Each item owns exact paths, and hotspot files have a single owner. Anything that needs the user (keys, accounts, legal review) goes in `notes`, with the feature config-gated. |
| Build | 1 agent per item, in parallel within a wave | Edit only owned paths. Backend tests via `scripts/pytest.sh` (mounts the source; safe to run in parallel). Never `docker compose build/run/up`, never `next build`. |
| Review | 2 agents per item, run in parallel | Lens **correctness** covers bugs, tests, UTC timestamps, nullable migrations and edits outside owned paths. Lens **contract** covers API↔`api.ts` type sync, AGENTS.md updates, content rules (no advice language, hypothetical labels) and secrets. Blocker or major issues go back to the builder, at most 2 fix rounds. |
| Verify | 1 agent per wave; the only node allowed to use shared resources | `docker compose build -q api` → full pytest → `tsc` → restart the API and curl touched endpoints. A failure goes to the likely item's builder, then one re-verify. |
| Docs | 1 agent, added automatically as the last item | Unless the plan already has an item with id `docs` (or `review_only` is set), the workflow appends a `docs` item that depends on every feature item and owns `SHARED_DOCS`: `README.md`, `AGENTS.md`, `.env.example`, `docs/`, `frontend/AGENTS.md`, `backend/AGENTS.md`. These paths are stripped from feature items' `owned_paths`, so feature builders report shared-doc changes instead of making them, and module-local AGENTS.md files stay with their feature. |
| Critic | 1 agent | Compares the result with the goal: missing pieces, unverified claims, stale docs. Its output becomes the next run's goal. |

### Why it's a graph and not a list

- **Ownership edges come from data,** not from the orchestrator remembering to say "don't touch X". Two items that both need `main.py` are serialized automatically.
- **Shared resources are modeled as an exclusive node.** Parallel `docker compose build` runs used to collide, and `next build` used to break the dev server. Builders now test against mounted source, and only Verify rebuilds.
- **Review is two independent lenses, not one.** The contract lens catches what the correctness lens is blind to, and vice versa.
- **The run is resumable and repeatable.** Same goal, same graph, same gates every time.

## Running it

From the orchestrator session:

```js
Workflow({ name: "feature-graph", args: { goal: "Email alert delivery via SMTP, config-gated" } })
// Already built, just review + verify + critic:
Workflow({ name: "feature-graph", args: { review_only: true, items: [ {id, title, task, modules, owned_paths, depends_on: [], acceptance: [] } ] } })
```

Loading notes:

- Saved workflows in `.claude/workflows/` are discovered when a session starts. A session that started before the file existed won't find it by `name`.
- In the Claude desktop app's virtualized scratch folders, `scriptPath` can be refused. Pass the file's contents through `script` instead. The Workflow tool then saves a copy under the session directory, and later runs can use that copy by `scriptPath`.

After it returns, the orchestrator still:

- reads the results,
- spot-checks in the browser,
- runs `next build` with the dev server stopped,
- writes the commit and PR.

Merging is the orchestrator's call, made after its own review.

## Helper: `scripts/pytest.sh`

Runs backend tests against the current source in the `quantdesk-api-test` dependency image without rebuilding it.
It mounts `backend/` at `/app` and the repo root read-only at `/repo`, so tests that compare backend code with `docs/` or
`frontend/` (`tests/test_paper_numbers.py`, the bundled-evidence check in `tests/test_insider_live.py`) can see them; they
skip when the mount is missing. Both mounts are per-container, so parallel runs stay safe.
It also handles Windows' virtualized path for the Claude desktop app, where Docker sees `AppData/Local/Packages/Claude_*/LocalCache/Roaming/...`.

```bash
bash scripts/pytest.sh tests/test_halts.py
```
