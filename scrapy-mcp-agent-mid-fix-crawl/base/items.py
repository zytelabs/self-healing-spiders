from typing import List, Optional

import attrs


@attrs.define
class Product:
    url: str
    name: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = None
    currency_raw: Optional[str] = None
    availability: Optional[str] = None


@attrs.define
class ProductList:
    url: str
    product_urls: Optional[List[str]] = None
    next_page_url: Optional[str] = None
