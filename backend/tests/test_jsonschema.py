"""Strict structured output has two rules pydantic does not apply by default."""

from pydantic import BaseModel, Field

from src.model.jsonschema import strict_json_schema


class Inner(BaseModel):
    name: str = Field(..., description="名称")
    note: str | None = Field(default=None, description="备注")


class Outer(BaseModel):
    days: list[Inner] = Field(default_factory=list)
    reply: str = Field(..., min_length=1)


def walk(node):
    """Yield every dict inside a schema, at any depth."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def test_every_object_forbids_extra_keys() -> None:
    schema = strict_json_schema(Outer)

    objects = [node for node in walk(schema) if "properties" in node]
    assert objects, "the schema should contain at least one object"
    assert all(node["additionalProperties"] is False for node in objects)


def test_every_property_is_required() -> None:
    """Optionality must be a nullable type, never an omitted key."""
    schema = strict_json_schema(Inner)

    assert schema["required"] == ["name", "note"]


def test_nested_models_are_strict_too() -> None:
    schema = strict_json_schema(Outer)

    inner = next(node for node in walk(schema) if node.get("title") == "Inner")
    assert inner["additionalProperties"] is False
    assert inner["required"] == ["name", "note"]


def test_defaults_are_dropped() -> None:
    schema = strict_json_schema(Outer)

    assert all("default" not in node for node in walk(schema))


def test_an_optional_field_becomes_nullable_rather_than_absent() -> None:
    schema = strict_json_schema(Inner)

    note = schema["properties"]["note"]
    variants = note.get("anyOf", [note])
    assert {"type": "null"} in variants


def test_the_source_model_is_not_mutated() -> None:
    """Pydantic caches model_json_schema(); strictifying must not poison that cache."""
    strict_json_schema(Inner)

    raw = Inner.model_json_schema()
    assert "additionalProperties" not in raw
