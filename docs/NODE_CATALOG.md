# Node catalog

The library reads configuration schemas and ports from `GET /api/v1/nodes`. Common execution settings are retries (0–3) and timeout (0.05–60 seconds). Invalid configurations fail graph validation or, when using a runtime reference, fail before the node action. Outputs are bounded JSON objects, and downloads are durable artifact references.

| Category | Nodes | Inputs and outputs |
| --- | --- | --- |
| Triggers | Manual, Schedule, Webhook, File | Pass event payload to the first active downstream node |
| HTTP & APIs | Offline API Fixture, HTTP GET, HTTP POST, API Pagination, JSON Parser | Fixture `orders`; approved HTTPS `url`; optional credential and bounded pages; parse a `text` field |
| Data Processing | CSV Reader, Excel Reader, Filter Records, Map Fields, Clean Records, Deduplicate, Aggregate Records, Validate Records | Inputs and outputs use `records` arrays. Map Fields takes an output-to-path map. Validation adds `invalid` and `invalid_count`. |
| Logic & Control | Condition, Switch, Merge, Delay, Batch Iterator | Named routing ports, collection merge, async bounded waits, or partitioned arrays |
| Utilities | Set Variables, Format Text, Date and Time, JSON Transform | Structured `values`, safe field placeholders, UTC timestamp, or JSON path lookup |
| Human Approval | Human Approval | Pauses for `action` and routes through `approve`, `reject`, `request_changes`, or `expired` |
| Files & Documents | CSV Export, Excel Export, JSON Export, Text Export, PDF Report, Read Text Fixture | Generate scope-bound files from records or objects. Fixture returns memo text. |
| Browser Automation | Open Browser Page, Extract Browser Table, Extract Browser Text, Extract Browser Links, Extract Browser Elements, Capture Browser Screenshot | Fixture or an approved HTTPS URL. Selectors, page count, record count, and per-operation deadline are bounded. Element and table nodes emit `records` for CSV/XLSX export. |
| AI Processing | Text Summarizer, Information Extractor, Text Classifier, Structured Output, AI Task | The AI Task supports summarization, extraction, classification, and typed JSON through the offline provider or a configured external adapter. |

For an example using these contracts, preview an imported template and change the relevant node fields in the builder. HTTP nodes require approved hosts. Browser nodes require an installed Chromium or supported desktop channel. External browser pagination reads a bounded next-link selector and validates the next target before each request. Batch Iterator emits arrays for the next node.

AI Task takes `provider`, an optional `model`, `task`, and text from its configuration or the upstream `text` field. Structured tasks take a mapping of required field names to JSON field types such as `{"status":"string","approved":"boolean"}`. Results are data fields, with safe `provider`, `model`, and usage counts. This node is non-replayable because a remote request can consume provider resources.
