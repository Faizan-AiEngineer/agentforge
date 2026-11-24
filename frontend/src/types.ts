export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type JsonObject = { [key: string]: Json }
export type NodeDefinition = {
  id: string; type: string; label: string; x: number; y: number
  config: JsonObject; retries: number; timeout: number
}
export type Wire = { source: string; target: string; port: string }
export type Graph = { schema_version: 1; nodes: NodeDefinition[]; edges: Wire[]; timeout: number }
export type Draft = { name: string; description: string; definition: Graph }
export type Workflow = Draft & { id: string; revision: number; created: number; updated: number }
export type Template = Draft & { id: string; category: string }
export type Schema = {
  type?: string; enum?: string[]; default?: Json; title?: string; minimum?: number; maximum?: number
  properties?: Record<string, Schema>; required?: string[]
}
export type NodeSpec = {
  type: string; name: string; category: string; description: string; schema: Schema
  ports: string[]; trigger: string | null; input_kind: string; output_kind: string; available: boolean
}
export type Execution = {
  id: string; workflow_id: string; workflow_name: string; revision: number; status: string; source: string
  created: number; started: number | null; ended: number | null; error: string | null
}
export type Step = {
  node_id: string; status: string; attempts: number; inputs: Json; output: Json
  port: string | null; error: string | null; started: number | null; ended: number | null
}
export type Artifact = { id: string; filename: string; size: number; sha256: string; media_type: string }
export type Approval = {
  id: string; workflow_name: string; execution_id: string; action: string; context: Json
  decision: string | null; reviewer: string; created: number; expires: number
}
export type ExecutionDetails = Execution & { can_resume: boolean; can_rerun: boolean; definition: Graph; nodes: Step[]; approvals: Approval[]; artifacts: Artifact[] }
export type Page<T> = { items: T[]; total: number; offset: number; limit: number }
export type Metrics = {
  workflows: number; total_executions: number; completed: number; statuses: Record<string, number>
  active_workflows: number; failed: number; success_rate: number | null; avg_duration: number | null
  pending_approvals: number; node_usage: { node: string; runs: number }[]; recent: Execution[]
}
