"""Scrape the bookshop. Run: uv run scrapy runspider books.py -a site=v1 -O out.json"""

from pathlib import Path

import scrapy

SITE = Path(__file__).parent / "site"


class BooksSpider(scrapy.Spider):
    name = "books"

    def __init__(self, site="v1", **kwargs):
        super().__init__(**kwargs)
        self.start_urls = [(SITE / f"{site}.html").resolve().as_uri()]

    def parse(self, response):
        for book in response.css("article.product_pod"):
            price = book.css("p.price_color::text").get()
            yield {
                "title": book.css("h3.title::text").get(),
                "price": float(price.strip("£")) if price else None,
                "availability": book.css("p.availability::text").get(),
            }
