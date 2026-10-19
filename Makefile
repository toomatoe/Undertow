# Developer shortcuts. Python runs in Docker (see AGENTS.md); these targets only wrap the scripts.
#   make test                 backend suite against the current source (scripts/pytest.sh, parallel-safe)
#   make test-file F=tests/test_oos.py
#   make reproduce            offline replay of the in-sample study vs the newest docs/results file
#   make reproduce-oos        offline replay of the pre-registered OOS study
#   make reproduce-insiders   offline replay of the pre-registered Form 4 insider-purchase study
#   make snapshot             hash-only input manifest for {DATA_DIR}/event_study.json
# reproduce/snapshot run in the api image: rebuild it after code changes (docker compose build api).

.PHONY: test test-file reproduce reproduce-oos reproduce-insiders snapshot

test:
	bash scripts/pytest.sh

test-file:
	@test -n "$(F)" || (echo "usage: make test-file F=tests/test_x.py" && exit 2)
	bash scripts/pytest.sh $(F)

reproduce:
	bash scripts/reproduce.sh main

reproduce-oos:
	bash scripts/reproduce.sh oos

reproduce-insiders:
	bash scripts/reproduce.sh insiders

snapshot:
	docker compose run --rm -T -e GIT_SHA=$$(git rev-parse HEAD) api python -m app.research.snapshot write
