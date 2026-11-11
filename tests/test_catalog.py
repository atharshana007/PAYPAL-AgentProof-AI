from datetime import datetime, timezone
from pathlib import Path

import pytest

import catalog
import mandate
import seed_demo


def test_catalog_contains_seven_fictional_demo_products():
    assert len(catalog.PRODUCTS) == 7
    assert all(
        {
            "id",
            "name",
            "keywords",
            "is_demo",
            "merchant",
            "category",
            "price_usd",
            "image",
        }
        <= product.keys()
        for product in catalog.PRODUCTS
    )
    assert all(product["is_demo"] for product in catalog.PRODUCTS)
    assert all(
        keyword == keyword.lower()
        for product in catalog.PRODUCTS
        for keyword in product["keywords"]
    )
    assert {product["merchant"] for product in catalog.PRODUCTS} == {
        "Flipkart",
        "Demo Accessories Shop",
    }
    assert {product["category"] for product in catalog.PRODUCTS} == {
        "accessories",
        "electronics",
    }
    assert any(
        product["category"] == "electronics" and product["price_usd"] > 50
        for product in catalog.PRODUCTS
    )
    mobile_case = next(
        product for product in catalog.PRODUCTS if product["id"] == "mobile-phone-case"
    )
    assert mobile_case["name"] == "Mobile Phone Case"
    assert mobile_case["merchant"] == "Demo Accessories Shop"
    assert mobile_case["category"] == "accessories"
    assert mobile_case["price_usd"] == 12.99
    assert mobile_case["keywords"] == ["mobile", "phone", "case", "cover"]


def test_normal_mock_selects_request_match_or_cheapest_category_fallback():
    assert catalog.select_product("Buy accessories")["id"] == "usb-c-cable"
    assert catalog.select_product("Buy a phone")["id"] == "mobile-phone-case"
    assert catalog.select_product("Find something")["id"] == "usb-c-cable"


@pytest.mark.parametrize(
    ("request_text", "expected_id"),
    [
        ("mobile case", "mobile-phone-case"),
        ("phone cover", "mobile-phone-case"),
        ("usb cable", "usb-c-cable"),
    ],
)
def test_mock_selects_product_by_request_words(request_text, expected_id):
    assert catalog.select_product(request_text)["id"] == expected_id


def test_mock_uses_cheapest_item_when_matching_scores_tie(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "PRODUCTS",
        (
            {
                "id": "more-expensive",
                "name": "Demo Cable",
                "keywords": ["cable"],
                "price_usd": 12,
                "category": "accessories",
            },
            {
                "id": "cheaper",
                "name": "Demo Cable",
                "keywords": ["cable"],
                "price_usd": 6,
                "category": "accessories",
            },
        ),
    )

    assert catalog.select_product("cable")["id"] == "cheaper"


def test_rogue_mock_selects_expensive_electronics_item():
    product = catalog.select_product("Buy accessories", rogue=True)

    assert product["id"] == "smart-monitor"
    assert product["category"] == "electronics"
    assert product["price_usd"] > 50


def test_each_catalog_image_is_served_from_static_directory():
    static_root = Path(__file__).resolve().parents[1] / "static"

    for product in catalog.PRODUCTS:
        image_path = static_root / product["image"].removeprefix("/static/")
        assert image_path.is_file()
        assert image_path.read_text(encoding="utf-8").lstrip().startswith("<svg")


def test_mock_product_uses_direct_demo_price_for_currency():
    product = catalog.select_product("accessories")

    assert catalog.price_for_currency(product, "USD") == product["price_usd"]
    assert catalog.price_for_currency(product, "INR") == product["price_inr"]
    assert catalog.price_for_currency(product, "USD") != catalog.price_for_currency(
        product, "INR"
    )


def test_seed_demo_allows_both_catalog_merchants_and_seven_day_mandate(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "seed-demo.db"))
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    monkeypatch.setattr("builtins.input", lambda prompt: "RESET")

    assert seed_demo.main() == 0

    saved = mandate.get_current()
    assert saved["mandate"]["allowed_merchants"] == [
        "Demo Accessories Shop",
        "Flipkart",
    ]
    expiry = datetime.fromisoformat(saved["mandate"]["expires_at"])
    assert (expiry - datetime.now(timezone.utc)).total_seconds() >= 6 * 24 * 60 * 60
