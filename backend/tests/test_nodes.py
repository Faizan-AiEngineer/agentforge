import csv
import io
import json

import pytest
from openpyxl import load_workbook

from backend.app.contracts import Graph
from backend.app.graph import analyze
from backend.app.nodes import REGISTRY, Context
from backend.app.runtime import PROJECT
from backend.app.templates import TEMPLATES, template


def direct(kind, value, config=None):
    spec = REGISTRY[kind]
    context = Context(PROJECT, PROJECT / "workflows" / "fixtures", frozenset(), "nodes",
                      "Node contract", {}, [value])
    coroutine = spec.action(context, spec.config.model_validate(config or {}))
    try:
        with pytest.raises(StopIteration) as completed:
            coroutine.send(None)
        return completed.value.value
    finally:
        coroutine.close()


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_builtin_templates_are_valid(key):
    graph = Graph.model_validate(template(key)["definition"])
    errors, order, *_ = analyze(graph)
    assert not errors
    assert len(order) == len(graph.nodes)


@pytest.mark.parametrize(
    "kind, config, expected",
    [
        ("filter", {"rules": [{"field": "amount", "op": "gt", "value": 5}]}, [{"id": "x", "amount": 8}]),
        ("map_fields", {"fields": {"transaction": "id"}}, [{"transaction": "x"}, {"transaction": "x"}]),
        ("dedupe", {}, [{"id": "x", "amount": 8}]),
        ("aggregate", {"operation": "sum"}, [{"group": None, "sum": 12}]),
    ],
)
def test_record_transforms(kind, config, expected):
    result = direct(kind, {"records": [{"id": "x", "amount": 8}, {"id": "x", "amount": 4}]}, config)
    assert result.output["records"] == expected
    assert result.output["count"] == len(expected)


def test_validation_quarantines_invalid_rows():
    result = direct("validate_records", {"records": [{"id": 1}, {}]})
    assert result.output["records"] == [{"id": 1}]
    assert result.output["invalid"] == [{}]
    assert result.output["invalid_count"] == 1


def test_field_to_field_comparison():
    result = direct("filter", {"records": [{"x": 10, "y": 1}, {"x": 2, "y": 2}]},
                    {"rules": [{"field": "x", "op": "ne", "value_field": "y"}]})
    assert result.output["records"] == [{"x": 10, "y": 1}]


def test_excel_and_csv_neutralize_formulas():
    records = {"records": [{"name": "=SUM(1,2)"}]}
    excel = direct("write_excel", records)
    workbook = load_workbook(io.BytesIO(excel.artifact[2]))
    assert workbook.active["A2"].value == "'=SUM(1,2)"
    workbook.close()
    result = direct("write_csv", records)
    rows = list(csv.DictReader(io.StringIO(result.artifact[2].decode("utf-8-sig"))))
    assert rows == [{"name": "'=SUM(1,2)"}]


def test_offline_supported_and_unsupported_inputs():
    result = direct("structured", {}, {"text": "status: complete", "fields": ["status"]})
    assert result.output == {"fields": {"status": "complete"}, "provider": "offline-rules"}
    with pytest.raises(ValueError, match="Unsupported offline input"):
        direct("structured", {}, {"text": "Write a novel", "fields": ["status"]})


def test_parser_and_json_artifact_contracts():
    values = direct("parse_json", {"text": '[{"id":1}]'}).output
    assert values == {"records": [{"id": 1}], "count": 1}
    assert json.loads(direct("write_json", values).artifact[2]) == values
    with pytest.raises(ValueError, match="Expected an array"):
        direct("write_csv", {})
