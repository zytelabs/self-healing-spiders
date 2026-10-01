# Heal a Scrapy crawl while it is still running.
# Run it from a copy (make stage), away from any CLAUDE.md files the agent would otherwise read.

PAGES ?= 10
# Seconds to hold each heal step on screen, so you can follow it. PACE=0 for full speed.
PACE ?= 1
# Pin the model: the CLI default can change. Sonnet was fastest in 3+3+3 runs, 1 Oct 2026.
export HEAL_MODEL ?= sonnet
STAGE ?= /tmp/scrapy-mcp-agent-mid-fix-crawl
PO = base/pages/books_toscrape_com.py

.PHONY: install run break reset show diff report test stage clean

install:            ## install dependencies
	uv sync

run:                ## crawl, watch with Spidermon, heal mid-crawl if it breaks
	HEAL_PACE=$(PACE) uv run python heal.py $(PAGES)

break:              ## break the price selector on purpose
	@perl -0pi -e 's/(def price.*?)p\.price_color/$$1p.price-now/s' $(PO)
	@grep -n "price-now" $(PO) && echo "✗ broke the price selector: p.price_color → p.price-now"

reset:              ## put the working selector back
	@cp .baseline/books_toscrape_com.py $(PO) && echo "✓ page objects restored"

show:               ## show what the crawl wrote
	@uv run python show.py

diff:               ## the page object before the heal, against the agent's fix
	@diff -u .heal/books_toscrape_com.before.py $(PO) 2>/dev/null \
	  || test -f .heal/books_toscrape_com.before.py || echo "no heal in the last run, so no diff"

report:             ## what the agent did: tries, cost, the fix
	@cat HEAL_REPORT.md 2>/dev/null || echo "no heal in the last run, so no report"

test:               ## the fixture tests, the gate every fix must pass
	uv run pytest tests -q

stage:              ## copy to $(STAGE) and install there
	rsync -a --delete --exclude .venv --exclude .heal --exclude books.jsonl --exclude 'HEAL_REPORT.md' \
	  --exclude ESCALATION.md --exclude __pycache__ ./ $(STAGE)/
	cd $(STAGE) && uv sync -q && echo "✓ staged in $(STAGE)"

clean:              ## remove crawl output and heal logs
	rm -rf .heal books.jsonl HEAL_REPORT.md ESCALATION.md
