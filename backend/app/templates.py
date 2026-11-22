from .contracts import Graph, WorkflowInput


def chain(*steps):
    nodes = [{"id": f"n{i}", "type": kind, "label": label, "x": 50 + (i % 4) * 245,
              "y": 95 + (i // 4) * 185, "config": config, "timeout": 45 if kind.startswith("browser_") else 20}
             for i, (kind, label, config) in enumerate(steps)]
    edges = [{"source": f"n{i-1}", "target": f"n{i}"} for i in range(1, len(steps))]
    return {"nodes": nodes, "edges": edges}


MANUAL = ("manual", "Manual Trigger", {})
SCHEDULE = ("schedule", "Schedule Trigger", {})
READ = ("read_csv", "Read order records", {})
CLEAN = ("clean", "Clean order fields", {"numeric_fields": ["amount"], "drop_empty": True})
VALIDATE = ("validate_records", "Validate required fields", {"required": ["id", "name"]})
DEDUP = ("dedupe", "Deduplicate orders", {"keys": ["id"]})
REPORT = ("report", "Generate PDF report", {"filename": "agentforge-report"})


def routing():
    graph = chain(MANUAL, ("values", "Prepare purchase request", {"values": {"amount": 240, "text": "Supply order"}}),
                  ("condition", "Over approval threshold?",
                   {"rules": [{"field": "amount", "op": "gt", "value": 100}]}),
                  ("approval", "Review purchase request", {"action": "Approve the proposed supply order"}),
                  ("write_json", "Save approved request", {"filename": "approved"}),
                  ("write_json", "Save review outcome", {"filename": "review"}),
                  ("write_json", "Save routine request", {"filename": "routine"}))
    graph["nodes"][3].update(x=780, y=35)
    graph["nodes"][4].update(x=1040, y=0)
    graph["nodes"][5].update(x=1040, y=153)
    graph["nodes"][6].update(x=780, y=230)
    graph["edges"] = graph["edges"][:2] + [
        {"source": "n2", "target": "n3", "port": "true"},
        {"source": "n2", "target": "n6", "port": "false"},
        {"source": "n3", "target": "n4", "port": "approve"},
        *({"source": "n3", "target": "n5", "port": port}
          for port in ("reject", "request_changes", "expired")),
    ]
    return graph


TEMPLATES = {
    "api-to-csv": ("API to CSV", "Data operations", "Collect fixture data, map order fields and export a CSV.",
                   chain(MANUAL, ("fixture_api", "Collect order records", {}),
                         ("map_fields", "Map order fields", {"fields": {"order": "id", "customer": "name", "amount": "amount"}}),
                         ("write_csv", "Export orders", {"filename": "orders"}))),
    "csv-cleanup": ("CSV Cleaning", "Data operations", "Trim order fields, quarantine incomplete rows and deduplicate.",
                    chain(MANUAL, READ, CLEAN, VALIDATE, DEDUP, ("write_csv", "Save cleaned orders", {"filename": "clean-orders"}))),
    "daily-report": ("Daily Business Report", "Reporting", "Aggregate synthetic orders by region and generate a PDF.",
                     chain(SCHEDULE, READ, CLEAN, ("aggregate", "Sum by region", {"operation": "sum", "group_by": "region"}),
                           REPORT)),
    "lead-excel": ("Lead Data Preparation", "Reporting", "Validate and deduplicate synthetic contacts in an Excel export.",
                   chain(MANUAL, READ, VALIDATE, DEDUP, ("write_excel", "Generate Excel workbook", {"filename": "sales-leads"}))),
    "website-extraction": ("Website Data Extraction", "Browser automation", "Read two offline catalog pages and create a workbook.",
                           chain(MANUAL, ("browser_table", "Extract catalog table", {"pages": 2}),
                                 ("clean", "Clean prices", {"numeric_fields": ["Price"]}),
                                 ("write_excel", "Export catalog", {"filename": "catalog"}))),
    "ai-document": ("AI Document Processing", "AI processing", "Process a sample memo using deterministic offline text rules.",
                    chain(MANUAL, ("read_text", "Load sample memo", {}), ("summarize", "Summarize memo", {"sentences": 3}),
                          ("structured", "Extract status field", {"fields": ["status"],
                           "text": "{{ nodes.n1.output.text }}"}), REPORT)),
    "approval-routing": ("Purchase Approval", "Human approval", "Route a purchase request to a reviewer and record the decision.",
                         routing()),
    "data-quality": ("Data Quality Automation", "Data operations", "Validate a CSV, retain quarantined rows and generate a report.",
                     chain(("file_trigger", "Watch approved input", {}),
                           ("read_csv", "Read changed file", {"source": "input"}), CLEAN, VALIDATE, REPORT)),
    "price-monitor": ("Price Monitoring", "Reporting", "Compare current and prior fixture prices, then save the price changes.",
                      chain(SCHEDULE, ("fixture_api", "Read price snapshots", {"dataset": "prices"}),
                            ("filter", "Find changed prices", {"rules": [
                                {"field": "current", "op": "ne", "value_field": "previous"}]}),
                            ("write_csv", "Export changed prices", {"filename": "price-changes"}))),
}


def template(key):
    name, group, description, definition = TEMPLATES[key]
    model = WorkflowInput(name=name, description=description, definition=Graph.model_validate(definition))
    return {"id": key, "category": group, **model.model_dump(mode="json", exclude={"revision"})}
