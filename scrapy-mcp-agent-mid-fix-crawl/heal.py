"""Run the crawl, and heal the page objects while it is still running.

Usage: uv run python heal.py [pages]      pages of the catalogue to crawl, default 10

The crawl runs with a Spidermon monitor that checks new items twice a second. When items come out
with missing fields it pauses the crawl, and this script asks an agent to fix the page objects.
The agent attaches to the paused crawl through the Scrapy MCP server. The fixture tests decide
whether the fix is good; only then is it loaded into the live crawl, which resumes.
"""

import asyncio
import difflib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ── what you can turn ───────────────────────────────────────────────
MAX_ATTEMPTS = int(os.environ.get("HEAL_MAX_ATTEMPTS", 2))  # tries before a human gets ESCALATION.md
BUDGET_USD = float(os.environ.get("HEAL_BUDGET_USD", 5))    # stop early once this much is spent
MODEL = os.environ.get("HEAL_MODEL", "")                     # opus | sonnet | haiku, empty = CLI default
EFFORT = os.environ.get("HEAL_EFFORT", "")                   # low | medium | high | xhigh | max
AGENT_TIMEOUT = 300                                          # seconds per attempt
PACE = float(os.environ.get("HEAL_PACE", 0))                 # stage: seconds to hold each heal step on screen
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")              # a fake agent tests the fail paths for free
# ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
PAGES_FILE = ROOT / "base/pages/books_toscrape_com.py"
HEAL = ROOT / ".heal"
FEED = ROOT / "books.jsonl"
REPORT = ROOT / "HEAL_REPORT.md"
ESCALATION = ROOT / "ESCALATION.md"
MCP_SERVER = Path(sys.prefix) / "bin" / "scrapy-mcp"
MCP_TOOLS = ["list_jobs", "status", "execute", "inspection_reference"]
GUARDED = ["base", "tests", "heal.py", "pyproject.toml", "Makefile"]  # everything but PAGES_FILE

RUNNING = []  # child processes to stop if heal.py exits early

C = {"red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m", "cyan": "\033[36m",
     "dim": "\033[2m", "bold": "\033[1m", "off": "\033[0m"}


def books(n):
    return f"{n} book" + ("" if n == 1 else "s")


def say(text, color=None):
    print(f"{C[color]}{text}{C['off']}" if color else text, flush=True)


def hold(steps=1.0):
    """Hold each step on screen long enough to read. Only the display waits; the crawl and the agent don't."""
    time.sleep(PACE * steps)
    return PACE * steps


# ── the crawl ────────────────────────────────────────────────────────

def start_crawl(pages):
    env = dict(os.environ, HEAL_DIR=str(HEAL))
    log = open(HEAL / "crawl.log", "w")
    cmd = [sys.executable, "-m", "scrapy", "crawl", "books", "-a", f"pages={pages}", "-L", "INFO"]
    crawl = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    RUNNING.append(crawl)
    return crawl


class Items:
    """Tails the per-item progress log that the crawl writes, and prints each item."""

    def __init__(self):
        self.path, self.pos, self.n = HEAL / "items.log", 0, 0

    def pending(self):
        return self.path.exists() and self.path.stat().st_size > self.pos

    def show_new(self):
        if not self.path.exists():
            return
        with open(self.path) as f:
            f.seek(self.pos)
            for line in f:
                if not line.endswith("\n"):
                    break
                self.pos += len(line)
                self.n += 1
                item = json.loads(line)
                name = (item["name"] or "?")[:48]
                if item["missing"]:
                    say(f"  ✗ {self.n:4d}  {name:<48}  missing: {', '.join(item['missing'])}", "red")
                    hold(0.15)
                else:
                    say(f"  ✓ {self.n:4d}  {name:<48}  £{item['price']}", "dim")
                    hold(0.02)


# ── the Scrapy MCP, as the script uses it ────────────────────────────

async def _mcp(tool, args):
    params = StdioServerParameters(command=str(MCP_SERVER))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        res = await s.call_tool(tool, args)
        return "\n".join(c.text for c in res.content if hasattr(c, "text"))


def mcp(tool, **args):
    return asyncio.run(_mcp(tool, args))


def find_job(pid):
    for line in mcp("list_jobs").splitlines():
        if f"pid={pid} " in line:
            return line.split()[1]
    raise RuntimeError(f"no attachable job for crawl pid {pid}")


LOAD_FIX = '''
from web_poet import HttpResponse
from base.quality import REQUIRED, load_page_objects
fixed = load_page_objects()
for name, old in crawler.page_objects.items():  # the classes scrapy-poet really uses
    new = getattr(fixed, name, None)
    if isinstance(new, type):
        for attr, value in vars(new).items():
            if not attr.startswith("_"):
                setattr(old, attr, value)
        print("loaded", name)
page_cls = crawler.page_objects["BooksToscrapeProductPage"]
ok = 0
recent = list(crawler.recent_responses)
for r in recent:
    page = page_cls(response=HttpResponse(url=r.url, body=r.body, encoding="utf-8"))
    ok += all(getattr(page, f) not in (None, "") for f in REQUIRED)
print(f"checked on live pages: {{ok}} of {{len(recent)}} complete")
if ok == len(recent):
    s = crawler.stats
    crawler.quality_last = (s.get_value("quality/items", 0), s.get_value("quality/items_missing", 0))
    crawler.healing = False
    crawler.engine.unpause()
    print("RESUMED")
'''


# ── the agent ────────────────────────────────────────────────────────

def agent_prompt(job, tripped, feedback):
    prompt = f"""A Scrapy crawl of books.toscrape.com is running right now as job {job}. Spidermon paused it
because new items are missing fields:
  {tripped['failures'][0]}

The spider uses scrapy-poet page objects in base/pages/books_toscrape_com.py.

Use the scrapy MCP tools to attach to the live crawl and find out why the fields are missing.
The last 10 product pages are still in memory as `crawler.recent_responses`: test your fixed
selectors against them. Then fix base/pages/books_toscrape_com.py. Only edit that file.
To try the edited file on those pages, load it with
`from base.quality import load_page_objects; m = load_page_objects()`. Do not import, reload or
remove modules in the crawl: that registers the page objects a second time.

Do not pause, unpause, stop or change the running crawl, and do not send new requests.
You cannot run shell commands. When you finish, the harness runs the fixture tests
(uv run pytest tests -q) and, if they pass, loads your fixed page objects into the live crawl
and resumes it. End with two or three sentences on what was wrong and what you changed."""
    if feedback:
        prompt += f"\n\nYour previous attempt did not pass:\n{feedback}"
    return prompt


def mcp_reply(tool_name, content):
    """First line worth showing from what a Scrapy MCP tool sent back to the agent."""
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    text = str(content)
    if tool_name.endswith("execute"):
        status = text.split(None, 1)[0] if text else ""
        body = text.split("--- output ---", 1)[-1]
        if "status=error" in status:
            lines = [l for l in body.splitlines() if l.strip()]
            return "error: " + (lines[-1].strip() if lines else "")
        lines = [l.strip() for l in body.split("--- traceback ---")[0].splitlines() if l.strip()]
        return lines[0] if lines else status
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("Attachable")]
    return lines[0] if lines else ""


def describe(tool):
    name = tool["name"].replace("mcp__scrapy__", "mcp ")
    args = tool.get("input", {})
    if "code" in args:
        lines = [l for l in args["code"].splitlines() if l.strip() and not l.strip().startswith("#")]
        arg = lines[0] if lines else ""
        arg += " …" if len(lines) > 1 else ""
    else:
        arg = args.get("file_path", args.get("job_id", ""))
        arg = str(arg).replace(str(ROOT) + "/", "")
    return f"{name} {arg}"[:100]


def run_agent(prompt, n):
    mcp_config = HEAL / "mcp.json"
    mcp_config.write_text(json.dumps({"mcpServers": {"scrapy": {"command": str(MCP_SERVER)}}}))
    cmd = [CLAUDE, "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "bypassPermissions", "--tools", "Read,Edit",
           "--mcp-config", str(mcp_config), "--strict-mcp-config",
           "--settings", '{"advisorModel": ""}',  # no advisor: its calls would bill a second model
           "--allowedTools", " ".join(f"mcp__scrapy__{t}" for t in MCP_TOOLS)]
    if MODEL:
        cmd += ["--model", MODEL]
    if EFFORT:
        cmd += ["--effort", EFFORT]
    transcript = open(HEAL / f"attempt-{n}.jsonl", "w")
    start, result, held, names = time.time(), {}, 0.0, {}
    # The signed-in Claude Code login pays, never an API key that happens to be in the shell.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, text=True)
    RUNNING.append(proc)
    try:
        for line in proc.stdout:
            transcript.write(line)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "assistant":
                for block in event["message"].get("content", []):
                    if block.get("type") == "tool_use":
                        names[block["id"]] = block["name"]
                        say(f"   → {describe(block)}", "cyan")
                        held += hold(0.6)
            elif event.get("type") == "user":
                for block in event["message"].get("content", []):
                    name = names.get(block.get("tool_use_id"), "") if isinstance(block, dict) else ""
                    if name.startswith("mcp__scrapy__"):
                        say(f"       ← {mcp_reply(name, block.get('content', ''))[:90]}", "dim")
                        held += hold(0.4)
            elif event.get("type") == "result":
                result = event
            if time.time() - start > AGENT_TIMEOUT:
                break
    finally:
        if proc.poll() is None:  # timed out, or heal.py is exiting
            proc.terminate()
        proc.wait()
        RUNNING.remove(proc)
    return result, time.time() - start - held


# ── guard and gate ───────────────────────────────────────────────────

def snapshot():
    files = {}
    for entry in GUARDED:
        for p in sorted((ROOT / entry).rglob("*")) if (ROOT / entry).is_dir() else [ROOT / entry]:
            if p.is_file() and p != PAGES_FILE and "__pycache__" not in p.parts:
                files[p] = p.read_bytes()
    return files


def restore(guard):
    for p in set(snapshot()) - set(guard):
        p.unlink()
    for p, content in guard.items():
        p.write_bytes(content)


def run_tests():
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True)
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    failures = [l for l in lines if "is not correct" in l or l.startswith(("Expected", "FAILED"))]
    return proc.returncode == 0, lines[-1] if lines else "(no output)", "\n".join(failures[:12])


# ── the heal ─────────────────────────────────────────────────────────

def heal(crawl, tripped, attempts, items):
    items.show_new()  # what the crawl finished before the pause took hold
    job = find_job(crawl.pid)
    hold()
    say(f"\n✗ Spidermon: {tripped['failures'][0].split(' : ', 1)[-1]}", "red")
    hold()
    say(f"⏸  crawl paused · {books(items.n)} so far · job {job}", "yellow")
    hold(1.5)
    before = PAGES_FILE.read_text()
    (HEAL / "books_toscrape_com.before.py").write_text(before)
    guard, feedback, spent = snapshot(), "", sum(a["cost"] for a in attempts)

    while len(attempts) < MAX_ATTEMPTS and spent < BUDGET_USD:
        n = len(attempts) + 1
        say(f"\n━━ attempt {n}/{MAX_ATTEMPTS} ━━  agent attaching to the crawl through the Scrapy MCP…", "bold")
        hold()
        result, secs = run_agent(agent_prompt(job, tripped, feedback), n)
        cost = result.get("total_cost_usd", 0) or 0
        spent += cost
        attempt = {"n": n, "cost": cost, "secs": secs, "turns": result.get("num_turns", 0),
                   "models": ",".join(result.get("modelUsage", {}) or {}),
                   "said": (result.get("result") or "").strip(), "tests": "", "live": ""}
        attempts.append(attempt)

        if not result or result.get("is_error"):
            attempt["verdict"] = f"ERROR: agent run failed ({result.get('subtype', 'no result')}), not a heal failure"
        elif snapshot() != guard:
            attempt["verdict"] = "FAIL: edited a file other than the page objects, reverted"
            restore(guard)
        elif PAGES_FILE.read_text() == before:
            attempt["verdict"] = "FAIL: page objects unchanged"
        else:
            passed, summary, failures = run_tests()
            attempt["tests"] = summary
            if not passed:
                attempt["verdict"] = "FAIL: fixture tests failed"
                feedback = f"uv run pytest tests -q → {summary}\n{failures}"
            else:
                out = mcp("execute", job_id=job, code=LOAD_FIX.format())
                attempt["live"] = "\n".join(l for l in out.splitlines() if l.startswith(("loaded", "checked")))
                if "RESUMED" in out:
                    attempt["verdict"] = "PASS"
                else:
                    attempt["verdict"] = "FAIL: fixed page objects still incomplete on live pages"
                    feedback = attempt["live"]

        verdict = attempt["verdict"]
        attempt["diff"] = page_diff(before)
        if verdict != "PASS":
            PAGES_FILE.write_text(before)  # the next attempt, or a human, starts from the original
        color = "green" if verdict == "PASS" else "red"
        say(f"   attempt {n}  {verdict}  ·  ${cost:.2f}  ·  {secs:.0f}s  ·  {attempt['turns']} turns  "
            f"·  spent ${spent:.2f} of ${BUDGET_USD:.2f}", color)
        if attempt["tests"]:
            say(f"   fixture tests: {attempt['tests']}", "dim")
        if verdict == "PASS":
            hold()
            say(f"   {attempt['live'].replace(chr(10), chr(10) + '   ')}", "dim")
            hold()
            say("\n   agent: " + attempt["said"].replace("\n", "\n   "), "cyan")
            hold(2)
            say("   " + attempt["diff"].replace("\n", "\n   "))
            hold(2)
            if items.pending():
                say("   already downloading when the crawl paused, so scraped with the old selector:", "dim")
                items.show_new()
            say("▶  crawl resumed with the fix, no restart", "green")
            hold(1.5)
            return True
    return False


def page_diff(before):
    return "".join(difflib.unified_diff(before.splitlines(True), PAGES_FILE.read_text().splitlines(True),
                                        "books_toscrape_com.py (before)", "books_toscrape_com.py (after)"))


# ── reporting ────────────────────────────────────────────────────────

def feed_summary():
    rows = [json.loads(l) for l in FEED.read_text().splitlines()] if FEED.exists() else []
    broken = [i for i, r in enumerate(rows) if not r.get("price") or not r.get("name") or not r.get("availability")]
    return rows, broken


def write_report(attempts, healed, elapsed, tripped):
    rows, broken = feed_summary()
    spent = sum(a["cost"] for a in attempts)
    title = "# Heal report" if healed else "# Escalation: the crawl could not be healed"
    lines = [title, "",
             f"Crawl: {len(rows)} items in books.jsonl, {len(rows) - len(broken)} complete, "
             f"{len(broken)} missing fields · {elapsed:.0f}s total", ""]
    if tripped:
        lines += [f"Spidermon tripped: `{tripped['failures'][0]}`", ""]
    lines += ["## Attempts", "", "| attempt | verdict | cost | time | turns | model |", "|---|---|---|---|---|---|"]
    for a in attempts:
        lines.append(f"| {a['n']} | {a['verdict']} | ${a['cost']:.2f} | {a['secs']:.0f}s | {a['turns']} | {a['models']} |")
    lines += ["", f"Total: ${spent:.2f} · {'healed' if healed else 'NOT healed'}", ""]
    for a in attempts:
        lines += [f"## Attempt {a['n']}: what the agent said", "", a["said"] or "(nothing)", ""]
        if a["tests"]:
            lines += [f"Fixture tests: `{a['tests']}`", ""]
        if a["live"]:
            lines += ["Live crawl: " + a["live"].replace("\n", " · "), ""]
        lines += [f"Attempt {a['n']}'s change to the page objects:", "", "```diff", a.get("diff") or "(none)", "```", ""]
    lines += ["Transcripts: `.heal/attempt-*.jsonl` · crawl log: `.heal/crawl.log`", ""]
    (ESCALATION if not healed else REPORT).write_text("\n".join(lines))
    if not healed:
        shutil.copy(ESCALATION, REPORT)


def main():
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    shutil.rmtree(HEAL, ignore_errors=True)
    HEAL.mkdir()
    for p in (FEED, REPORT, ESCALATION):
        p.unlink(missing_ok=True)

    if os.environ.get("HEAL_ENABLED", "1") != "1":
        say(f"▶ crawling books.toscrape.com, {pages} catalogue pages · no healing: a broken selector is scraped as it is", "bold")
    else:
        say(f"▶ crawling books.toscrape.com, {pages} catalogue pages · Spidermon checks new items twice a second", "bold")
        say(f"▶ agent: model {MODEL or 'default'} · effort {EFFORT or 'default'} · "
            f"{MAX_ATTEMPTS} attempts · budget ${BUDGET_USD:.2f}\n", "dim")
    started, items, attempts, healed, tripped = time.time(), Items(), [], None, None
    crawl = start_crawl(pages)
    trip_file = HEAL / "TRIPPED.json"

    while crawl.poll() is None:
        items.show_new()
        if trip_file.exists():
            tripped = json.loads(trip_file.read_text())
            trip_file.rename(HEAL / f"tripped-{len(attempts)}.json")
            if len(attempts) >= MAX_ATTEMPTS:
                healed = False
                break
            ok = heal(crawl, tripped, attempts, items)
            if not ok:
                healed = False
                break
            healed = True
        time.sleep(0.1)

    if healed is False:
        say("\n✗ not healed: stopping the crawl, a human gets ESCALATION.md", "red")
        crawl.send_signal(signal.SIGTERM)
    crawl.wait()
    items.show_new()
    elapsed = time.time() - started
    rows, broken = feed_summary()

    say("")
    if tripped is None:
        if crawl.returncode != 0 or not rows or broken:
            say(f"✗ the crawl did not finish cleanly: exit {crawl.returncode}, {books(len(rows))}, "
                f"{len(broken)} missing fields · see .heal/crawl.log", "red")
            say("   " + "\n   ".join((HEAL / "crawl.log").read_text().splitlines()[-5:]), "dim")
            return 1
        say(f"✓ perfect run: {books(len(rows))}, all complete · {elapsed:.0f}s → books.jsonl", "green")
        return 0
    write_report(attempts, healed, elapsed, tripped)
    spent = sum(a["cost"] for a in attempts)
    if healed:
        say(f"✓ HEALED mid-crawl on attempt {len(attempts)} of {MAX_ATTEMPTS} · ${spent:.2f} · "
            f"{books(len(rows))}, {len(rows) - len(broken)} complete, {len(broken)} broken before the fix · "
            f"{elapsed:.0f}s → books.jsonl, HEAL_REPORT.md", "green")
        return 0
    say(f"✗ ESCALATED after {len(attempts)} attempts · ${spent:.2f} · {books(len(rows))} written before the stop, "
        f"{len(rows) - len(broken)} complete → ESCALATION.md", "red")
    return 1


def stop_children(*_):
    for proc in RUNNING:
        if proc.poll() is None:
            proc.terminate()
    for proc in RUNNING:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    signal.signal(signal.SIGINT, signal.default_int_handler)  # even if started with SIGINT ignored
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\n✗ interrupted: stopping the crawl and the agent", "red")
        sys.exit(130)
    finally:
        stop_children()
