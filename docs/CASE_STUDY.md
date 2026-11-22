# Engineering case study

A business operator needs to turn recurring spreadsheet cleanup and review into a process that can be explained and repeated. AgentForge puts the run order and business decisions on the graph, records what each node consumed and produced, and makes approvals and output files accessible from the same execution.

The local architecture uses a durable SQLite queue and one orchestration worker. The key tradeoff is predictable restart semantics with a lightweight install. Immutable versions prevent edits from changing in-flight work, and checkpoints keep approved or completed steps from being re-executed merely because the application restarted. A deterministic demo covers data enrichment, report generation, signed triggers and review. The offline provider handles rules-based processing so demonstrations do not need a model account.

The verification strategy uses HTTP integration tests against fresh SQLite directories, targeted browser tests of the builder, and repeatable fixed-seed benchmarks. Security boundaries constrain filesystem locations, network destinations, graph shape, secret handling and external writes. The current trust model and evidence are listed in [Project status](../PROJECT_STATUS.md).
