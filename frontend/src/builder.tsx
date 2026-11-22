import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow,
  type Connection, type Edge, type Node, type NodeChange, type NodeProps, type NodeTypes } from '@xyflow/react'
import { Check, CircleHelp, ClipboardCheck, Copy, Download, FileJson, GitBranch, Grid2X2, PanelLeft,
  Play, Plus, Redo2, Save, Search, Settings2, Trash2, Undo2, X } from 'lucide-react'
import { request, useApi } from './api'
import { useToast } from './app'
import { attach, blankGraph, createNode, edgeId, removeNode } from './graph'
import type { Draft, Execution, ExecutionDetails, Graph, Json, JsonObject, NodeDefinition, NodeSpec, Schema, Step, Workflow } from './types'
import { Badge, Glyph, Loading, Notice } from './ui'

type FlowData = { definition: NodeDefinition; spec?: NodeSpec; status?: string }
type ForgeNode = Node<FlowData, 'forge'>

function FlowCard({ data, selected }: NodeProps<ForgeNode>) {
  const { spec, definition, status } = data
  const ports = spec?.ports ?? ['out']
  return <div className={'flow-node' + (selected ? ' selected' : '')} data-node-id={definition.id}>
    {!spec?.trigger && <Handle type="target" position={Position.Left} id="input" />}
    <div className="flow-node-core"><Glyph group={spec?.category ?? 'Utilities'} size={17} /><div><strong>{definition.label}</strong><small>{spec?.name ?? definition.type}</small></div></div>
    {status && <div className="flow-status"><Badge value={status} /></div>}
    {ports.map((port, index) => <div key={port} className={'flow-port' + (ports.length > 1 ? ' named' : '')} style={{ top: ports.length > 1 ? 14 + index * 14 : 32 }}>
      {ports.length > 1 && <span>{port.replaceAll('_', ' ')}</span>}<Handle type="source" position={Position.Right} id={port} />
    </div>)}
  </div>
}

const nodeTypes: NodeTypes = { forge: FlowCard }

function flowNodes(graph: Graph, specs: NodeSpec[], steps: Step[], selected?: string): ForgeNode[] {
  return graph.nodes.map(definition => ({ id: definition.id, type: 'forge', position: { x: definition.x, y: definition.y },
    selected: definition.id === selected,
    data: { definition, spec: specs.find(node => node.type === definition.type), status: steps.find(step => step.node_id === definition.id)?.status } }))
}
function flowEdges(graph: Graph, selected?: string): Edge[] {
  return graph.edges.map(edge => ({ ...edge, id: edgeId(edge), sourceHandle: edge.port, targetHandle: 'input',
    type: 'smoothstep', selected: selected === edgeId(edge), label: edge.port === 'out' ? undefined : edge.port.replaceAll('_', ' ') }))
}

export function ExecutionGraph({ graph, steps = [], select }: { graph: Graph; steps?: Step[]; select?: (id: string) => void }) {
  const specs = useApi<NodeSpec[]>('/nodes')
  const [active, setActive] = useState('')
  return <div className="execution-graph"><ReactFlow nodes={flowNodes(graph, specs.data ?? [], steps, active)} edges={flowEdges(graph)}
    nodeTypes={nodeTypes} onNodeClick={(_, node) => { setActive(node.id); select?.(node.id) }}
    nodesConnectable={false} nodesDraggable={false} fitView fitViewOptions={{ padding: .3, maxZoom: .95 }}
    minZoom={.15} proOptions={{ hideAttribution: true }}><Background gap={20} size={1.1} variant={BackgroundVariant.Dots} /><Controls showInteractive={false} /></ReactFlow></div>
}

function JsonField({ value, change, label }: { value: Json | undefined; change: (value: Json | undefined) => void; label: string }) {
  const serialized = value === undefined ? '' : JSON.stringify(value, null, 2)
  const [text, setText] = useState(serialized)
  const [invalid, setInvalid] = useState(false)
  useEffect(() => { setText(serialized); setInvalid(false) }, [serialized])
  return <><textarea className="code-field nodrag" aria-label={label} value={text} rows={4} spellCheck={false}
    onChange={event => { setText(event.target.value); setInvalid(false) }}
    onBlur={() => {
      try { change(text.trim() ? JSON.parse(text) : undefined); setInvalid(false) }
      catch { setInvalid(true) }
    }} />{invalid && <small className="error-text" role="alert">Enter valid JSON before leaving this field.</small>}</>
}

function Field({ schema, name, value, change }: { schema: Schema; name: string; value: Json | undefined; change: (value: Json | undefined) => void }) {
  const current = value ?? schema.default
  if (schema.enum) return <select aria-label={name} value={typeof current === 'string' ? current : ''} onChange={event => change(event.target.value)}>
    {schema.default === undefined && <option value="">Select an option</option>}{schema.enum.map(item => <option key={item}>{item}</option>)}</select>
  if (schema.type === 'boolean') return <input type="checkbox" aria-label={name} checked={current === true} onChange={event => change(event.target.checked)} />
  if (schema.type === 'number' || schema.type === 'integer') return <input type="number" aria-label={name} value={typeof current === 'number' ? current : ''}
    min={schema.minimum} max={schema.maximum} step={schema.type === 'integer' ? 1 : 'any'} onChange={event => change(event.target.value === '' ? undefined : Number(event.target.value))} />
  if (schema.type === 'string' || name === 'text') return <input aria-label={name} value={typeof current === 'string' ? current : ''} placeholder={name === 'credential' ? 'Credential reference name' : undefined}
    onChange={event => change(event.target.value || undefined)} />
  return <JsonField label={name} value={current} change={change} />
}

function Inspector({ node, spec, step, change, duplicate, remove }: {
  node: NodeDefinition; spec?: NodeSpec; step?: Step; change: (patch: Partial<NodeDefinition>) => void
  duplicate: () => void; remove: () => void
}) {
  const [raw, setRaw] = useState(false)
  function config(name: string, value: Json | undefined) {
    const updated = { ...node.config }
    if (value === undefined) delete updated[name]
    else updated[name] = value
    change({ config: updated })
  }
  return <><div className="builder-panel-head"><Settings2 size={16} /><strong>Node settings</strong></div>
    <div className="inspector-scroll"><div className="inspect-title"><Glyph group={spec?.category ?? 'Utilities'} /><div><strong>{node.label}</strong><small>{spec?.category ?? node.type}</small></div></div>
    <label>Node name<input value={node.label} onChange={event => change({ label: event.target.value })} maxLength={100} /></label>
    <p className="field-help">{spec?.description}</p>
    <div className="inspect-section"><h4>Configuration</h4><button className="button small" onClick={() => setRaw(!raw)}>{raw ? 'Form' : 'JSON'}</button></div>
    {raw ? <JsonField label="Configuration JSON" value={node.config} change={value => {
      if (value && typeof value === 'object' && !Array.isArray(value)) change({ config: value as JsonObject })
    }} /> : Object.entries(spec?.schema.properties ?? {}).map(([name, schema]) => <label key={name}>
      <span>{name.replaceAll('_', ' ')}{spec?.schema.required?.includes(name) && ' *'}</span>
      <Field schema={schema} name={name} value={node.config[name]} change={value => config(name, value)} /></label>)}
    {!raw && !Object.keys(spec?.schema.properties ?? {}).length && <p className="field-help">This node needs no additional configuration.</p>}
    <div className="inspect-section"><h4>Execution settings</h4></div><div className="input-pair">
    <label>Retries<input type="number" min={0} max={3} value={node.retries} onChange={event => change({ retries: Number(event.target.value) })} /></label>
    <label>Timeout (s)<input type="number" min={0.05} max={60} step="any" value={node.timeout} onChange={event => change({ timeout: Number(event.target.value) })} /></label></div>
    <p className="field-help">Output ports · {spec?.ports.join(', ') || 'out'}</p><code className="node-reference">{node.id}</code>
    {step && <><div className="inspect-section"><h4>Latest execution</h4><Badge value={step.status} /></div>
      <details><summary>Inputs</summary><pre>{JSON.stringify(step.inputs, null, 2)}</pre></details>
      <details><summary>Output</summary><pre>{JSON.stringify(step.output, null, 2)}</pre></details>
      {step.error && <Notice error={step.error} />}</>}
    <div className="actions inspect-actions"><button className="button small" onClick={duplicate}><Copy size={14} /> Duplicate</button>
      <button className="icon-button danger" aria-label="Delete selected node" onClick={remove}><Trash2 size={16} /></button></div></div></>
}

export function BuilderRoute() {
  const { id } = useParams()
  const route = useApi<Workflow>('/workflows/' + (id ?? ''), 0, Boolean(id))
  if (!id) return <Builder key="new" />
  if (route.isPending) return <section className="workspace"><Loading /></section>
  if (!route.data) return <section className="workspace"><Notice error={route.error} /></section>
  return <Builder key={id} initial={route.data} />
}

function Builder({ initial }: { initial?: Workflow }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const toast = useToast(state => state.show)
  const [draft, setDraft] = useState<Draft>(initial ?? { name: 'Untitled workflow', description: '', definition: blankGraph })
  const [saved, setSaved] = useState<Workflow | undefined>(initial)
  const [selected, setSelected] = useState('')
  const [edge, setEdge] = useState('')
  const [filter, setFilter] = useState('')
  const [library, setLibrary] = useState(true)
  const [properties, setProperties] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [eventText, setEventText] = useState('{}')
  const [panel, setPanel] = useState<ReactNode>(null)
  const [undo, setUndo] = useState<Draft[]>([])
  const [redo, setRedo] = useState<Draft[]>([])
  const dragging = useRef(false)
  const specs = useApi<NodeSpec[]>('/nodes')
  const run = useApi<ExecutionDetails>('/executions/' + runId, 1200, Boolean(runId))
  const graph = draft.definition
  const selectedNode = graph.nodes.find(node => node.id === selected)
  const selectedSpec = specs.data?.find(node => node.type === selectedNode?.type)
  const nodeStatus = runId ? run.data?.nodes ?? [] : []
  const status = runId ? run.data?.status : undefined
  const dirty = !saved || JSON.stringify(draft.definition) !== JSON.stringify(saved.definition) || draft.name !== saved.name || draft.description !== saved.description
  const categories = [...new Set((specs.data ?? []).map(node => node.category))]
  const triggers = graph.nodes.filter(item => specs.data?.find(node => node.type === item.type)?.trigger)
  const manual = !triggers.length || triggers.some(node => node.type === 'manual')

  function remember() {
    setUndo(previous => [...previous.slice(-39), draft])
    setRedo([])
  }
  function commit(next: Draft) {
    if (next === draft) return
    remember()
    setDraft(next)
    setPanel(null)
  }
  function update(graph: Graph) {
    if (graph !== draft.definition) commit({ ...draft, definition: graph })
  }
  function goBack() {
    const previous = undo.at(-1)
    if (!previous) return
    setRedo(stack => [draft, ...stack])
    setDraft(previous)
    setUndo(undo.slice(0, -1))
  }
  function goForward() {
    if (!redo.length) return
    setUndo(stack => [...stack.slice(-39), draft])
    setDraft(redo[0])
    setRedo(redo.slice(1))
  }
  function add(spec: NodeSpec) {
    const node = createNode(spec, graph.nodes.length)
    update({ ...graph, nodes: [...graph.nodes, node] })
    setSelected(node.id)
    setEdge('')
    setProperties(true)
  }
  function remove(id: string) {
    update(removeNode(graph, id))
    setSelected('')
  }
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (event.target instanceof HTMLElement && (event.target.closest('input,textarea,select') || event.target.isContentEditable)) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) goForward()
        else goBack()
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (selectedNode) remove(selectedNode.id)
        else if (edge) { update({ ...graph, edges: graph.edges.filter(item => edgeId(item) !== edge) }); setEdge('') }
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  })

  function move(changes: NodeChange<ForgeNode>[]) {
    const positions = changes.filter(change => change.type === 'position' && change.position)
    if (!positions.length) return
    setDraft(previous => ({ ...previous, definition: { ...previous.definition,
      nodes: previous.definition.nodes.map(node => {
        const change = positions.find(item => item.type === 'position' && item.id === node.id)
        return change?.type === 'position' && change.position ? { ...node, ...change.position } : node
      }) } }))
  }
  function connect(connection: Connection) {
    try {
      update(attach(graph, { source: connection.source, target: connection.target, port: connection.sourceHandle ?? 'out' }, specs.data ?? []))
      setError(null)
    } catch (error) { setError(error) }
  }
  async function persist() {
    if (saved && !dirty) return saved
    const body = { name: draft.name, description: draft.description, definition: draft.definition, revision: saved?.revision }
    const data = await request<Workflow>(saved ? '/workflows/' + saved.id : '/workflows', saved ? 'PUT' : 'POST', body)
    setSaved(data)
    client.setQueryData(['/workflows/' + data.id], data)
    await client.invalidateQueries({ predicate: query => String(query.queryKey[0]).startsWith('/workflows?') || query.queryKey[0] === '/workflows' })
    return data
  }
  async function save() {
    setBusy(true); setError(null)
    try {
      const item = await persist()
      if (!initial) navigate('/builder/' + item.id, { replace: true })
      toast('Workflow saved')
    } catch (error) { setError(error) } finally { setBusy(false) }
  }
  async function validate() {
    setBusy(true); setError(null)
    try {
      const response = await request<{valid: boolean; errors: string[]}>('/validate', 'POST', graph)
      if (!response.valid) setError(response.errors.join('\n'))
      else toast('Workflow is valid')
    } catch (error) { setError(error) } finally { setBusy(false) }
  }
  async function launch() {
    setBusy(true); setError(null)
    try {
      const payload = JSON.parse(eventText)
      const checked = await request<{valid: boolean; errors: string[]}>('/validate', 'POST', graph)
      if (!checked.valid) throw new Error(checked.errors.join('\n'))
      const workflow = await persist()
      const result = await request<Execution>('/workflows/' + workflow.id + '/run', 'POST', { payload })
      setRunId(result.id)
      setPanel(null)
      toast('Workflow queued')
      if (!initial) navigate('/executions/' + result.id)
    } catch (error) { setError(error) } finally { setBusy(false) }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ name: draft.name, description: draft.description, definition: graph }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = (draft.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workflow') + '.json'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 500)
  }

  return <section className="builder-workspace"><div className="builder-top"><div><div className="builder-title"><GitBranch size={21} /><input aria-label="Workflow name" value={draft.name}
    maxLength={100} onChange={event => commit({ ...draft, name: event.target.value })} /></div>
    <p>{saved ? 'Revision ' + saved.revision : 'New draft'}{dirty ? ' · Unsaved changes' : ' · Saved'}</p></div>
    <div className="actions">
      <button className="icon-button" aria-label="Workflow settings" onClick={() => setSettingsOpen(true)}><Settings2 size={19} /></button>
      <button className="icon-button" aria-label="Export workflow JSON" onClick={download}><Download size={18} /></button>
      <button className="button" disabled={busy} onClick={validate}><ClipboardCheck size={16} /> Validate</button>
      <button className="button" disabled={busy} onClick={save}><Save size={16} /> Save</button>
      {manual ? <button className="button primary" disabled={busy} onClick={launch}><Play size={16} fill="currentColor" /> Run workflow</button>
      : <Link className="button primary" to="/schedules"><Play size={16} /> Manage triggers</Link>}
    </div></div>
    {error != null && <Notice error={error} />}{specs.isError && <Notice error={specs.error} />}
    {runId && <div className="builder-execution"><Badge value={status ?? 'QUEUED'} /><Link to={'/executions/' + runId}>Inspect execution</Link></div>}
    <div className={'builder-frame' + (!library ? ' hide-library' : '') + (!properties ? ' hide-properties' : '')}>
      {library && <aside className="builder-library"><div className="builder-panel-head"><Grid2X2 size={16} /><strong>Node library</strong>
        <button className="icon-button" title="Hide library" aria-label="Hide library" onClick={() => setLibrary(false)}><X size={16} /></button></div>
        <label className="filter-field"><Search size={15} /><input placeholder="Find a node…" aria-label="Find a node" value={filter} onChange={event => setFilter(event.target.value)} /></label>
        <div className="builder-library-scroll">{categories.map(category => {
          const items = specs.data?.filter(node => node.category === category && node.name.toLowerCase().includes(filter.toLowerCase())) ?? []
          return items.length ? <div key={category}><h3>{category}</h3>{items.map(item => <button className="library-node" key={item.type} title={item.description}
            onClick={() => add(item)}><Glyph group={item.category} size={15} /><span>{item.name}</span><Plus size={14} /></button>)}</div> : null
        })}</div></aside>}
      <div className="canvas"><div className="canvas-tools">
        {!library && <button className="icon-button" aria-label="Show node library" onClick={() => setLibrary(true)}><PanelLeft size={18} /></button>}
        <button className="icon-button" aria-label="Undo" disabled={!undo.length} onClick={goBack}><Undo2 size={18} /></button>
        <button className="icon-button" aria-label="Redo" disabled={!redo.length} onClick={goForward}><Redo2 size={18} /></button>
        <button className="icon-button" aria-label="Set execution payload" onClick={() => setPanel('payload')}><FileJson size={17} /></button>
        {!properties && <button className="icon-button" aria-label="Show node settings" onClick={() => setProperties(true)}><Settings2 size={18} /></button>}
        {edge && <button className="icon-button danger" aria-label="Remove connection" onClick={() => { update({ ...graph, edges: graph.edges.filter(item => edgeId(item) !== edge) }); setEdge('') }}><Trash2 size={16} /></button>}
      </div>
      <ReactFlow nodes={flowNodes(graph, specs.data ?? [], nodeStatus, selected)} edges={flowEdges(graph, edge)}
        nodeTypes={nodeTypes} onNodesChange={move} onConnect={connect}
        onNodeClick={(_, item) => { setSelected(item.id); setEdge(''); setProperties(true) }}
        onEdgeClick={(_, item) => { setEdge(item.id); setSelected('') }}
        onPaneClick={() => { setSelected(''); setEdge('') }}
        onNodeDragStart={() => { if (!dragging.current) remember(); dragging.current = true }}
        onNodeDragStop={() => { dragging.current = false }}
        fitView fitViewOptions={{ minZoom: .28, maxZoom: .95, padding: .23 }} minZoom={.15}
        deleteKeyCode={null} proOptions={{ hideAttribution: true }}>
        <Background gap={21} size={1} variant={BackgroundVariant.Dots} /><Controls /><MiniMap pannable zoomable nodeColor="var(--accent)" />
      </ReactFlow>
      {!graph.nodes.length && <div className="canvas-empty"><span className="blank-icon"><GitBranch size={29} /></span><h2>Start your workflow</h2>
        <p>Add a trigger, then connect the actions you want to run.</p>
        <button className="button primary" onClick={() => { const spec = specs.data?.find(node => node.type === 'manual'); if (spec) add(spec) }} disabled={!specs.data}><Plus size={17} /> Add manual trigger</button></div>}
      <div className="canvas-count">{graph.nodes.length} nodes <span>·</span> {graph.edges.length} connections</div></div>
      {properties && <aside className="builder-inspector">{selectedNode ? <Inspector key={selectedNode.id} node={selectedNode} spec={selectedSpec}
        step={nodeStatus.find(step => step.node_id === selectedNode.id)}
        change={patch => update({ ...graph, nodes: graph.nodes.map(item => item.id === selectedNode.id ? { ...item, ...patch } : item) })}
        duplicate={() => {
          const copy = { ...selectedNode, id: 'n' + crypto.randomUUID().replaceAll('-', '').slice(0, 12), x: selectedNode.x + 32, y: selectedNode.y + 86, label: selectedNode.label.slice(0, 90) + ' copy' }
          update({ ...graph, nodes: [...graph.nodes, copy] }); setSelected(copy.id)
        }} remove={() => remove(selectedNode.id)} /> : <><div className="builder-panel-head"><Settings2 size={16} /><strong>Node settings</strong>
          <button className="icon-button" aria-label="Hide node settings" onClick={() => setProperties(false)}><X size={16} /></button></div>
        <div className="inspector-empty"><CircleHelp size={23} /><h3>Select a node</h3><p>Configure its fields, ports, and execution settings.</p></div></>}</aside>}
    </div>
    {(settingsOpen || panel === 'payload') && <div className="overlay"><article className="dialog" role="dialog" aria-modal="true" aria-label={settingsOpen ? 'Workflow settings' : 'Manual trigger payload'}>
      <div className="section-head"><h2>{settingsOpen ? 'Workflow settings' : 'Manual trigger payload'}</h2>
        <button className="icon-button" aria-label="Close dialog" onClick={() => { setSettingsOpen(false); setPanel(null) }}><X size={20} /></button></div>
      <div className="pad form-stack">{settingsOpen ? <><label>Description<textarea value={draft.description} maxLength={2000}
        onChange={event => commit({ ...draft, description: event.target.value })} /></label><label>Workflow timeout (seconds)
        <input type="number" min={1} max={3600} value={graph.timeout} onChange={event => update({ ...graph, timeout: Number(event.target.value) })} /></label></>
        : <label>JSON payload<textarea className="code-field" rows={8} value={eventText} onChange={event => setEventText(event.target.value)} /></label>}
        <button className="button primary" onClick={() => { setSettingsOpen(false); setPanel(null) }}><Check size={16} /> Done</button></div>
    </article></div>}
  </section>
}
