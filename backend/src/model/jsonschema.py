"""Adapt a pydantic model to the schema dialect strict structured outputs require.

Providers that implement ``response_format={"type": "json_schema", "strict": true}``
validate the model's JSON against a schema *before* returning it, which removes a
whole failure class: the field is present, of the right type, and no extra keys.

Strict mode has two requirements pydantic does not satisfy by default:

* every object sets ``additionalProperties: false``;
* every property is listed in ``required`` - optionality is expressed as a nullable
  type (``{"anyOf": [{"type": "string"}, {"type": "null"}]}``), never by omission.

Pydantic in turn emits ``default``, which strict mode has no use for. This module
is the whole translation layer, so the wire concern never leaks into the models.
"""

from typing import Any

from pydantic import BaseModel


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON Schema, made acceptable to strict structured outputs."""
    schema = model.model_json_schema()
    _strictify(schema)
    return schema


def _strictify(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("default", None)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for value in list(node.values()):
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)
