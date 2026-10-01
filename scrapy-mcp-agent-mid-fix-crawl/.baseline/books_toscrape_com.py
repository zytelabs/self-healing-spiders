from typing import List, Optional

from web_poet import Returns, WebPage, field, handle_urls

from base.items import Product, ProductList


@handle_urls("books.toscrape.com/catalogue/page-")
class BooksToscrapeProductListPage(WebPage, Returns[ProductList]):
    @field
    def url(self) -> str:
        return str(self.response.url)

    @field
    def product_urls(self) -> Optional[List[str]]:
        hrefs = self.css("article.product_pod h3 a::attr(href)").getall()
        return [self.urljoin(h) for h in hrefs] or None

    @field
    def next_page_url(self) -> Optional[str]:
        href = self.css("li.next a::attr(href)").get()
        return self.urljoin(href) if href else None


@handle_urls("books.toscrape.com/catalogue/")
class BooksToscrapeProductPage(WebPage, Returns[Product]):
    @field
    def url(self) -> str:
        return str(self.response.url)

    @field
    def name(self) -> Optional[str]:
        return self.css("div.product_main h1::text").get()

    @field
    def price(self) -> Optional[str]:
        raw = self.css("div.product_main p.price_color::text").get()
        return raw.lstrip("£") if raw else None

    @field
    def currency(self) -> Optional[str]:
        return "GBP" if self.currency_raw == "£" else None

    @field
    def currency_raw(self) -> Optional[str]:
        raw = self.css("div.product_main p.price_color::text").get()
        return raw[0] if raw else None

    @field
    def availability(self) -> Optional[str]:
        text = " ".join(self.css("div.product_main p.availability::text").getall())
        if "In stock" in text:
            return "InStock"
        return "OutOfStock" if text.strip() else None
