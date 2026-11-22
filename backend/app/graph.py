from collections import defaultdict, deque

from pydantic import ValidationError

from . import ai_nodes as _ai_nodes  # noqa: F401
from . import browser_nodes as _browser_nodes  # noqa: F401
from . import special_nodes as _special_nodes  # noqa: F401
from .nodes import REFERENCE, REGISTRY, get_path
from .security import MAX_BODY, json_size


def references(value):
    if isinstance(value, str):
        ref = REFERENCE.fullmatch(value)
        if ref:
            yield ref
    if isinstance(value, dict):
        for item in value.values():
            yield from references(item)
    if isinstance(value, list):
        for item in value:
            yield from references(item)


def resolve(value, outputs):
    if isinstance(value, str):
        ref = REFERENCE.fullmatch(value)
        if ref:
            missing = object()
            found = get_path(outputs.get(ref[1], {}), ref[2].lstrip("."), missing)
            if ref[1] not in outputs or found is missing:
                raise ValueError(f"Unavailable output reference: {ref[1]}{ref[2]}")
            return found
    if isinstance(value, dict):
        return {key: resolve(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, outputs) for item in value]
    return value


def config_errors(node, spec):
    try:
        spec.config.model_validate(node.config)
    except ValidationError as exc:
        for item in exc.errors(include_url=False, include_input=False):
            path = ".".join(map(str, item["loc"]))
            raw = get_path(node.config, path)
            if item["type"] != "extra_forbidden" and isinstance(raw, str) and REFERENCE.fullmatch(raw):
                continue
            yield f"{node.label} configuration {path}: {item['msg']}"


def analyze(graph):
    errors = []
    nodes = {node.id: node for node in graph.nodes}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    if json_size(graph.model_dump()) > MAX_BODY:
        errors.append("Workflow exceeds the JSON size limit")
    if len(nodes) != len(graph.nodes):
        errors.append("Node IDs must be unique")
    triggers = []
    for item in graph.nodes:
        spec = REGISTRY.get(item.type)
        if not spec:
            errors.append(f"Unsupported node type: {item.type}")
            continue
        if spec.trigger:
            triggers.append(item.id)
        if item.retries and not spec.replay:
            errors.append(f"{item.label} cannot be retried automatically")
        errors.extend(config_errors(item, spec))
    if len(triggers) != 1:
        errors.append("Connect exactly one trigger")
    seen = set()
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.port)
        if key in seen or edge.source not in nodes or edge.target not in nodes:
            errors.append(f"Duplicate edge or missing endpoint: {edge.source} → {edge.target}")
            continue
        seen.add(key)
        source = REGISTRY.get(nodes[edge.source].type)
        target = REGISTRY.get(nodes[edge.target].type)
        if source and edge.port not in source.ports:
            errors.append(f"Unknown port {edge.port} on {edge.source}")
        if target and target.trigger:
            errors.append("Trigger nodes cannot receive incoming edges")
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
    remaining = {key: len(incoming[key]) for key in nodes}
    ready = deque(key for key, count in remaining.items() if not count)
    ordered, ancestors, reachable = [], defaultdict(set), set(triggers)
    while ready:
        key = ready.popleft()
        ordered.append(key)
        if key not in reachable:
            errors.append(f"{nodes[key].label} is disconnected from the trigger")
        for ref in references(nodes[key].config):
            if ref[1] not in ancestors[key]:
                errors.append(f"{nodes[key].label} references {ref[1]}, which must be upstream")
        for edge in outgoing[key]:
            remaining[edge.target] -= 1
            ancestors[edge.target].update(ancestors[key] | {key})
            if key in reachable:
                reachable.add(edge.target)
            if remaining[edge.target] == 0:
                ready.append(edge.target)
    if len(ordered) != len(nodes):
        errors.append("Graph contains a cycle")
    return list(dict.fromkeys(errors)), ordered, nodes, incoming, ancestors
