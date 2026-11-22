from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Node(Contract):
    id: Identifier
    type: Identifier
    label: Title
    x: float = Field(default=0, ge=-100_000, le=100_000)
    y: float = Field(default=0, ge=-100_000, le=100_000)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    retries: int = Field(default=0, ge=0, le=3)
    timeout: float = Field(default=20, ge=0.05, le=60)


class Edge(Contract):
    source: Identifier
    target: Identifier
    port: Identifier = "out"


class Graph(Contract):
    schema_version: Literal[1] = 1
    nodes: list[Node] = Field(default_factory=list, max_length=100)
    edges: list[Edge] = Field(default_factory=list, max_length=300)
    timeout: int = Field(default=300, ge=1, le=3600)


class WorkflowInput(Contract):
    name: Title
    description: str = Field(default="", max_length=2000)
    definition: Graph
    revision: int | None = Field(default=None, ge=1)


class RunInput(Contract):
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class Expression(Contract):
    field: str = Field(default="", max_length=200)
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "null", "not_null", "truthy"]
    value: JsonValue = None
    value_field: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def membership(self):
        if self.op == "in" and self.value_field is None and not isinstance(self.value, (list, str)):
            raise ValueError("Membership requires a list or string")
        return self


class Rules(Contract):
    mode: Literal["all", "any"] = "all"
    rules: list[Expression] = Field(min_length=1, max_length=20)
