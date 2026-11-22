import asyncio
import csv
import hashlib
import io
import json
import re
import statistics
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from openpyxl import Workbook, load_workbook
from pydantic import Field, JsonValue, StringConstraints
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from .ai_providers import AISettings
from .contracts import Contract, Rules
from .security import MAX_FILE, read_file, request_json

Filename = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")]
REFERENCE = re.compile(r"\{\{\s*nodes\.([A-Za-z][\w-]*)\.output((?:\.[\w-]+)*)\s*\}\}", re.ASCII)
TEXT_LIMIT = 100_000


@dataclass(frozen=True)
class Context:
    root: Path
    fixtures: Path
    allowed_hosts: frozenset[str]
    run_id: str
    workflow_name: str
    payload: dict
    inputs: list[dict]
    approval: str | None = None
    auth: str | None = None
    allow_post: bool = False
    browser: str = ""
    timeline: list[dict] = field(default_factory=list)
    browser_hosts: frozenset[str] = frozenset()
    ai: AISettings = field(default_factory=AISettings)

    @property
    def first(self):
        return self.inputs[0] if self.inputs else {}


@dataclass
class Result:
    output: dict = field(default_factory=dict)
    port: str = "out"
    artifact: tuple[str, str, bytes] | None = None
    approval: tuple[str, int] | None = None


@dataclass(frozen=True)
class Spec:
    name: str
    category: str
    description: str
    config: type[Contract]
    action: Callable[[Context, Any], Awaitable[Result]]
    ports: tuple[str, ...] = ("out",)
    trigger: str | None = None
    replay: bool = True
    input_kind: str = "object"
    output_kind: str = "object"


REGISTRY: dict[str, Spec] = {}


def node(kind, name, group, config=Contract, **kwargs):
    def register(action):
        REGISTRY[kind] = Spec(name, group, action.__doc__ or name, config, action, **kwargs)
        return action

    return register


def get_path(value, path, default=None):
    for key in path.split(".") if path else ():
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and len(key) < 10 and key.isascii() and key.isdecimal() and int(key) < len(value):
            value = value[int(key)]
        else:
            return default
    return value


def compare(rule, data):
    actual = get_path(data, rule.field)
    expected = get_path(data, rule.value_field) if rule.value_field is not None else rule.value
    match rule.op:
        case "eq":
            return actual == expected
        case "ne":
            return actual != expected
        case "null":
            return actual is None
        case "not_null":
            return actual is not None
        case "truthy":
            return bool(actual)
        case "in":
            return (isinstance(expected, list) or (isinstance(expected, str) and isinstance(actual, str))
                    ) and actual in expected
    comparable = ((type(actual) in (int, float) and type(expected) in (int, float))
                  or (isinstance(actual, str) and isinstance(expected, str)))
    if not comparable:
        return False
    match rule.op:
        case "gt":
            return actual > expected
        case "gte":
            return actual >= expected
        case "lt":
            return actual < expected
        case "lte":
            return actual <= expected
    return False


def passes(config, data):
    checks = (compare(rule, data) for rule in config.rules)
    return all(checks) if config.mode == "all" else any(checks)


def records(ctx):
    values = ctx.first.get("records")
    if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
        raise ValueError("Expected an array of record objects at input.records")
    return values


def record_result(rows, **metadata):
    return Result({"records": rows, "count": len(rows), **metadata})


@node("manual", "Manual Trigger", "Triggers", trigger="manual", input_kind="none")
@node("schedule", "Schedule Trigger", "Triggers", trigger="schedule", input_kind="none")
@node("webhook", "Webhook Trigger", "Triggers", trigger="webhook", input_kind="none")
@node("file_trigger", "File Trigger", "Triggers", trigger="file", input_kind="none")
async def trigger(ctx, _):
    """Pass the originating event payload downstream."""
    return Result(ctx.payload)


class Values(Contract):
    values: dict[str, JsonValue] = Field(default_factory=dict)


@node("values", "Set Variables", "Utilities", Values)
async def values(_, config):
    """Create structured values or map exact upstream references."""
    return Result(config.values)


class FileConfig(Contract):
    filename: Filename = "orders.csv"
    source: Literal["input", "fixture"] = "fixture"


def input_root(ctx, config):
    return ctx.fixtures if config.source == "fixture" else ctx.root / "input"


class FixtureConfig(Contract):
    dataset: Literal["orders", "prices"] = "orders"


@node("fixture_api", "Offline API Fixture", "HTTP & APIs", FixtureConfig, output_kind="records")
async def fixture_api(ctx, config):
    """Read a recorded, synthetic JSON dataset from the bundled fixture."""
    data = read_file(ctx.fixtures, config.dataset + ".json")
    return record_result(json.loads(data)["records"])


class HTTPConfig(Contract):
    url: str = Field(min_length=1, max_length=2048)
    credential: str = Field(default="", pattern=r"^[a-z][a-z0-9-]{0,63}$|^$")


class PostConfig(HTTPConfig):
    body: dict[str, JsonValue] = Field(default_factory=dict)


class Pagination(HTTPConfig):
    records_key: str = "records"
    next_key: str = "next"
    max_pages: int = Field(default=3, ge=1, le=10)


@node("http_get", "HTTP GET", "HTTP & APIs", HTTPConfig)
async def http_get(ctx, config):
    """Fetch JSON from an administrator-approved public HTTPS origin."""
    data = await asyncio.to_thread(request_json, config.url, ctx.allowed_hosts, authorization=ctx.auth)
    return Result(data if isinstance(data, dict) else {"data": data})


@node("http_post", "HTTP POST", "HTTP & APIs", PostConfig, replay=False)
async def http_post(ctx, config):
    """Send JSON after an approval gate when external writes are enabled."""
    if not ctx.allow_post:
        raise ValueError("External writes require a successful upstream approval and administrator opt-in")
    data = await asyncio.to_thread(request_json, config.url, ctx.allowed_hosts,
                                   body=config.body, authorization=ctx.auth)
    return Result(data if isinstance(data, dict) else {"data": data})


@node("api_pages", "API Pagination", "HTTP & APIs", Pagination, output_kind="records")
async def api_pages(ctx, config):
    """Follow a bounded chain of approved HTTPS JSON pages."""
    from urllib.parse import urljoin, urlsplit

    rows, seen = [], set()
    url = config.url
    original_host = urlsplit(url).hostname
    for _ in range(config.max_pages):
        if url in seen:
            raise ValueError("API pagination repeated a URL")
        seen.add(url)
        auth = ctx.auth if urlsplit(url).hostname == original_host else None
        page = await asyncio.to_thread(request_json, url, ctx.allowed_hosts, authorization=auth)
        data = get_path(page, config.records_key)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ValueError("API page does not contain record objects")
        rows.extend(data)
        next_url = get_path(page, config.next_key)
        if not next_url:
            break
        if not isinstance(next_url, str):
            raise ValueError("API next link must be text")
        url = urljoin(url, next_url)
    return record_result(rows)


class JSONConfig(Contract):
    text: str | None = None


@node("parse_json", "JSON Parser", "HTTP & APIs", JSONConfig)
async def parse_json(ctx, config):
    """Decode JSON text into an object, records or a scalar result."""
    text = config.text if config.text is not None else ctx.first.get("text")
    if not isinstance(text, str):
        raise ValueError("Provide JSON text or an upstream text field")
    data = json.loads(text)
    if isinstance(data, list) and all(isinstance(row, dict) for row in data):
        return record_result(data)
    return Result(data if isinstance(data, dict) else {"data": data})


@node("read_csv", "CSV Reader", "Data Processing", FileConfig, output_kind="records")
async def read_csv(ctx, config):
    """Load record objects from the approved input or fixture directory."""
    filename = ctx.payload.get("filename", config.filename) if config.source == "input" else config.filename
    text = read_file(input_root(ctx, config), filename).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("CSV needs unique column headers")
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("CSV rows must match the column headers")
    return record_result(rows)


class ExcelConfig(FileConfig):
    filename: Filename = "orders.xlsx"


@node("read_excel", "Excel Reader", "Data Processing", ExcelConfig, output_kind="records")
async def read_excel(ctx, config):
    """Read the first sheet of a bounded XLSX workbook."""
    from zipfile import ZipFile

    data = read_file(input_root(ctx, config), config.filename)
    with ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 16 * 1024 * 1024:
            raise ValueError("Expanded workbook exceeds 16 MiB")
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = book.active
        if (sheet.max_row or 0) > 10000 or (sheet.max_column or 0) > 100:
            raise ValueError("Sheet exceeds the 10,000 row or 100 column limit")
        rows = sheet.values
        headers = [str(cell or "") for cell in next(rows, ())]
        if not headers or not all(headers) or len(set(headers)) != len(headers):
            raise ValueError("Sheet needs nonempty, unique column headers")
        return record_result([
            dict(zip(headers, (cell.isoformat() if hasattr(cell, "isoformat") else cell for cell in row),
                     strict=True))
            for row in rows
        ])
    finally:
        book.close()


@node("filter", "Filter Records", "Data Processing", Rules, input_kind="records", output_kind="records")
async def filter_data(ctx, config):
    """Keep records that match the configured rules."""
    return record_result([row for row in records(ctx) if passes(config, row)])


class Mapping(Contract):
    fields: dict[str, str] = Field(default_factory=lambda: {"name": "name"})


@node("map_fields", "Map Fields", "Data Processing", Mapping, input_kind="records", output_kind="records")
async def map_fields(ctx, config):
    """Copy source paths into the selected output fields."""
    return record_result([{key: get_path(row, path) for key, path in config.fields.items()}
                          for row in records(ctx)])


class Clean(Contract):
    trim: bool = True
    drop_empty: bool = False
    numeric_fields: list[str] = Field(default_factory=list, max_length=100)


@node("clean", "Clean Records", "Data Processing", Clean, input_kind="records", output_kind="records")
async def clean(ctx, config):
    """Trim text, discard empty values and coerce selected numeric fields."""
    rows = []
    for row in records(ctx):
        cleaned = {}
        for key, value in row.items():
            if config.trim and isinstance(value, str):
                value = value.strip()
            if value is None or value == "":
                if config.drop_empty:
                    continue
            elif key in config.numeric_fields:
                value = float(value)
            cleaned[key] = value
        rows.append(cleaned)
    return record_result(rows)


class Keys(Contract):
    keys: list[str] = Field(default_factory=lambda: ["id"], min_length=1, max_length=30)


@node("dedupe", "Deduplicate", "Data Processing", Keys, input_kind="records", output_kind="records")
async def dedupe(ctx, config):
    """Keep the first row for each combination of selected field values."""
    seen, rows = set(), []
    for row in records(ctx):
        key = json.dumps([get_path(row, path) for path in config.keys], sort_keys=True)
        if key not in seen:
            seen.add(key)
            rows.append(row)
    return record_result(rows)


class Aggregate(Contract):
    operation: Literal["count", "sum", "average", "min", "max"] = "count"
    field: str = "amount"
    group_by: str = ""


@node("aggregate", "Aggregate Records", "Data Processing", Aggregate,
      input_kind="records", output_kind="records")
async def aggregate(ctx, config):
    """Compute bounded grouped counts or numeric aggregates."""
    groups = defaultdict(list)
    for row in records(ctx):
        key = json.dumps(get_path(row, config.group_by) if config.group_by else None, sort_keys=True)
        groups[key].append(get_path(row, config.field))
    operations = {"count": len, "sum": sum, "average": statistics.fmean, "min": min, "max": max}
    results = []
    for key, values in groups.items():
        if config.operation != "count" and any(type(value) not in (float, int) for value in values):
            raise ValueError("Numeric aggregation requires numeric values")
        results.append({"group": json.loads(key), config.operation: operations[config.operation](values)})
    return record_result(results)


class Validate(Contract):
    required: list[str] = Field(default_factory=lambda: ["id"], max_length=100)
    rules: Rules | None = None


@node("validate_records", "Validate Records", "Data Processing", Validate,
      input_kind="records", output_kind="records")
async def validate_records(ctx, config):
    """Separate valid and quarantined records and report their counts."""
    valid, invalid = [], []
    for row in records(ctx):
        has_fields = all(get_path(row, path) not in (None, "") for path in config.required)
        selected = valid if has_fields and (not config.rules or passes(config.rules, row)) else invalid
        selected.append(row)
    return record_result(valid, invalid=invalid, invalid_count=len(invalid))


@node("condition", "Condition", "Logic & Control", Rules, ports=("true", "false"))
async def condition(ctx, config):
    """Route the current object through the true or false port."""
    return Result(ctx.first, "true" if passes(config, ctx.first) else "false")


class Cases(Contract):
    cases: dict[Literal["case1", "case2", "case3"], Rules] = Field(default_factory=dict)


@node("switch", "Switch", "Logic & Control", Cases, ports=("case1", "case2", "case3", "default"))
async def switch(ctx, config):
    """Route to the first matching configured case, then to default."""
    for port, rules in sorted(config.cases.items()):
        if passes(rules, ctx.first):
            return Result(ctx.first, port)
    return Result(ctx.first, "default")


@node("merge", "Merge", "Logic & Control")
async def merge(ctx, _):
    """Collect active inputs, concatenating any record arrays."""
    rows = [row for value in ctx.inputs for row in value.get("records", []) if isinstance(row, dict)]
    return record_result(rows, inputs=ctx.inputs)


class Delay(Contract):
    seconds: float = Field(default=1, ge=0, le=30)


@node("delay", "Delay", "Logic & Control", Delay)
async def delay(ctx, config):
    """Wait asynchronously, then forward the input."""
    await asyncio.sleep(config.seconds)
    return Result(ctx.first)


class Batch(Contract):
    size: int = Field(default=50, ge=1, le=1000)


@node("batch", "Batch Iterator", "Logic & Control", Batch, input_kind="records")
async def batch(ctx, config):
    """Partition records into bounded batches for downstream processing."""
    rows = records(ctx)
    batches = [rows[index:index + config.size] for index in range(0, len(rows), config.size)]
    return Result({"batches": batches, "count": len(batches)})


class Text(Contract):
    text: str | None = Field(default=None, max_length=TEXT_LIMIT)


@node("format_text", "Format Text", "Utilities", Text)
async def format_text(ctx, config):
    """Insert simple input paths using {field} placeholders."""
    text = config.text if config.text is not None else ctx.first.get("text", "")
    pattern = r"(?<!\{)\{([\w.-]+)\}(?!\})"
    return Result({"text": re.sub(pattern, lambda match: str(get_path(ctx.first, match[1], "")), text)})


@node("datetime", "Date and Time", "Utilities")
async def date_time(_, __):
    """Produce the current UTC timestamp."""
    return Result({"timestamp": datetime.now(UTC).isoformat()})


class Transform(Contract):
    path: str = ""
    key: str = "data"


@node("transform", "JSON Transform", "Utilities", Transform)
async def transform(ctx, config):
    """Place a selected JSON path under a configured key."""
    return Result({config.key: get_path(ctx.first, config.path)})


class ApprovalConfig(Contract):
    action: str = Field(default="Review this workflow output", min_length=1, max_length=300)
    expires_in: int = Field(default=86400, ge=1, le=604800)


@node("approval", "Human Approval", "Human Approval", ApprovalConfig,
      ports=("approve", "reject", "request_changes", "expired"))
async def approval(ctx, config):
    """Suspend the workflow and route the reviewer decision when it resumes."""
    if ctx.approval:
        return Result({**ctx.first, "decision": ctx.approval}, ctx.approval.lower())
    return Result(approval=(config.action, config.expires_in))


class Export(Contract):
    filename: Filename = "results"


def cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and (value.startswith(("\t", "\r", "\n"))
                                   or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value


def artifact(config, extension, mime, data):
    if len(data) > MAX_FILE:
        raise ValueError("Output exceeds the 4 MiB artifact limit")
    stem = config.filename.removesuffix("." + extension)
    return Result({"filename": f"{stem}.{extension}", "sha256": hashlib.sha256(data).hexdigest()},
                  artifact=(f"{stem}.{extension}", mime, data))


def export_rows(ctx):
    rows = records(ctx)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    return rows, columns


@node("write_csv", "CSV Export", "Files & Documents", Export, input_kind="records")
async def write_csv(ctx, config):
    """Create a downloadable UTF-8 CSV artifact."""
    rows, columns = export_rows(ctx)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow([cell(key) for key in columns])
    writer.writerows([cell(row.get(key)) for key in columns] for row in rows)
    return artifact(config, "csv", "text/csv", stream.getvalue().encode("utf-8-sig"))


@node("write_excel", "Excel Export", "Files & Documents", Export, input_kind="records")
async def write_excel(ctx, config):
    """Create a downloadable XLSX artifact."""
    rows, columns = export_rows(ctx)
    book = Workbook()
    book.active.title = "AgentForge results"
    book.active.append([cell(key) for key in columns])
    book.active.freeze_panes = "A2"
    for row in rows:
        book.active.append([cell(row.get(key)) for key in columns])
    stream = io.BytesIO()
    book.save(stream)
    return artifact(config, "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    stream.getvalue())


@node("write_json", "JSON Export", "Files & Documents", Export)
async def write_json(ctx, config):
    """Save the current object as a JSON artifact."""
    return artifact(config, "json", "application/json", json.dumps(ctx.first, indent=2).encode())


@node("write_text", "Text Export", "Files & Documents", Export)
async def write_text(ctx, config):
    """Save the text field as a downloadable text artifact."""
    text = ctx.first.get("text", ctx.first.get("summary"))
    if not isinstance(text, str):
        raise ValueError("Expected a text or summary field")
    return artifact(config, "txt", "text/plain", text.encode())


@node("report", "PDF Report", "Files & Documents", Export)
async def report(ctx, config):
    """Generate a PDF with processing results and the persisted node timeline."""
    stream = io.BytesIO()
    doc = canvas.Canvas(stream, pagesize=(612, 792))
    doc.setTitle(ctx.workflow_name)
    doc.setFillColor(colors.HexColor("#101e32"))
    doc.rect(0, 650, 612, 142, fill=1, stroke=0)
    doc.setFillColor(colors.HexColor("#75e2cf"))
    doc.setFont("Helvetica-Bold", 11)
    doc.drawString(42, 747, "AGENTFORGE / EXECUTION REPORT")
    doc.setFillColor(colors.white)
    doc.setFont("Helvetica-Bold", 24)
    doc.drawString(42, 704, ctx.workflow_name[:44])
    doc.setFont("Helvetica", 10)
    doc.drawString(42, 674, "Execution " + ctx.run_id)
    lines = ["Node timeline"]
    for step in ctx.timeline:
        lines.append(f"{step['node_id']}   {step['status']}   attempts {step['attempts']}")
        if step["error"]:
            lines.append("  " + step["error"])
    lines += ["", "Processing results", *json.dumps(ctx.first, indent=2).splitlines()[:100]]
    y = 620
    for line in lines:
        if y < 48:
            doc.showPage()
            y = 740
        doc.setFillColor(colors.HexColor("#162744"))
        doc.setFont("Courier", 9)
        doc.drawString(42, y, line[:98])
        y -= 14
    doc.save()
    return artifact(config, "pdf", "application/pdf", stream.getvalue())
