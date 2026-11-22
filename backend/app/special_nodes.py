import asyncio
import re
from typing import Literal

from pydantic import Field

from .contracts import Contract
from .nodes import Result, Text, node
from .security import read_file


def input_text(ctx, config):
    value = config.text if config.text is not None else ctx.first.get("text")
    if not isinstance(value, str) or not value.strip() or len(value) > 100_000:
        raise ValueError("Provide nonempty text within 100,000 characters")
    return value


class Summarize(Text):
    sentences: int = Field(default=2, ge=1, le=8)


@node("summarize", "Text Summarizer", "AI Processing", Summarize)
async def summarize(ctx, config):
    """Select the first sentences using the deterministic offline provider."""
    text = input_text(ctx, config)
    summary = " ".join(re.split(r"(?<=[.!?])\s+", text.strip())[:config.sentences])
    return Result({"summary": summary, "text": summary, "provider": "offline-rules"})


@node("extract_info", "Information Extractor", "AI Processing", Text)
async def extract_info(ctx, config):
    """Extract email addresses and numeric literals using offline rules."""
    text = input_text(ctx, config)
    emails = list(dict.fromkeys(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)))
    numbers = re.findall(r"(?<!\w)-?\d+(?:\.\d+)?", text)
    return Result({"emails": emails[:100], "numbers": numbers[:100], "provider": "offline-rules"})


class Classifier(Text):
    categories: dict[str, list[str]] = Field(default_factory=lambda: {"billing": ["invoice", "payment"]})


@node("classify", "Text Classifier", "AI Processing", Classifier)
async def classify(ctx, config):
    """Select a label using case-insensitive keyword matching."""
    text = input_text(ctx, config).casefold()
    scores = {label: sum(keyword.casefold() in text for keyword in words if keyword)
              for label, words in config.categories.items()}
    label = max(scores, key=scores.get) if scores and max(scores.values()) else "unclassified"
    return Result({"label": label, "scores": scores, "provider": "offline-rules"})


class Structured(Text):
    fields: list[str] = Field(default_factory=lambda: ["status"], min_length=1, max_length=20)


class StructuredResult(Contract):
    fields: dict[str, str]
    provider: Literal["offline-rules"] = "offline-rules"


@node("structured", "Structured Output", "AI Processing", Structured)
async def structured(ctx, config):
    """Validate requested fields from text containing key: value lines."""
    text = input_text(ctx, config)
    fields = dict(line.split(":", 1) for line in text.splitlines() if ":" in line)
    missing = [key for key in config.fields if key not in fields]
    if missing:
        raise ValueError("Unsupported offline input. Missing fields: " + ", ".join(missing))
    result = StructuredResult(fields={key: fields[key].strip() for key in config.fields})
    return Result(result.model_dump())


class ReadText(Contract):
    sample: Literal["memo"] = "memo"


@node("read_text", "Read Text Fixture", "Files & Documents", ReadText)
async def read_text(ctx, config):
    """Read the approved demonstration memo from disk."""
    data = await asyncio.to_thread(read_file, ctx.fixtures, config.sample + ".txt")
    return Result({"text": data.decode("utf-8")})
