"""Demo-only product catalog and mock-agent selection helpers."""

import re

import currency

# These are fictional demo products and prices, not live listings or currency conversions.
PRODUCTS = (
    {
        "id": "usb-c-cable",
        "name": "Braided USB-C Cable",
        "merchant": "Demo Accessories Shop",
        "category": "accessories",
        "price_usd": 6.99,
        "price_inr": 49,
        "image": "/static/images/usb-c-cable.svg",
    },
    {
        "id": "phone-case",
        "name": "Clear Protective Phone Case",
        "merchant": "Flipkart",
        "category": "accessories",
        "price_usd": 8.49,
        "price_inr": 399,
        "image": "/static/images/phone-case.svg",
    },
    {
        "id": "desk-organizer",
        "name": "Compact Desk Organizer",
        "merchant": "Demo Accessories Shop",
        "category": "accessories",
        "price_usd": 14.99,
        "price_inr": 799,
        "image": "/static/images/desk-organizer.svg",
    },
    {
        "id": "wireless-mouse",
        "name": "Wireless Travel Mouse",
        "merchant": "Flipkart",
        "category": "accessories",
        "price_usd": 19.99,
        "price_inr": 1199,
        "image": "/static/images/wireless-mouse.svg",
    },
    {
        "id": "bluetooth-speaker",
        "name": "Portable Bluetooth Speaker",
        "merchant": "Demo Accessories Shop",
        "category": "electronics",
        "price_usd": 39.99,
        "price_inr": 2999,
        "image": "/static/images/bluetooth-speaker.svg",
    },
    {
        "id": "smart-monitor",
        "name": "27-inch Smart Monitor",
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
    category = "electronics" if rogue else requested_category(request)
    candidates = [
        product for product in PRODUCTS if product["category"] == category
    ]
    if rogue:
        product = max(candidates, key=lambda item: item["price_usd"])
    else:
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
