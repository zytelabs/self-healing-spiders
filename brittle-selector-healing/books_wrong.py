"""A plausible but WRONG repair for v2, kept for the silent-corruption beat.

It takes the first price in each card, which is the struck-through old price.
Run: uv run scrapy runspider books_wrong.py -O wrong.json && uv run python check.py wrong.json
"""

from pathlib import Path

import scrapy

SITE = Path(__file__).parent / "site"


class BooksWrongSpider(scrapy.Spider):
    name = "books-wrong"
    start_urls = [(SITE / "v2.html").resolve().as_uri()]

    def parse(self, response):
        for book in response.css("article.book-card"):
            stock = book.css("span.book-card__stock::attr(data-stock)").get()
            yield {
                "title": book.css("h2.book-card__name::text").get(),
                "price": float(
                    book.css(".price::text").get().strip("£")
                ),
                "availability": "In stock" if stock == "in" else "Out of stock",
            }
