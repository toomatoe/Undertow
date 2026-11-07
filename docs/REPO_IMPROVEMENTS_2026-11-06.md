# Repository improvement review — 2026-11-06

## Decision and scope

Prioritize correctness in the existing News and Signals workflows. Source inspection found reproducible
request-ordering and pagination failures in both pages, while the frontend had no automated behavioral
test command. This pass implements a shared feed request lifecycle, server-authoritative live refresh,
recoverable pagination, and offline regression tests in CI. No study design, result, API schema, integration,
or deployment changes are included.

Plan and ownership: [feed reliability plan](plans/2026-11-06-feed-reliability.json).

## Findings addressed

| Finding in the original implementation | Consequence | Acceptance |
| --- | --- | --- |
| First-page requests committed without checking whether filters changed | Slow old requests could replace the active filter's rows, cursor, error, and loading state | Resolve requests out of order; only the current request commits |
| Pagination lacked a synchronous guard and request invalidation | Repeated clicks duplicated rows; old pages could append to a new filter | One pagination request at a time; obsolete pages ignored; merge by article ID |
| Pagination had no error handler | Failure produced an unhandled rejection without a usable retry | Preserve current rows and cursor, show the error, and retry |
| News fetched individual SSE article IDs and inserted/replaced rows independently of list filtering | Enrichment could change eligibility; in-flight event fetches survived filter changes | Treat events as update notifications; refresh through the filtered list endpoint |
| Signals automatically reloaded the first page after new events | Reading older pages could be interrupted by an ingest burst | Show a refresh notification without discarding the current page |
| News initialized the size selector with an unavailable empty option | Displayed option did not explicitly represent the effective query | Explicit All sizes default; preserve Signals' small-cap default |

React's official [Effect guidance](https://react.dev/learn/synchronizing-with-effects#fetching-data)
recommends aborting a fetch or ignoring its result when its Effect is cleaned up. Its
[useEffect reference](https://react.dev/reference/react/useEffect#fetching-data-with-effects) explains
that responses can arrive in a different order than requests. These support request invalidation;
the specific defects above were found in this repository, not inferred from framework guidance.

## Prioritized follow-up work

These are source-inspection findings, not changes delivered in this pass. Verify each with the listed
regression cases before implementation. Container verification was unavailable because Docker was not running.

1. **Complete pagination at tied timestamps.** `backend/app/main.py`, `list_articles` and `list_signals`,
   sort by `(published_at DESC, id DESC)` but return only a timestamp cursor and filter subsequent pages
   with `published_at < before`. Rows sharing the page boundary timestamp can be skipped. Add a compound
   cursor with a compatibility path for existing timestamp clients, mirror the contract in `api.ts`, and
   test more than one page of equal timestamps for exact coverage and no duplicates on both endpoints.
2. **Report EDGAR failures accurately.** `main.edgar_poller` updates the heartbeat after `poll_edgar`
   returns, including returned error/skipped results from `pipeline/ingest.py`. Advance the successful
   heartbeat only for successful polls; represent intentionally disabled EDGAR in health inputs.
   Test success, returned error, skipped, raised error, and disabled configurations without network calls.
3. **Validate uptime records and order by actual time.** `health.read_snapshots` accepts arbitrary
   component values. A list-valued component reaches set membership in `history` and can raise `TypeError`.
   History also sorts timestamp strings rather than parsed instants and groups offset timestamps without
   UTC normalization. Validate record/status shapes; test malformed nested values, mixed offsets, incident
   ordering, and UTC day boundaries while retaining valid records.
4. **Preserve hooks for partially successful ingestion.** `_store_source` commits each new article but
   clears `new_ids` if a later article fails. Earlier committed articles then miss their alert/journal hooks.
   Preserve committed IDs and test a source that succeeds once and then fails; hooks must run exactly once
   for the committed article, with the failure still recorded.

These backend changes should be a separate verified wave with `bash scripts/pytest.sh`, the full container
suite, and endpoint checks. They do not require changing the research taxonomy or pre-registered studies.

## Validation

Validation results will be recorded after implementation and independent review.
