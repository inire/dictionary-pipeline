"""Contract layer tests — validates the YAML <-> pandera bridge end-to-end."""

from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import pytest

from dictionary_pipeline.contract import (
    apply_derivations,
    build_pandera_schema,
    load_contract,
    rename_to_contract,
)

EXAMPLES = Path(__file__).parent.parent / "examples" / "doordash"


def test_load_contract_doordash():
    c = load_contract(EXAMPLES / "dictionary.yaml")
    assert c.dataset_name == "doordash_2026_purchased_items"
    assert len(c.fields) == 13
    assert len(c.derived_fields) == 3
    assert c.pii is True
    assert "delivery_address" in c.pii_fields


def test_source_to_field_map():
    c = load_contract(EXAMPLES / "dictionary.yaml")
    m = c.source_to_field_map()
    assert m["Order Status"] == "order_status"
    assert m["Payment Methods"] == "payment_method"  # plural -> singular rename


def test_build_pandera_schema():
    c = load_contract(EXAMPLES / "dictionary.yaml")
    schema = build_pandera_schema(c)
    assert isinstance(schema, pa.DataFrameSchema)
    assert "order_status" in schema.columns
    assert "currency" in schema.columns


def test_schema_validates_synthetic_dataframe():
    c = load_contract(EXAMPLES / "dictionary.yaml")
    schema = build_pandera_schema(c)
    df = pd.DataFrame([{
        "order_status": "Delivered",
        "order_date": pd.Timestamp("2026-01-15"),
        "order_id": "deb50d86-21ac-4101-a76b-749f663efa82",
        "payment_method": "Visa 4122",
        "product_description": "Test item",
        "product_quantity": 1,
        "store_name": "Test Store",
        "product_type": "Test",
        "product_price": 9.99,
        "currency": "USD",
        "invoice_url": "https://www.doordash.com/orders/deb50d86-21ac-4101-a76b-749f663efa82",
        "delivery_address": "Anywhere",
        "product_image": None,
    }])
    validated = schema.validate(df)
    assert len(validated) == 1


def test_schema_rejects_bad_categorical():
    c = load_contract(EXAMPLES / "dictionary.yaml")
    schema = build_pandera_schema(c)
    df = pd.DataFrame([{
        "order_status": "Refunded",  # not in allowed_values
        "order_date": pd.Timestamp("2026-01-15"),
        "order_id": "deb50d86-21ac-4101-a76b-749f663efa82",
        "payment_method": "Visa 4122",
        "product_description": "x",
        "product_quantity": 1,
        "store_name": "x",
        "product_type": "x",
        "product_price": 1.0,
        "currency": "USD",
        "invoice_url": "https://www.doordash.com/orders/deb50d86-21ac-4101-a76b-749f663efa82",
        "delivery_address": "x",
        "product_image": None,
    }])
    with pytest.raises(pa.errors.SchemaError):
        schema.validate(df)


def test_derivations_compute_correctly():
    c = load_contract(EXAMPLES / "dictionary.yaml")
    df = pd.DataFrame([
        {"order_id": "A", "product_price": 10.0, "product_quantity": 2},
        {"order_id": "A", "product_price": 5.0, "product_quantity": 1},
        {"order_id": "B", "product_price": 20.0, "product_quantity": 4},
    ])
    out = apply_derivations(df, c)
    # unit_price
    assert out.loc[0, "unit_price"] == 5.0
    assert out.loc[1, "unit_price"] == 5.0
    assert out.loc[2, "unit_price"] == 5.0
    # order_item_count (per order_id)
    assert out.loc[0, "order_item_count"] == 2
    assert out.loc[2, "order_item_count"] == 1
    # order_total
    assert out.loc[0, "order_total"] == 15.0
    assert out.loc[2, "order_total"] == 20.0


def test_rename_preserves_unmapped_columns():
    c = load_contract(EXAMPLES / "dictionary.yaml")
    df = pd.DataFrame([{"Order Status": "Delivered", "ExtraColumn": "x"}])
    out = rename_to_contract(df, c)
    assert "order_status" in out.columns
    assert "ExtraColumn" in out.columns  # unmapped columns survive
