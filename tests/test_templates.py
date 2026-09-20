"""Tests to verify all shipped templates load and pass schema validation."""
from __future__ import annotations

import pytest
from builder.models import ServerConfig
from builder.templates import load_template, load_templates


def test_load_all_templates():
    templates = load_templates()
    expected = {"business", "community", "gaming", "study"}
    for key in expected:
        assert key in templates, f"Template {key} missing from load_templates()"
    # Example is loaded separately as detailed example
    example = load_template("example")
    assert example is not None


@pytest.mark.parametrize("name", ["business", "community", "gaming", "study", "example"])
def test_template_validates(name: str):
    schema = load_template(name)
    assert schema is not None
    # Validate via ServerConfig
    config = ServerConfig.from_dict(schema)
    dict_val = config.to_dict()
    assert "roles" in dict_val
    assert "categories" in dict_val
    assert len(dict_val["roles"]) > 0
    assert len(dict_val["categories"]) > 0
