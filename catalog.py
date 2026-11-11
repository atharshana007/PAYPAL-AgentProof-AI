"""Demo-only product catalog and mock-agent selection helpers."""

import re

import currency

# These are fictional demo products and prices, not live listings or currency conversions.
PRODUCTS = (
    {
        "id": "usb-c-cable",
        "name": "Braided USB-C Cable",
        "keywords": ["braided", "usb", "cable", "charging"],
        "is_demo": True,
        "merchant": "Demo Accessories Shop",
        "category": "accessories",
        "price_usd": 6.99,
        "price_inr": 49,
        "image": "/static/images/usb-c-cable.svg",
    },
    {
        "id": "phone-case",
        "name": "Clear Protective Phone Case",
        "keywords": ["clear", "protective", "phone", "case"],
        "is_demo": True,
        "merchant": "Flipkart",
        "category": "accessories",
        "price_usd": 8.49,
        "price_inr": 399,
        "image": "/static/images/phone-case.svg",
    },
    {
        "id": "mobile-phone-case",
        "name": "Mobile Phone Case",
        "keywords": ["mobile", "phone", "case", "cover"],
        "is_demo": True,
        "merchant": "Demo Accessories Shop",
        "category": "accessories",
        "price_usd": 12.99,
        "price_inr": 999,
        "image": "/static/images/phone-case.svg",
    },
    {
        "id": "desk-organizer",
        "name": "Compact Desk Organizer",
        "keywords": ["compact", "desk", "organizer", "storage"],
        "is_demo": True,
        "merchant": "Demo Accessories Shop",
        "category": "accessories",
        "price_usd": 14.99,
        "price_inr": 799,
        "image": "/static/images/desk-organizer.svg",
    },
    {
        "id": "wireless-mouse",
        "name": "Wireless Travel Mouse",
        "keywords": ["wireless", "travel", "mouse", "computer"],
        "is_demo": True,
        "merchant": "Flipkart",
        "category": "accessories",
        "price_usd": 19.99,
        "price_inr": 1199,
        "image": "/static/images/wireless-mouse.svg",
    },
    {
        "id": "bluetooth-speaker",
        "name": "Portable Bluetooth Speaker",
        "keywords": ["portable", "bluetooth", "speaker", "audio"],
        "is_demo": True,
        "merchant": "Demo Accessories Shop",
        "category": "electronics",
        "price_usd": 39.99,
        "price_inr": 2999,
        "image": "/static/images/bluetooth-speaker.svg",
    },
    {
        "id": "smart-monitor",
        "name": "27-inch Smart Monitor",
        "keywords": ["smart", "monitor", "display"],
        "is_demo": True,
        "merchant": "Flipkart",
        "category": "electronics",
        "price_usd": 129.99,
        "price_inr": 9999,
        "image": "/static/images/smart-monitor.svg",
    },
)

GENERIC_PRODUCT_IMAGE = "/static/images/demo-product.svg"
_PRODUCTS_BY_ID = {product["id"]: product for product in PRODUCTS}
_PRODUCTS_BY_NAME = {product["name"].casefold(): product for product in PRODUCTS}
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_WORD_EQUIVALENTS = {"phone": "mobile", "cover": "case"}


def _normalized_words(text):
    return tuple(
        _WORD_EQUIVALENTS.get(word, word)
        for word in _WORD_PATTERN.findall(text.casefold())
    )


def product_match(request, product):
    """Return shared-word occurrence score and unique normalized matched words."""
    request_words = set(_normalized_words(request))
    product_words = _normalized_words(product["name"]) + tuple(
        word
        for keyword in product["keywords"]
        for word in _normalized_words(keyword)
    )
    matched_words = tuple(sorted(request_words.intersection(product_words)))
    score = sum(word in request_words for word in product_words)
    return score, matched_words


def requested_category(request):
    text = request.casefold()
    if re.search(r"\b(electronics?|phones?|laptops?|monitors?|speakers?)\b", text):
        return "electronics"
    if re.search(
        r"\b(accessor(?:y|ies)|cases?|cables?|chargers?|mice|mouse|organizers?)\b",
        text,
    ):
        return "accessories"
    return "accessories"


def select_product(request, rogue=False):
    if rogue:
        candidates = [
            product for product in PRODUCTS if product["category"] == "electronics"
        ]
        product = max(candidates, key=lambda item: item["price_usd"])
        return dict(product)

    scored = [(product_match(request, product)[0], product) for product in PRODUCTS]
    best_score = max(score for score, _ in scored)
    if best_score:
        product = min(
            (product for score, product in scored if score == best_score),
            key=lambda item: item["price_usd"],
        )
    else:
        category = requested_category(request)
        candidates = [
            product for product in PRODUCTS if product["category"] == category
        ]
        product = min(candidates, key=lambda item: item["price_usd"])
    return dict(product)


def price_for_currency(product, currency_code):
    currency.validate_currency(currency_code)
    price_field = "price_usd" if currency_code == "USD" else "price_inr"
    return product[price_field]


def describe_purchase(purchase, currency_code):
    """Provide safe, display-ready catalog metadata for any agent proposal."""
    product = None
    product_id = purchase.get("product_id")
    if isinstance(product_id, str):
        product = _PRODUCTS_BY_ID.get(product_id)
    item = purchase.get("item")
    if product is None and isinstance(item, str):
        product = _PRODUCTS_BY_NAME.get(item.casefold())

    product_name = product["name"] if product else (
        item if isinstance(item, str) and item.strip() else "Demo product"
    )
    product_image = product["image"] if product else GENERIC_PRODUCT_IMAGE
    price = purchase.get("amount")
    return {
        "product_name": product_name,
        "product_image": product_image,
        "price": price,
        "currency": currency_code,
    }
