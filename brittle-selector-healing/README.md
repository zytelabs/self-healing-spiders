# Brittle selector healing: the site got redesigned

A spider scrapes a bookshop. The bookshop is redesigned, the spider silently
returns empty fields, and an agent repairs it: up to 2 attempts, then it hands
over to a human.

Everything lives in this folder. The "site" is two HTML files read from disk,
so there is no server and no network, except for the agent itself.

## Files

| File | What it is |
| --- | --- |
| `site/v1.html` | the bookshop before the redesign |
| `site/v2.html` | after: same books and prices, new markup, plus a struck-through old price |
| `site/gone.html` | prices behind a sign-in, so there is nothing to fix: shows the escalation |
| `books.py` | the spider, written for v1 |
| `check.py` | four checks on the output: count, fields present, values sane, golden sample |
| `heal.sh` | the repair loop: up to 2 agent attempts, then `ESCALATION.md` |
| `books_wrong.py` | a saved wrong fix that passes three checks and fails the golden sample |
| `reset.sh` | back to the starting state |

Open `site/v1.html` and `site/v2.html` side by side and use Inspect to see
the selectors change while the page shows the same books.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and a signed-in `claude` CLI.

```bash
uv run scrapy runspider books.py -a site=v1 -O out.json && uv run python check.py   # all green
uv run scrapy runspider books.py -a site=v2 -O out.json && uv run python check.py   # broken
./heal.sh                                                                           # repair it
./reset.sh                                                                          # start again (asks twice)
```

`heal.sh` prints each tool call the agent makes, then after every attempt the
verdict, cost, time, turns and a budget bar. Before the first attempt it copies
`books.py` to `books.before.py`, so `diff -u books.before.py books.py` shows
what the agent changed. On success it prints that diff and
`HEALED on attempt N of 2 · $X · Ys`. After 2 failures it writes
`ESCALATION.md` with every attempt, its cost, the last check output and the
last diff. If the agent edits `check.py` or `site/`, that attempt fails and
the files are put back.

A fix that looks right and isn't:

```bash
uv run scrapy runspider books_wrong.py -O wrong.json && uv run python check.py wrong.json
```

Settings, all at the top of `heal.sh`:

```bash
HEAL_MAX_ATTEMPTS=2      # tries before ESCALATION.md
HEAL_BUDGET_USD=10       # stop early once this much is spent
HEAL_MODEL=sonnet        # opus | sonnet | haiku, empty = CLI default
HEAL_EFFORT=low          # low | medium | high | xhigh | max
```

For example `HEAL_MODEL=sonnet HEAL_EFFORT=low ./heal.sh`. Tool access is
`TOOLS` in the same block, an allowlist passed as `--tools` with
`--strict-mcp-config`: Read, Grep, Glob and Bash, no web, no MCP servers, no subagents.
A denylist is not enough: with Bash, Edit and Write denied, the agent found
`Monitor` through `ToolSearch` and wrote `books.py` with it.

To see an escalation, run `./heal.sh gone`: the prices are not in that page,
so both attempts fail and `ESCALATION.md` explains why.

## Run it from a clean folder

Claude Code reads every `CLAUDE.md` above the folder it runs in. If your own
projects folder has one, copy this demo somewhere outside it (for example
`/tmp`) so the agent only sees what is in the demo.

## Measured

Claude Opus 5.5 unless noted, 10 books on one page:

| Run | Result |
| --- | --- |
| v2, 7 runs (28 and 29 Sep 2026) | healed on attempt 1 every time, $0.07 to $0.16, 24 to 31s |
| v2, Sonnet 5 at low effort, 1 run (28 Sep) | healed on attempt 1, $0.08, 21s |
| v2 without Bash (Read, Grep, Glob only), 3 runs (29 Sep) | escalated after 2 attempts, $0.11 to $0.24, 33 to 49s |
| gone, 2 runs (29 Sep) | escalated after 2 attempts, $0.17 to $0.19, 57 to 61s |
