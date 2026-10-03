# Heal a crawl while it is still running

A Scrapy project for books.toscrape.com, built to [zytelabs/scrapy-openspec](https://github.com/zytelabs/scrapy-openspec)
(scrapy-poet page objects, attrs items, `savefixture` tests). One script, `heal.py`, runs the crawl,
watches it with Spidermon, and heals it mid-crawl with an agent that attaches through the
[Scrapy MCP server](https://github.com/scrapy/scrapy-mcp-official).

```
make stage        # copy to /tmp/scrapy-mcp-agent-mid-fix-crawl and install; run everything from there
cd /tmp/scrapy-mcp-agent-mid-fix-crawl
make run          # perfect run: every book complete in books.jsonl, fanfare
make show
make break        # break the price selector on purpose
make run          # no agent: the crawl finishes with 200 books and no prices, sad trombone
make run-with-heal   # Spidermon pauses the crawl, the agent fixes it, the crawl finishes, fanfare
make show         # a few broken rows at the top, then correct ones
make report       # HEAL_REPORT.md: tries, cost, the fix
make reset        # put the working selector back
```

## How the heal works

1. `base/quality.py` counts missing fields per item. A Spidermon periodic monitor checks the
   items scraped since its last check, twice a second. If any is missing a field, its action
   pauses the crawl engine (it does not stop it) and writes `.heal/TRIPPED.json`.
2. `heal.py` sees the trip and runs `claude -p`. The agent gets only Read, Edit and the four
   Scrapy MCP tools. It attaches to the paused crawl, tests selectors on the product pages
   still in memory (`crawler.recent_responses`), and edits `base/pages/books_toscrape_com.py`.
3. Then `heal.py` decides whether the fix goes in. It checks that no other file changed and runs the fixture tests
   (`uv run pytest tests -q`, the hand-checked answer key). If they pass, it loads the fixed
   page objects into the live crawl through the MCP, checks them on the in-memory pages, and
   unpauses. Books scraped while broken stay broken in `books.jsonl`: they are not re-crawled.
4. After two failed attempts, or once `HEAL_BUDGET_USD` is spent, it writes `ESCALATION.md` and
   stops the crawl.

Dials: `PAGES` (make variable, default 10), `HEAL_MODEL`, `HEAL_EFFORT`, `HEAL_MAX_ATTEMPTS`,
`HEAL_BUDGET_USD`. `CLAUDE_BIN` swaps in a fake agent to test the fail paths for free.

Sound: `base/quality.py` extends the [scrapy-beep](https://github.com/apscrapes/scrapy-fanfare-audio-plugin) extension. A fanfare plays when the crawl finishes with its last item complete, a sad trombone otherwise. `BEEP_ENABLED = False` in `base/settings.py` turns it off.

Needs Scrapy 2.19+ (the remote-control extension the MCP attaches to), [uv](https://docs.astral.sh/uv/)
and a signed-in `claude`.
`pytest<9` is pinned: a failing web-poet fixture test crashes pytest 9 with INTERNALERROR.

## Measured

10 catalogue pages (200 books), the price selector broken on purpose, 1 Oct 2026:

| Model | Healed on attempt 1 | Cost per heal | Agent time |
| --- | --- | --- | --- |
| Haiku, 3 runs | 3 of 3 | $0.06 to $0.08 | 37 to 50s |
| Sonnet, 3 runs | 3 of 3 | $0.07 to $0.09 | 15 to 18s |
| Opus, 3 runs | 3 of 3 | $0.12 to $0.14 | 22 to 31s |

Across those 9 runs, 8 to 16 books came out without a price (they were already downloading when
Spidermon paused the crawl) and the crawl never restarted. Sonnet is the default in the Makefile.
