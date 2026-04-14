"""Contract layer tests — validates the YAML <-> pandera bridge end-to-end."""

from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import pytest

from dictionary_pipeline.contract import (
    Contract,
    DerivedFieldSpec,
    apply_derivations,
    build_pandera_schema,
    load_contract,
    rename_to_contract,
)

EXAMPLES = Path(__file__).parent.parent / "examples" / "doordash"
INSTACART = Path(__file__).parent.parent / "examples" / "instacart"


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


def test_derivation_field_agnostic_division():
    """Division pattern should work with ANY two field names, not just product_price/product_quantity."""

    contract = Contract(
        dataset_name="test", description="", source="", grain="",
        pii=False, pii_fields=[], naming_convention="snake_case",
        last_updated="2026-01-01",
        fields=[],
        derived_fields=[
            DerivedFieldSpec(
                name="unit_paid",
                label="test",
                type="decimal",
                dtype="float64",
                transformation="price_paid_before_tax / product_quantity",
            ),
        ],
    )
    df = pd.DataFrame([
        {"price_paid_before_tax": 9.0, "product_quantity": 2},
        {"price_paid_before_tax": 4.5, "product_quantity": 1},
    ])
    out = apply_derivations(df, contract)
    assert out.loc[0, "unit_paid"] == 4.5
    assert out.loc[1, "unit_paid"] == 4.5


def test_derivation_field_agnostic_groupby_sum():
    """Groupby sum should work with ANY key and ANY value field."""

    contract = Contract(
        dataset_name="test", description="", source="", grain="",
        pii=False, pii_fields=[], naming_convention="snake_case",
        last_updated="2026-01-01",
        fields=[],
        derived_fields=[
            DerivedFieldSpec(
                name="order_total_paid",
                label="test",
                type="decimal",
                dtype="float64",
                transformation="groupby(order_id).price_paid_before_tax.sum()",
            ),
        ],
    )
    df = pd.DataFrame([
        {"order_id": "A", "price_paid_before_tax": 9.0},
        {"order_id": "A", "price_paid_before_tax": 4.5},
        {"order_id": "B", "price_paid_before_tax": 20.0},
    ])
    out = apply_derivations(df, contract)
    assert out.loc[0, "order_total_paid"] == 13.5
    assert out.loc[1, "order_total_paid"] == 13.5
    assert out.loc[2, "order_total_paid"] == 20.0


def test_derivation_subtraction():
    """Subtraction pattern: field_a - field_b."""

    contract = Contract(
        dataset_name="test", description="", source="", grain="",
        pii=False, pii_fields=[], naming_convention="snake_case",
        last_updated="2026-01-01",
        fields=[],
        derived_fields=[
            DerivedFieldSpec(
                name="discount",
                label="test",
                type="decimal",
                dtype="float64",
                transformation="product_price - price_paid_before_tax",
            ),
        ],
    )
    df = pd.DataFrame([
        {"product_price": 10.0, "price_paid_before_tax": 9.0},
        {"product_price": 5.0, "price_paid_before_tax": 5.0},
    ])
    out = apply_derivations(df, contract)
    assert out.loc[0, "discount"] == 1.0
    assert out.loc[1, "discount"] == 0.0


def test_derivation_missing_column_raises():
    """Referencing a column not in the DataFrame should raise KeyError, not a confusing pandas error."""

    contract = Contract(
        dataset_name="test", description="", source="", grain="",
        pii=False, pii_fields=[], naming_convention="snake_case",
        last_updated="2026-01-01",
        fields=[],
        derived_fields=[
            DerivedFieldSpec(
                name="bad",
                label="test",
                type="decimal",
                dtype="float64",
                transformation="nonexistent_col / product_quantity",
            ),
        ],
    )
    df = pd.DataFrame([{"product_quantity": 2}])
    with pytest.raises(KeyError, match="nonexistent_col"):
        apply_derivations(df, contract)


def test_derivation_unrecognized_pattern_raises():
    """Patterns that don't match any regex should still raise NotImplementedError."""

    contract = Contract(
        dataset_name="test", description="", source="", grain="",
        pii=False, pii_fields=[], naming_convention="snake_case",
        last_updated="2026-01-01",
        fields=[],
        derived_fields=[
            DerivedFieldSpec(
                name="bad",
                label="test",
                type="decimal",
                dtype="float64",
                transformation="MAGIC(field_a, field_b)",
            ),
        ],
    )
    df = pd.DataFrame([{"field_a": 1, "field_b": 2}])
    with pytest.raises(NotImplementedError, match="not registered"):
        apply_derivations(df, contract)


def test_load_contract_instacart():
    c = load_contract(INSTACART / "dictionary.yaml")
    assert c.dataset_name == "instacart_2025_purchased_items"
    assert len(c.fields) == 15
    assert len(c.derived_fields) == 3
    assert c.pii is True
    assert "shipping_address" in c.pii_fields


def test_instacart_derivations_against_engine():
    """Verify the Instacart dictionary's derivations run through the field-agnostic engine."""
    c = load_contract(INSTACART / "dictionary.yaml")
    df = pd.DataFrame([
        {"order_id": "'ABC", "product_price": 10.0, "product_quantity": 2},
        {"order_id": "'ABC", "product_price": 5.0, "product_quantity": 1},
        {"order_id": "'DEF", "product_price": 20.0, "product_quantity": 4},
    ])
    out = apply_derivations(df, c)
    assert out.loc[0, "unit_price"] == 5.0
    assert out.loc[0, "order_item_count"] == 2
    assert out.loc[0, "order_total"] == 15.0
    assert out.loc[2, "order_total"] == 20.0


from dictionary_pipeline.contract import FieldSpec, Contract, load_contract
import tempfile
from pathlib import Path


def test_fieldspec_defaults_shareable_true():
    f = FieldSpec(
        name="foo",
        label="Foo",
        type="text",
        dtype="string",
    )
    assert f.shareable is True
    assert f.community_notes == ""


def test_load_contract_respects_shareable_flag():
    yaml_body = """
dataset:
  name: test_ds
  description: test
  source: test
  grain: one row per thing
  pii: false
  pii_fields: []
  naming_convention: snake_case
  last_updated: "2026-04-14"

fields:
  - name: field_a
    label: A
    type: text
    dtype: string
    nullable: false
    shareable: false
  - name: field_b
    label: B
    type: text
    dtype: string
    nullable: false
    community_notes: "Generic description for community sharing"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_body)
        path = f.name

    contract = load_contract(path)
    field_a = contract.field_by_name("field_a")
    field_b = contract.field_by_name("field_b")

    assert field_a.shareable is False
    assert field_b.shareable is True
    assert field_b.community_notes == "Generic description for community sharing"


def test_contract_community_version_defaults_empty():
    yaml_body = """
dataset:
  name: test_ds
  description: test
  source: test
  grain: one row per thing
  pii: false
  pii_fields: []
  naming_convention: snake_case
  last_updated: "2026-04-14"
fields: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_body)
        path = f.name

    contract = load_contract(path)
    assert contract.community_version == ""


def test_contract_community_version_loads_from_yaml():
    yaml_body = """
dataset:
  name: test_ds
  description: test
  source: test
  grain: one row per thing
  pii: false
  pii_fields: []
  naming_convention: snake_case
  last_updated: "2026-04-14"
  community_version: "1.0.0"
fields: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_body)
        path = f.name

    contract = load_contract(path)
    assert contract.community_version == "1.0.0"
