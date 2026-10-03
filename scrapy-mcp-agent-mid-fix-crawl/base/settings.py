import os
BOT_NAME = "base"
SPIDER_MODULES = ["base.spiders"]
NEWSPIDER_MODULE = "base.spiders"
ROBOTSTXT_OBEY = True

ADDONS = {"scrapy_poet.Addon": 300}
SCRAPY_POET_DISCOVER = ["base.pages"]
SCRAPY_POET_TESTS_DIR = "tests/fixtures"

# Fast for the stage: books.toscrape.com is a sandbox built for scraping practice.
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 8
DOWNLOAD_DELAY = 0
AUTOTHROTTLE_ENABLED = False
TELNETCONSOLE_ENABLED = False

FEEDS = {"books.jsonl": {"format": "jsonlines", "overwrite": True}}
FEED_EXPORT_ENCODING = "utf-8"

ITEM_PIPELINES = {"base.quality.TrackMissing": 100}
EXTENSIONS = {
    "spidermon.contrib.scrapy.extensions.Spidermon": 500,
    "base.quality.CrawlHandles": 510,
    # fanfare on a clean finish, trombone on a failure. Not via its Addon: that sets EXTENSIONS at a lower
    # priority than this project dict, so it would never load.
    "base.quality.QualityBeep": 520,
}
SPIDERMON_ENABLED = True
# No tripwire, nothing pauses the crawl and no agent is started (make run); make run-with-heal sets HEAL_ENABLED=1
SPIDERMON_PERIODIC_MONITORS = {"base.quality.Tripwire": 0.5} if os.environ.get("HEAL_ENABLED", "1") == "1" else {}
