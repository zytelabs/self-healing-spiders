import scrapy

from base.items import Product, ProductList


class BooksSpider(scrapy.Spider):
    name = "books"
    allowed_domains = ["books.toscrape.com"]
    urls = ["https://books.toscrape.com/catalogue/page-1.html"]

    def __init__(self, pages=10, **kwargs):
        super().__init__(**kwargs)
        self.max_pages = int(pages)

    async def start(self):
        for url in self.urls:
            yield scrapy.Request(url, callback=self.parse)

    async def parse(self, response, product_list: ProductList):
        for url in product_list.product_urls or []:
            yield response.follow(url, callback=self.parse_product)
        page = int(response.url.split("page-")[1].split(".")[0])
        if product_list.next_page_url and page < self.max_pages:
            yield response.follow(product_list.next_page_url, callback=self.parse)

    async def parse_product(self, _, product: Product):
        yield product
