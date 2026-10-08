# Self-healing spiders

Companion code for the Extract Summit workshop: can an agent fix a broken Scrapy
spider, and how far should you let it go?

Two demos, each in its own folder with its own README:

| Folder | What it shows |
|---|---|
| [`brittle-selector-healing/`](brittle-selector-healing/) | A bookshop redesign breaks the spider's selectors. `heal.sh` runs `claude -p` to fix the spider after the crawl, re-runs the checks itself, and hands over to a human after 2 failed attempts. Runs offline against local HTML. |
| [`scrapy-mcp-agent-mid-fix-crawl/`](scrapy-mcp-agent-mid-fix-crawl/) | A live crawl of books.toscrape.com breaks halfway. Spidermon pauses it, an agent attaches through the [Scrapy MCP server](https://github.com/scrapy/scrapy-mcp-official) and fixes the page object, the fixture tests decide, and the crawl carries on without a restart. |

The talk slides are in [`slides/index.html`](slides/index.html): open it in a browser, arrow keys to move, `f` for fullscreen, `l` for light mode.

You need [uv](https://docs.astral.sh/uv/) and a signed-in [Claude Code](https://code.claude.com) CLI
(`claude`). Each heal costs real tokens: the READMEs list what we measured.

Run the demos from a copy outside any folder that has its own `CLAUDE.md`, or the agent will
read those instructions too.
