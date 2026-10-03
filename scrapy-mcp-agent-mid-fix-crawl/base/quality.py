"""Data quality while the crawl runs: count missing fields, and pause the crawl for healing."""

import json
import os
import time
import types
from collections import deque

from scrapy import signals
from scrapy_beep.extension import BeepExtension
from spidermon import Monitor, MonitorSuite, monitors
from spidermon.core.actions import Action

REQUIRED = ["name", "price", "availability"]
HEAL_DIR = os.environ.get("HEAL_DIR", ".heal")
PAGES_FILE = os.path.join(os.path.dirname(__file__), "pages", "books_toscrape_com.py")


def load_page_objects(path=PAGES_FILE):
    """Load the page objects file as it is on disk now, without registering its URL rules again."""
    import web_poet

    real = web_poet.handle_urls
    web_poet.handle_urls = lambda *a, **k: (lambda cls: cls)
    try:
        module = types.ModuleType("page_objects_on_disk")
        exec(compile(open(path).read(), path, "exec"), module.__dict__)
    finally:
        web_poet.handle_urls = real
    return module


class QualityBeep(BeepExtension):
    """The plugin judges a crawl by item count and ERROR lines: empty rows get the fanfare, and Spidermon's
    own failure report (an ERROR line) makes a healed crawl sound like a failure. Here the last item decides:
    still broken at the end is a failure, healed halfway is not."""

    def spider_closed(self, spider, reason):
        last_ok = spider.crawler.stats.get_value("quality/last_item_ok")
        if last_ok is None:
            return super().spider_closed(spider, reason)
        ok = last_ok and reason == "finished"
        spider.logger.info("QualityBeep: reason=%s, last item %s → %s", reason,
                           "complete" if last_ok else "missing fields", "SUCCESS" if ok else "FAILURE")
        self._play(self.success_sound if ok else self.failure_sound)


class TrackMissing:
    """Keeps every item (broken ones too) and writes a one-line progress record per item."""

    def __init__(self, crawler):
        self.crawler = crawler
        os.makedirs(HEAL_DIR, exist_ok=True)
        self.progress = open(os.path.join(HEAL_DIR, "items.log"), "w", buffering=1)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_item(self, item):
        stats = self.crawler.stats
        missing = [f for f in REQUIRED if getattr(item, f, None) in (None, "")]
        stats.inc_value("quality/items")
        stats.set_value("quality/last_item_ok", not missing)
        if missing:
            stats.inc_value("quality/items_missing")
            for f in missing:
                stats.inc_value(f"quality/missing/{f}")
        record = {"name": item.name, "price": item.price, "missing": missing, "url": item.url}
        self.progress.write(json.dumps(record) + "\n")
        return item


class CrawlHandles:
    """What an agent needs to inspect and heal the live crawl, kept on the crawler.

    crawler.recent_responses: the last few product pages, still in memory.
    crawler.page_objects: the page object classes scrapy-poet uses, captured at start, so a fix
    lands on those even if a module is re-imported later.
    """

    def __init__(self, crawler):
        crawler.recent_responses = deque(maxlen=10)
        crawler.page_objects = {}
        crawler.signals.connect(self.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(self.response_received, signal=signals.response_received)
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def spider_opened(self, spider):
        from web_poet import default_registry

        for rule in default_registry.get_rules():  # the first rule for a pattern is the one used
            self.crawler.page_objects.setdefault(rule.use.__name__, rule.use)

    def response_received(self, response, request, spider):
        if "/catalogue/" in response.url and "/page-" not in response.url:
            self.crawler.recent_responses.append(response)


@monitors.name("Items since the last check")
class LiveQuality(Monitor):
    @monitors.name("no new item is missing a required field")
    def test_new_items_complete(self):
        crawler, stats = self.data.crawler, self.data.stats
        if getattr(crawler, "healing", False):
            return  # a heal is in progress, the harness resumes the checks
        items, bad = stats.get("quality/items", 0), stats.get("quality/items_missing", 0)
        last_items, last_bad = getattr(crawler, "quality_last", (0, 0))
        crawler.quality_last = (items, bad)
        new_bad = bad - last_bad
        missing = {f: stats.get(f"quality/missing/{f}", 0) for f in REQUIRED}
        self.assertEqual(
            new_bad, 0,
            f"{new_bad} of {items - last_items} new items missing fields "
            f"(so far: {', '.join(f'{f} {n}' for f, n in missing.items() if n)})",
        )


class PauseForHealing(Action):
    def run_action(self):
        crawler = self.data.crawler
        crawler.healing = True
        crawler.engine.pause()
        stats = crawler.stats
        report = {
            "tripped_at": time.time(),
            "pid": os.getpid(),
            "items": stats.get_value("quality/items", 0),
            "items_missing": stats.get_value("quality/items_missing", 0),
            "missing": {f: stats.get_value(f"quality/missing/{f}", 0) for f in REQUIRED},
            "failures": [str(f[1]).strip().splitlines()[-1] for f in self.result.failures],
        }
        path = os.path.join(HEAL_DIR, "TRIPPED.json")
        with open(path + ".tmp", "w") as f:
            json.dump(report, f)
        os.replace(path + ".tmp", path)  # heal.py polls for this file: never let it read half of it


class Tripwire(MonitorSuite):
    monitors = [LiveQuality]
    monitors_failed_actions = [PauseForHealing]
