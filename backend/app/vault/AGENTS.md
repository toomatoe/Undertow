# backend/app/vault: Obsidian vault export

Writes Undertow's data as plain Markdown into an Obsidian vault folder Undertow owns: `<VAULT_DIR>/Undertow/`.
A human (or an agent working in the vault) reads it in Obsidian, writes notes next to it, and Undertow reads
thesis notes back. Research and education only; content rules from frontend/AGENTS.md apply (no buy/sell language,
every number labelled historical or hypothetical).

**Never imports `app.main`** (circular). Everything main-specific is a parameter (`evidence_fn`, `paper_fn`).
**Never reads `Settings`**: no setting other than the vault/data paths passed in can reach the vault (no SEC user
agent, admin token, SMTP/email values, API keys).

## Files

| File | What |
|---|---|
| `exporter.py` | `export_vault`, `ExportResult`, `read_state`, `count_conflicts`, `EXPORT_LOCK`, `make_evidence_fn`; one renderer per note type |
| `writer.py` | Update policies: `write_once`, `write_copy`, `write_machine`, `write_fenced` (fence/hash, sealed journal mode), `write_conflict` |
| `fs.py` | `VaultFS`: the only writer. Path confinement, filename sanitizing, atomic write-if-changed, append-only lines. No delete helper |
| `frontmatter.py` | Deterministic YAML emitter, `yaml.safe_load` parsing with a minimal fallback parser, raw key chunks |
| `render.py` | Pure text helpers: accession from URL, 8-K items from title, evidence sentence, excerpts, money/percent |
| `readback.py` | `read_theses` |
| `bases/*.base` | Static Obsidian Bases YAML copied to `Undertow/Bases/` |
| `static/vault_agents.md`, `static/vault_claude.md` | Copied to `Undertow/AGENTS.md` (schema + rules for agents in the vault) and `Undertow/CLAUDE.md` (pointer) |
| `working_paper.md` | Byte-identical copy of `docs/paper/WORKING_PAPER.md` (the api image is built from `./backend`, so `docs/` is not in it). Copied to `Undertow/Paper/working-paper.md` |

When `docs/paper/WORKING_PAPER.md` changes, copy it here too (as for `frontend/src/content/working-paper.md`);
`tests/test_vault.py::test_working_paper_copy_is_identical` fails otherwise (needs the `/repo` mount).
When a note schema changes, update `static/vault_agents.md`.

## Layout (`<vault_dir>/Undertow/`)

| Path | Policy |
|---|---|
| `Tickers/<SYMBOL>.md` | symbols with a signal filing in the lookback window or on the watchlist. Fenced block regenerated; `## My notes` created once |
| `Signals/<YYYY-MM-DD>-<SYMBOL>-<form>-<accession suffix>.md` | signal filings in the lookback window; write-once. Accession from the EDGAR URL (no column), else `a<article id>` |
| `Journal/<entry id>.md` | every `JournalEntry`; sealed mode (below) |
| `Briefs/<YYYY-MM-DD>.md` | days with signal filings in the window, plus today (UTC). Today's is fenced/regenerated; past days created if missing, then frozen |
| `Studies/<name>.md` | each existing study file (`study_files`, default `DEFAULT_STUDY_FILES`); machine note |
| `Paper/working-paper.md`, `Bases/*.base`, `AGENTS.md`, `CLAUDE.md` | copies, rewritten only when the bytes differ |
| `Newsletter/<issue id>.md` | archived issue Markdown (`newsletter.service.list_issues/load_text`) plus frontmatter; write-once |
| `index.md` | catalog (counts + newest links per folder); machine note |
| `log.md` | append-only (`open('a')`): `- <UTC ts> created=N updated=N unchanged=N conflicts=N errors=N`, only for runs that changed something or had conflicts/errors |
| `_conflicts/<name>-<UTC ts>.md` | new content for a note whose fenced block was edited by hand (an identical pending conflict file is not written twice) |

`{data_dir}/vault_state.json` (outside the vault) holds the last `ExportResult` and when it was written.

## Safety rules (enforced in `fs.py` / tested)

- Every target resolves inside `realpath(<vault_dir>)/Undertow` (no `..`, no symlinked folder or file, `Undertow`
  itself must not be a symlink). Filename components: `[A-Za-z0-9._-]`, no leading dot, max 120 chars.
- Atomic writes (temp file in the same dir + `os.replace`, mode 0644), only when the bytes differ, so a second export
  with unchanged data writes 0 files and appends nothing to `log.md`.
- **Nothing is ever deleted** (no unlink/remove/rmtree anywhere in the package; a test greps for it).
- Third-party text is an excerpt (≤ 500 chars of `ai_summary` or `snippet`, never `body`) with HTML comment markers removed.
- Briefs: every prose line is checked with `newsletter.service.banned_words()` on a copy with tickers and note
  names blanked; a flagged line is dropped and logged at error level (the test asserts none is ever flagged).

## Fence/hash mechanism (`writer.py`)

Generated content sits between `<!-- undertow:begin -->` and `<!-- undertow:end -->`; its sha256 is stored in the
frontmatter (`undertow_hash`; journal notes: `outcome_hash`). On re-export, if the block in the file no longer
hashes to the stored value (a human edited inside the fence), the note is not touched and the new note goes to
`_conflicts/`. Otherwise only the block is replaced. Machine keys are regenerated in a fixed order; keys a human
added are kept as raw text; volatile keys (`generated_at`, `updated`) are carried over when the rest is unchanged.

**Sealed mode (journal):** every existing non-`outcome_` key is copied verbatim (raw text) from the file; only
`sealed_day`/`seal_hash` may go from null to a value once (when the day appears in `journal_chain.jsonl`). The
`outcome_*` keys and the fenced outcome block are regenerated. The head text above the fence is written once.

## Public API (used by the vault API item)

```python
from app.vault import EXPORT_LOCK, ExportResult, export_vault, read_state, count_conflicts, read_theses, make_evidence_fn

with EXPORT_LOCK:   # callers prevent overlapping runs; export_vault does not take the lock itself
    res = export_vault(session, vault_dir=..., data_dir=..., lookback_days=30,
                       evidence_fn=None,   # (signal_code, bucket) -> Evidence/EvidenceOut/dict | None
                       paper_fn=None,      # () -> paper.service.build_portfolio(...) dict | None
                       study_files=None,   # {name: filename under data_dir}; default DEFAULT_STUDY_FILES
                       now=None)           # aware datetime; default utcnow
res.to_dict()  # {created, updated, unchanged, conflicts, errors, counts{folder: n}, conflict_paths, started_at, finished_at}
read_state(data_dir) -> dict | None        # {"last_export": {...}, "written_at": ...}
count_conflicts(vault_dir) -> int
read_theses(vault_dir, ticker=None, limit=50) -> [{title, path, ticker, updated, tags, excerpt}]
make_evidence_fn(data_dir) -> evidence_fn  # event_study.json 20-day rows + insider forward-test row, no app.main
```

`export_vault` never raises for one bad note: per-note and per-stage exceptions are logged and counted in `errors`.
Evidence in main.py terms: `state.evidence` (main study) for `ALL_SIGNALS` codes and `forward_evidence()` for
`FORWARD_TEST_SIGNALS` codes; `make_evidence_fn` reproduces that from files.

`read_theses`: walks the vault excluding `Undertow/`, `.obsidian/`, `.git/`, `.trash/` and any dot-dir; `*.md` only;
no symlinks; skips files > 1 MB; stops after 5000 files; safe frontmatter parsing only. A thesis = `type: thesis` or
`tags` containing `undertow/thesis` (string or list, `#` optional). `ticker` matches `ABCD`, `[[ABCD]]` or a list,
case-insensitively. Sorted by `updated` (frontmatter `updated`/`date`, else file mtime date) descending.

Settings (`app/config.py`): `VAULT_ENABLED` (true), `VAULT_DIR` (`./vault`; compose `/app/vault`, bind-mounted from
`VAULT_HOST_DIR`, default `./vault`), `VAULT_LOOKBACK_DAYS` (30), `VAULT_EXPORT_MINUTES` (15). The scheduler wiring
lives in main.py (not owned by this module).

## Tests

`tests/test_vault.py` (tmp dirs, in-memory SQLite, no network; `fundamentals.company_profile` and `httpx.get` are
patched to fail): rendering and `yaml.safe_load` of every note type, `## My notes` survives, fence edit -> conflict
file with the original untouched, nothing outside `<vault>/Undertow` (sentinel in the vault root), idempotence
(second run 0 created/updated, same bytes and mtimes, `log.md` unchanged), journal sealed fields immutable while
`outcome_*` updates, signal notes and past briefs immutable, `.base` files parse, thesis read-back variants, no
secrets (marker env values never appear), banned words in briefs, working-paper copy identical, no delete calls,
symlink/`..` confinement, fallback frontmatter parser.
