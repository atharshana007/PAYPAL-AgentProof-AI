from datetime import datetime, timezone
from pathlib import Path

import catalog
import mandate
import seed_demo


def test_catalog_contains_six_fictional_demo_products():
    assert len(catalog.PRODUCTS) == 6
    assert all(
        {"id", "name", "merchant", "category", "price_usd", "image"} <= product.keys()
        for product in catalog.PRODUCTS
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


def test_normal_mock_selects_cheapest_matching_category():
    assert catalog.select_product("Buy accessories")["id"] == "usb-c-cable"
    assert catalog.select_product("Buy a phone")["id"] == "bluetooth-speaker"
    assert catalog.select_product("Find something")["category"] == "accessories"


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
