import { useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Activity, ArrowUpRight, BarChart3, BookOpen, Check, ChevronRight, CircleCheck, ClipboardList,
  Copy, Download, FileJson, FileText, GitBranch, KeyRound, Layers3, Play, Plus, Search, ShieldCheck,
  Timer, Upload, Workflow as WorkflowIcon, X, Zap } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { base, request, useApi } from './api'
import { usePreferences, useToast } from './app'
import { ExecutionGraph } from './builder'
import type { Approval, Execution, ExecutionDetails, Metrics, NodeSpec, Page, Template, Workflow } from './types'
import { Badge, date, duration, Empty, Glyph, Loading, Notice, Pager, titleCase } from './ui'

export function PageTitle({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <div className="page-title"><div><h1>{title}</h1><p>{description}</p></div>{children && <div className="page-actions">{children}</div>}</div>
}

function Start({ title = 'New workflow' }: { title?: string }) {
  return <Link className="button primary" to="/builder"><Plus size={17} />{title}</Link>
}

function ExecTable({ items, dense = false }: { items: Execution[]; dense?: boolean }) {
  return <div className="table-scroll"><table><thead><tr><th>Workflow</th><th>Status</th>{!dense && <th>Trigger</th>}<th>Started</th><th>Duration</th><th aria-label="Details" /></tr></thead>
    <tbody>{items.map(run => <tr key={run.id}><td><Link className="table-workflow" to={'/executions/' + run.id}>
      <Glyph group="Workflows" size={15} /><span><strong>{run.workflow_name}</strong><small>Run {run.id.slice(0, 8)}</small></span></Link></td>
      <td><Badge value={run.status}/></td>{!dense && <td>{titleCase(run.source)}</td>}
      <td>{date(run.started ?? run.created, true)}</td><td className="monospace">{duration(run.started, run.ended)}</td>
      <td><Link className="icon-button row-link" to={'/executions/' + run.id} aria-label={'Inspect ' + run.workflow_name}><ChevronRight size={17} /></Link></td></tr>)}</tbody></table></div>
}

const metricCards = [
  { label: 'Workflows', key: 'workflows', group: 'Workflows', note: 'Saved in this workspace' },
  { label: 'Total executions', key: 'total_executions', group: 'Executions', note: 'All recorded workflow runs' },
  { label: 'Success rate', key: 'success_rate', group: 'Files & Documents', note: 'Across completed executions' },
  { label: 'Pending approvals', key: 'pending_approvals', group: 'Approvals', note: 'Waiting for a decision' },
] as const

export function Overview({ monitoring = false }: { monitoring?: boolean }) {
  const query = useApi<Metrics>('/monitoring', 3000)
  const stats = query.data
  const statuses = Object.entries(stats?.statuses ?? {}).map(([name, count]) => ({ name: titleCase(name), count }))
  return <section className="workspace overview">
    <PageTitle title={monitoring ? 'Monitoring' : 'Overview'} description={monitoring ? 'Execution outcomes and worker activity.' : 'Manage workflows and review recent runs.'}><Start /></PageTitle>
    {!monitoring && <div className="hero">
      <div className="hero-copy"><div className="hero-label"><Zap size={13} /> AUTOMATION WORKSPACE</div>
      <h2>Build and run workflows</h2><p>Connect triggers, data transformations, and approval steps on the workflow canvas.</p>
      <div className="hero-actions"><Link to="/builder" className="button primary"><Play size={15} fill="currentColor" /> Open workflow builder</Link>
      <Link to="/templates" className="button hero-secondary"><Layers3 size={16} /> Browse templates</Link></div></div>
      <div className="hero-art" aria-hidden="true">
        <div className="art-link art-link-one" /><div className="art-link art-link-two" /><div className="art-link art-link-three" />
        <div className="mini-node art-a"><Glyph group="Triggers" /><div><strong>Manual trigger</strong><small>Start workflow</small></div></div>
        <div className="mini-node art-b"><Glyph group="Data Processing" /><div><strong>Process records</strong><small>Data processing</small></div></div>
        <div className="mini-node art-c"><Glyph group="Files & Documents" /><div><strong>Export results</strong><small>Files &amp; documents</small></div></div>
        <div className="mini-node art-d"><Glyph group="Logic & Control" size={15} /><div><strong>Review</strong></div></div>
      </div>
    </div>}
    {query.isError && <Notice error={query.error} />}
    <div className="metric-grid">{metricCards.map(card => {
      const value = stats?.[card.key]
      return <article className="card metric" key={card.key}><div className="metric-head"><Glyph group={card.group} /><span>{card.label}</span></div>
        <strong>{value == null ? '—' : card.key === 'success_rate' ? Math.round(value * 100) + '%' : value.toLocaleString()}</strong><small>{card.note}</small></article>
    })}</div>
    {monitoring && stats && <div className="overview-grid charts">
      <article className="card"><div className="section-head"><div><h2>Execution outcomes</h2><p>All persisted statuses</p></div><BarChart3 size={19} /></div>
        {statuses.length ? <div className="chart"><ResponsiveContainer width="100%" height={228}><BarChart data={statuses}><CartesianGrid vertical={false} stroke="var(--line)" /><XAxis dataKey="name" tick={{ fill: 'var(--muted)', fontSize: 12 }} /><YAxis allowDecimals={false} tick={{ fill: 'var(--muted)', fontSize: 12 }} /><Tooltip contentStyle={{ background: 'var(--panel)', borderColor: 'var(--line)', color: 'var(--text)' }}/><Bar dataKey="count" fill="var(--accent)" radius={[5,5,0,0]} /></BarChart></ResponsiveContainer></div>
          : <Empty title="No outcomes yet" detail="Run a workflow to populate the chart." />}</article>
      <article className="card"><div className="section-head"><div><h2>Engine activity</h2><p>From the execution database</p></div><Activity size={19} /></div>
        <dl className="stat-list"><div><dt>Active workflows</dt><dd>{stats.active_workflows}</dd></div><div><dt>Completed</dt><dd>{stats.completed}</dd></div>
          <div><dt>Failed or timed out</dt><dd>{stats.failed}</dd></div><div><dt>Average duration</dt><dd>{duration(0, stats.avg_duration)}</dd></div></dl></article>
    </div>}
    <div className={'overview-grid' + (monitoring ? ' wide' : '')}>
      <article className="card">
        <div className="section-head"><div><h2>Recent executions</h2><p>Latest activity across your workflows.</p></div><Link className="button subtle" to="/executions">View history <ChevronRight size={15} /></Link></div>
        {query.isPending ? <Loading /> : stats?.recent.length ? <ExecTable items={stats.recent.slice(0, monitoring ? 10 : 5)} dense />
          : query.isError ? null
          : <Empty title="No executions yet" detail="Run a saved workflow to see its status, duration, and results here."><Link className="button" to="/templates">Explore templates</Link></Empty>}
      </article>
      {!monitoring && <article className="card quick"><div className="section-head"><div><h2>Quick start</h2><p>Explore the studio.</p></div></div>
        {[{ link: '/templates', title: 'Start with a template', description: 'Import a complete workflow', group: 'Reporting' },
          { link: '/nodes', title: 'Explore the node library', description: 'See available actions and triggers', group: 'AI Processing' },
          { link: '/approvals', title: 'Review approvals', description: 'Resume paused workflows', group: 'Human Approval' }].map(item =>
          <Link className="quick-row" key={item.link} to={item.link}><Glyph group={item.group} /><span><strong>{item.title}</strong><small>{item.description}</small></span><ChevronRight size={15} /></Link>)}
      </article>}
    </div>
  </section>
}

export function Workflows() {
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [search, setSearch] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const path = '/workflows?limit=20&offset=' + offset
  const query = useApi<Page<Workflow>>(path)
  const client = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast(state => state.show)
  async function copy(id: string) {
    try {
      const workflow = await request<Workflow>('/workflows/' + id + '/duplicate', 'POST')
      await client.invalidateQueries({ predicate: query => String(query.queryKey[0]).startsWith('/workflows') })
      toast('Workflow duplicated')
      navigate('/builder/' + workflow.id)
    } catch (error) { setError(error) }
  }
  async function upload(file: File) {
    try {
      if (file.size > 1_048_576) throw new Error('Choose a workflow JSON smaller than 1 MiB.')
      const { name, description, definition } = JSON.parse(await file.text())
      const validation = await request<{ valid: boolean; errors: string[] }>('/validate', 'POST', definition)
      if (!validation.valid) throw new Error(validation.errors.join('\n'))
      const item = await request<Workflow>('/workflows', 'POST', { name, description, definition })
      await client.invalidateQueries({ predicate: query => String(query.queryKey[0]).startsWith('/workflows') })
      toast('Workflow imported')
      navigate('/builder/' + item.id)
    } catch (error) { setError(error) }
  }
  const items = (query.data?.items ?? []).filter(item => item.name.toLowerCase().includes(search.toLowerCase()))
  return <section className="workspace"><PageTitle title="My Workflows" description="Open, duplicate, or import saved automation drafts.">
    <input ref={input} type="file" accept=".json,application/json" hidden onChange={event => { if (event.target.files?.[0]) void upload(event.target.files[0]); event.target.value = '' }} />
    <button className="button" onClick={() => input.current?.click()}><Upload size={16} /> Import JSON</button><Start /></PageTitle>
    {error != null && <Notice error={error} />}{query.isError && <Notice error={query.error} />}
    <article className="card"><div className="section-head"><div><h2>Saved workflows</h2><p>{query.data?.total ?? 0} workflows in this workspace</p></div>
      <label className="filter-field"><Search size={16} /><input placeholder="Filter this page" aria-label="Filter workflows" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
    {query.isPending ? <Loading /> : items.length ? <div className="table-scroll"><table><thead><tr><th>Name</th><th>Nodes</th><th>Revision</th><th>Updated</th><th>Actions</th></tr></thead>
    <tbody>{items.map(item => <tr key={item.id}><td><Link className="table-workflow" to={'/builder/' + item.id}><Glyph group="Workflows" />
      <span><strong>{item.name}</strong><small>{item.description}</small></span></Link></td>
      <td>{item.definition.nodes.length}</td><td>v{item.revision}</td><td>{date(item.updated)}</td>
      <td><button className="icon-button" title="Duplicate workflow" aria-label={'Duplicate ' + item.name} onClick={() => copy(item.id)}><Copy size={16} /></button></td></tr>)}</tbody></table></div>
      : <Empty title={search ? 'No matching workflows' : 'No saved workflows'} detail="Create a workflow or import one from the template library." />}
    {query.data && <Pager {...query.data} change={setOffset} />}</article></section>
}

export function History() {
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const query = useApi<Page<Execution>>('/executions?limit=25&offset=' + offset + (status ? '&status=' + status : ''), 2000)
  return <section className="workspace"><PageTitle title="Execution History" description="Inspect persisted runs, node outputs, and generated artifacts." />
    {query.isError && <Notice error={query.error} />}<article className="card"><div className="section-head"><div><h2>Workflow runs</h2><p>{query.data?.total ?? 0} runs</p></div>
      <select aria-label="Filter by status" value={status} onChange={event => { setStatus(event.target.value); setOffset(0) }}><option value="">All statuses</option>
      {['QUEUED','RUNNING','WAITING_APPROVAL','SUCCEEDED','FAILED','TIMED_OUT','CANCELLED'].map(item => <option key={item} value={item}>{titleCase(item)}</option>)}</select></div>
    {query.isPending ? <Loading /> : query.data?.items.length ? <ExecTable items={query.data.items} />
      : <Empty title="No runs to display" detail="Executed workflows and their results appear here." />}
    {query.data && <Pager {...query.data} change={setOffset} />}</article></section>
}

export function Details() {
  const { id } = useParams()
  const query = useApi<ExecutionDetails>('/executions/' + id, 1200)
  const [active, setActive] = useState('')
  const [error, setError] = useState<unknown>(null)
  const navigate = useNavigate()
  const data = query.data
  const selected = data?.nodes.find(step => step.node_id === active) ?? data?.nodes.find(step => step.status !== 'SKIPPED')
  const canCancel = data && ['QUEUED','RUNNING','WAITING_APPROVAL'].includes(data.status)
  async function action(operation: string) {
    try {
      const result = await request<Execution>('/executions/' + id + '/' + operation, 'POST')
      if (result.id !== id) navigate('/executions/' + result.id)
      await query.refetch()
    } catch (error) { setError(error) }
  }
  async function downloadArtifact(identifier: string, filename: string) {
    setError(null)
    try {
      const response = await fetch(base + '/artifacts/' + identifier)
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : 'Artifact download failed.')
      }
      const url = URL.createObjectURL(await response.blob())
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { setError(error) }
  }
  if (query.isPending) return <section className="workspace"><Loading /></section>
  if (!data) return <section className="workspace"><Notice error={query.error} /></section>
  return <section className="workspace"><PageTitle title={data.workflow_name} description={'Run ' + data.id.slice(0, 8) + ' · Draft revision ' + data.revision}>
    <Link className="button" to="/executions">All runs</Link>{canCancel ? <button className="button" onClick={() => action('cancel')}>Cancel run</button>
    : data.status !== 'SUCCEEDED' && <button className="button primary" onClick={() => action('retry')}>Retry pinned version</button>}</PageTitle>
    {error != null && <Notice error={error} />}{data.error && <Notice error={data.error} />}
    <div className="run-summary card"><Badge value={data.status} /><span>Trigger <strong>{titleCase(data.source)}</strong></span>
      <span>Started <strong>{date(data.started, true)}</strong></span><span>Duration <strong>{duration(data.started, data.ended)}</strong></span></div>
    <div className="detail-grid">
      <article className="card"><div className="section-head"><div><h2>Execution graph</h2><p>Pinned workflow version</p></div><GitBranch size={18} /></div>
        <ExecutionGraph graph={data.definition} steps={data.nodes} select={setActive} /></article>
      <article className="card"><div className="section-head"><div><h2>Generated artifacts</h2><p>Files created by this run</p></div><FileText size={18} /></div>
        {data.artifacts.map(file => <a href={base + '/artifacts/' + file.id} className="quick-row" key={file.id} download={file.filename}
          onClick={event => { event.preventDefault(); void downloadArtifact(file.id, file.filename) }}>
          <Glyph group="Reporting" /><span><strong>{file.filename}</strong><small>{Math.max(1, Math.ceil(file.size / 1024))} KB</small></span><Download size={17} /></a>)}
        {!data.artifacts.length && <p className="muted pad">No files have been generated.</p>}
        {data.approvals.map(item => <Link className="quick-row" to="/approvals" key={item.id}><Glyph group="Human Approval" /><span><strong>{item.action}</strong><small>{item.decision ? titleCase(item.decision) : 'Pending review'}</small></span><ChevronRight size={16} /></Link>)}</article>
    </div>
    <article className="card timeline"><div className="section-head"><div><h2>Node timeline</h2><p>Select a node to inspect its inputs and output.</p></div><Activity size={19} /></div>
      <div className="timeline-grid"><div>{data.nodes.map(step => <button key={step.node_id} className={'step-row' + (selected?.node_id === step.node_id ? ' chosen' : '')}
        onClick={() => setActive(step.node_id)}><span>{data.definition.nodes.find(n => n.id === step.node_id)?.label ?? step.node_id}
        <small>{step.attempts} attempt{step.attempts === 1 ? '' : 's'} · {duration(step.started, step.ended)}</small></span><Badge value={step.status} /></button>)}</div>
        <div className="step-preview">{selected ? <><h3>{data.definition.nodes.find(n => n.id === selected.node_id)?.label}</h3>{selected.error && <Notice error={selected.error} />}
          <h4>Input</h4><pre>{JSON.stringify(selected.inputs, null, 2)}</pre><h4>Output {selected.port && <span>· {selected.port}</span>}</h4><pre>{JSON.stringify(selected.output, null, 2)}</pre></>
          : <p className="muted">Waiting for node checkpoints.</p>}</div></div></article>
  </section>
}

export function Library() {
  const query = useApi<NodeSpec[]>('/nodes')
  const [filter, setFilter] = useState('')
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState<NodeSpec>()
  const categories = [...new Set((query.data ?? []).map(node => node.category))]
  const items = (query.data ?? []).filter(node => (!category || node.category === category) &&
    (node.name + ' ' + node.description).toLowerCase().includes(filter.toLowerCase()))
  return <section className="workspace"><PageTitle title="Node Library" description="Explore the actions, control flow, and triggers available in your workspace." />
    <div className="filter-line"><label className="filter-field"><Search size={17} /><input aria-label="Search nodes" placeholder="Search nodes" value={filter} onChange={event => setFilter(event.target.value)} /></label>
      <select value={category} aria-label="Category" onChange={event => setCategory(event.target.value)}><option value="">All categories</option>{categories.map(name => <option key={name}>{name}</option>)}</select></div>
    {query.isPending && <Loading />}{query.isError && <Notice error={query.error} />}
    <div className="tiles">{items.map(node => <button className="card tile" key={node.type} onClick={() => setSelected(node)}><div className="tile-head"><Glyph group={node.category} /><small>{node.available ? node.category : 'Setup required'}</small></div><h3>{node.name}</h3><p>{node.description}</p><small>{node.input_kind} in · {node.output_kind} out</small></button>)}</div>
    {!items.length && !query.isPending && <Empty title="No matching nodes" detail="Change the category or search term." />}
    {selected && <div className="overlay" onClick={() => setSelected(undefined)}><article className="dialog" role="dialog" aria-modal="true" aria-label={selected.name} onClick={event => event.stopPropagation()}>
      <div className="section-head"><div><h2>{selected.name}</h2><p>{selected.category}</p></div><button className="icon-button" aria-label="Close node" onClick={() => setSelected(undefined)}><X size={20} /></button></div>
      <div className="pad"><p>{selected.description}</p><p>Output ports · {selected.ports.join(', ')}</p><pre>{JSON.stringify(selected.schema, null, 2)}</pre></div>
    </article></div>}</section>
}

export function Templates() {
  const query = useApi<Template[]>('/templates')
  const [selected, setSelected] = useState<Template>()
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const client = useQueryClient()
  const toast = useToast(state => state.show)
  async function useTemplate(template: Template) {
    setError(null)
    setBusy(true)
    try {
      const workflow = await request<Workflow>('/templates/' + template.id + '/import', 'POST')
      await client.invalidateQueries({ predicate: query => String(query.queryKey[0]).startsWith('/workflows') })
      toast('Template imported')
      navigate('/builder/' + workflow.id)
    } catch (error) { setError(error) } finally { setBusy(false) }
  }
  return <section className="workspace"><PageTitle title="Templates" description="Import a complete workflow and adapt it to your process." />
    {query.isPending && <Loading />}{query.isError && <Notice error={query.error} />}
    <div className="tiles templates">{query.data?.map(item => <article className="card tile" key={item.id}><div className="tile-head"><Glyph group={item.category} /><small>{item.category}</small></div>
      <h3>{item.name}</h3><p>{item.description}</p><div className="tile-footer"><span>{item.definition.nodes.length} nodes</span><button className="button" onClick={() => setSelected(item)}>Preview</button></div></article>)}</div>
    {selected && <div className="overlay" onClick={() => !busy && setSelected(undefined)}><article className="dialog template-dialog" role="dialog" aria-modal="true" aria-label={selected.name} onClick={event => event.stopPropagation()}>
      <div className="section-head"><div><h2>{selected.name}</h2><p>{selected.description}</p></div><button className="icon-button" aria-label="Close template" onClick={() => setSelected(undefined)}><X size={20} /></button></div>
      <ExecutionGraph graph={selected.definition} /><div className="pad">{error != null && <Notice error={error} />}
        <button className="button primary" disabled={busy} onClick={() => useTemplate(selected)}><Plus size={16} /> Import template</button></div>
    </article></div>}</section>
}

export function ApprovalPage() {
  const [offset, setOffset] = useState(0)
  const query = useApi<Page<Approval>>('/approvals?limit=15&offset=' + offset, 2000)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState('')
  const capabilities = useApi<Capabilities>('/system/capabilities')
  const [reviewerKey, setReviewerKey] = useState('')
  const toast = useToast(state => state.show)
  async function decide(id: string, decision: string) {
    setBusy(id)
    setError(null)
    try {
      const headers = reviewerKey ? { 'X-AgentForge-Reviewer': reviewerKey } : undefined
      await request('/approvals/' + id + '/decision', 'POST', { decision }, headers)
      setReviewerKey('')
      await query.refetch()
      toast('Decision recorded')
    } catch (error) { setError(error) } finally { setBusy('') }
  }
  return <section className="workspace"><PageTitle title="Approvals" description="Review proposed actions from paused workflow runs." />
    {capabilities.data?.approval_requires_key && <div className="filter-line"><label className="form-stack">Reviewer key
      <input type="password" autoComplete="off" value={reviewerKey} maxLength={200} onChange={event => setReviewerKey(event.target.value)} /></label></div>}
    {query.isError && <Notice error={query.error} />}{error != null && <Notice error={error} />}
    {query.isPending ? <Loading /> : <div className="approval-list">{query.data?.items.map(item => <article className="card approval-card" key={item.id}>
      <div className="section-head"><div className="table-workflow"><Glyph group="Human Approval" /><div><h2>{item.workflow_name}</h2><p>{item.action}</p></div></div><Badge value={item.decision ?? 'WAITING_APPROVAL'} /></div>
      <div className="pad"><div className="meta-line"><span>{item.reviewer}</span><span>Requested {date(item.created, true)}</span><span>Expires {date(item.expires, true)}</span></div>
      <details><summary>Review workflow context</summary><pre>{JSON.stringify(item.context, null, 2)}</pre></details>
      <div className="actions"><Link className="button" to={'/executions/' + item.execution_id}>Inspect run</Link>{!item.decision && <>
        <button className="button" disabled={busy === item.id} onClick={() => decide(item.id, 'REQUEST_CHANGES')}>Request changes</button>
        <button className="button" disabled={busy === item.id} onClick={() => decide(item.id, 'REJECT')}>Reject</button>
        <button className="button primary" disabled={busy === item.id} onClick={() => decide(item.id, 'APPROVE')}><Check size={16} /> Approve</button></>}</div></div>
    </article>)}</div>}
    {!query.isPending && !query.data?.items.length && <article className="card"><Empty title="Approval inbox is empty" detail="Workflow review requests will appear when an approval node pauses a run." /></article>}
    {query.data && <Pager {...query.data} change={setOffset} />}</section>
}

type ScheduleRow = { id: string; workflow_id: string; kind: string; expression: string; timezone: string; enabled: boolean; next_run: number | null; last_run: number | null; error: string | null }
type Hook = { id: string; workflow_id: string; credential: string }
type Credential = { name: string; kind: string; env_var: string }
type Provider = 'ollama' | 'openai'
type Capabilities = { browser_channel: string; browser_hosts: string[]; external_http: boolean; approved_hosts: string[]; ai_setup: Record<Provider, boolean>; distributed_worker: boolean; approval_requires_key: boolean }
type ProviderStatus = { configured: boolean; available: boolean; models: string[] }

export function Schedules() {
  const workflows = useApi<Page<Workflow>>('/workflows')
  const schedules = useApi<Page<ScheduleRow>>('/schedules', 3000)
  const hooks = useApi<Page<Hook>>('/webhooks')
  const credentials = useApi<Page<Credential>>('/credentials')
  const [kind, setKind] = useState('interval')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast(state => state.show)
  const workflowsFor = (trigger: string) => workflows.data?.items.filter(item => item.definition.nodes.some(node => node.type === trigger)) ?? []
  const name = (id: string) => workflows.data?.items.find(item => item.id === id)?.name ?? id.slice(0, 8)
  async function submit(event: FormEvent<HTMLFormElement>, target: string) {
    event.preventDefault()
    const form = event.currentTarget
    const data = Object.fromEntries(new FormData(form))
    setBusy(true)
    setError(null)
    try {
      await request(target, 'POST', data)
      await Promise.all([schedules.refetch(), hooks.refetch()])
      toast(target === '/schedules' ? 'Schedule created' : 'Webhook created')
    } catch (error) { setError(error) } finally { setBusy(false) }
  }
  async function toggle(row: ScheduleRow) {
    try { await request('/schedules/' + row.id, 'PATCH', { enabled: !row.enabled }); await schedules.refetch() }
    catch (error) { setError(error) }
  }
  return <section className="workspace"><PageTitle title="Schedules & Triggers" description="Start workflows from a clock, approved local files, or signed webhooks." />
    {error != null && <Notice error={error} />}{schedules.isError && <Notice error={schedules.error} />}{hooks.isError && <Notice error={hooks.error} />}
    <div className="detail-grid balanced"><form className="card settings-form" onSubmit={event => submit(event, '/schedules')}>
      <div className="section-head"><div><h2>Create schedule</h2><p>Select a workflow with the matching trigger.</p></div><Timer size={18} /></div>
      <div className="form-grid pad"><label>Trigger type<select name="kind" value={kind} onChange={event => setKind(event.target.value)}>
      <option value="interval">Interval</option><option value="cron">Cron</option><option value="once">One time</option><option value="file">File watch</option></select></label>
      <label>Workflow<select key={kind} name="workflow_id" required><option value="">Select workflow</option>{workflowsFor(kind === 'file' ? 'file_trigger' : 'schedule').map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>{kind === 'interval' ? 'Interval in seconds' : kind === 'once' ? 'ISO date and time' : kind === 'cron' ? 'Cron expression' : 'File extension'}
        <input name="expression" key={kind} required placeholder={kind === 'interval' ? '60' : kind === 'once' ? '2027-01-01T09:00:00' : kind === 'cron' ? '0 9 * * 1-5' : '.csv'} /></label>
      <label>Time zone<input name="timezone" defaultValue="UTC" required /></label>
      <button className="button primary" disabled={busy}><Plus size={16} /> Add schedule</button></div>
    </form><form className="card settings-form" onSubmit={event => submit(event, '/webhooks')}>
      <div className="section-head"><div><h2>Create webhook</h2><p>Every request requires a timestamped HMAC signature.</p></div><ShieldCheck size={18} /></div>
      <div className="form-grid pad"><label>Webhook workflow<select name="workflow_id" required><option value="">Select workflow</option>{workflowsFor('webhook').map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Webhook credential<select name="credential" required><option value="">Select reference</option>{credentials.data?.items.filter(item => item.kind === 'webhook').map(item => <option key={item.name}>{item.name}</option>)}</select></label>
      <button className="button primary" disabled={busy}><Plus size={16} /> Add webhook</button></div>
    </form></div>
    <article className="card list-card"><div className="section-head"><div><h2>Active definitions</h2><p>Registered schedules and webhook endpoints</p></div></div>
      {schedules.data?.items.map(row => <div className="quick-row" key={row.id}><Glyph group="Schedules" /><span><strong>{name(row.workflow_id)}</strong>
        <small>{titleCase(row.kind)} · {row.expression} · Next {date(row.next_run, true)} · Last {date(row.last_run, true)}{row.error ? ' · ' + row.error : ''}</small></span>
        <button className="button small" onClick={() => toggle(row)}>{row.enabled ? 'Disable' : 'Enable'}</button></div>)}
      {hooks.data?.items.map(hook => <div className="quick-row" key={hook.id}><Glyph group="Integrations" /><span><strong>{name(hook.workflow_id)}</strong><small className="monospace">{base}/hooks/{hook.id}</small></span></div>)}
      {!schedules.data?.items.length && !hooks.data?.items.length && <Empty title="No triggers configured" detail="Add a schedule or webhook to start workflows automatically." />}</article>
  </section>
}

export function Credentials() {
  const query = useApi<Page<Credential>>('/credentials')
  const [error, setError] = useState<unknown>(null)
  const [status, setStatus] = useState<Record<string, boolean>>({})
  const toast = useToast(state => state.show)
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    setError(null)
    try {
      await request('/credentials', 'POST', Object.fromEntries(new FormData(form)))
      form.reset()
      await query.refetch()
      toast('Credential reference saved')
    } catch (error) { setError(error) }
  }
  async function check(name: string) {
    try {
      const data = await request<{ configured: boolean }>('/credentials/' + name + '/status')
      setStatus(previous => ({ ...previous, [name]: data.configured }))
    } catch (error) { setError(error) }
  }
  return <section className="workspace"><PageTitle title="Credentials" description="Link workflow actions to secrets supplied in the backend environment." />
    {error != null && <Notice error={error} />}{query.isError && <Notice error={query.error} />}
    <form className="card settings-form" onSubmit={submit}><div className="section-head"><div><h2>Add reference</h2><p>Store the variable name. Set its value in the server environment.</p></div><KeyRound size={19} /></div>
    <div className="pad form-grid"><label>Reference name<input required name="name" placeholder="orders-api" pattern="[a-z][a-z0-9\-]{0,63}" /></label>
      <label>Type<select name="kind"><option value="bearer">Bearer token</option><option value="basic">Basic authentication</option><option value="api_key">API key</option><option value="webhook">Webhook secret</option><option value="ai">AI credential reference</option></select></label>
      <label>Environment variable<input required name="env_var" placeholder="AGENTFORGE_SECRET_ORDERS" pattern="AGENTFORGE_SECRET_[A-Z0-9_]+" /></label>
      <button className="button primary"><Plus size={16} /> Save reference</button></div></form>
    <article className="card list-card"><div className="section-head"><div><h2>Saved references</h2><p>{query.data?.total ?? 0} references</p></div></div>
      {query.data?.items.map(item => <div className="quick-row" key={item.name}><Glyph group="Human Approval" /><span><strong>{item.name}</strong><small>{item.env_var} · {titleCase(item.kind)}{status[item.name] !== undefined ? status[item.name] ? ' · Configured' : ' · Missing from environment' : ''}</small></span>
        <button className="button" onClick={() => check(item.name)}>Check configuration</button></div>)}
      {!query.data?.items.length && <Empty title="No credentials registered" detail="Add an environment reference for an HTTP integration or signed webhook." />}</article>
  </section>
}

export function Integrations() {
  const caps = useApi<Capabilities>('/system/capabilities')
  const workers = useApi<{ active_workers: number }>('/system/status', 4000)
  const [checked, setChecked] = useState(false)
  const [providerStates, setProviderStates] = useState<Partial<Record<Provider, ProviderStatus>>>({})
  const [pending, setPending] = useState<Provider>()
  const [error, setError] = useState<unknown>(null)
  const workerCount = workers.data?.active_workers
  const workerState = caps.data?.distributed_worker && workerCount != null
    ? workerCount + (workerCount === 1 ? ' active worker' : ' active workers')
    : caps.data?.distributed_worker ? 'Worker status unavailable' : 'Local executor active'
  async function checkProvider(provider: Provider) {
    setError(null)
    setPending(provider)
    try {
      const result = await request<ProviderStatus>('/system/ai/' + provider)
      setProviderStates(previous => ({ ...previous, [provider]: result }))
    } catch (failure) { setError(failure) } finally { setPending(undefined) }
  }
  const items = [
    { name: 'Deterministic text processing', group: 'AI Processing', detail: 'Summarize, classify, and extract fields locally.', state: 'Available', provider: undefined },
    { name: 'Playwright static pages', group: 'Browser Automation', detail: 'Extract bundled fixtures or approved static HTTPS pages in an offline browser.', state: caps.data?.browser_hosts.length ? caps.data.browser_hosts.join(', ') : 'Fixtures bundled', provider: undefined },
    { name: 'Public HTTPS', group: 'HTTP & APIs', detail: 'GET, pagination, and approval-gated POST.', state: caps.data?.external_http ? caps.data.approved_hosts.join(', ') : 'Host allowlist required', provider: undefined },
    ...([{ name: 'Ollama', provider: 'ollama' }, { name: 'OpenAI-compatible', provider: 'openai' }] as const).map(({ name, provider }) => {
      const health = providerStates[provider]
      return { name, provider, group: 'AI Processing', detail: health?.available ? (health.models.join(', ') || 'No configured model is available.') : 'Configure the model allowlist in the backend environment.',
        state: health ? health.available ? 'Reachable' : 'Unavailable' : caps.data?.ai_setup[provider] ? 'Configured' : 'Setup required' }
    }),
    { name: 'Distributed worker', group: 'Integrations', detail: 'PostgreSQL, Redis, and Celery execution.', state: workerState, provider: undefined },
    { name: 'Local exports', group: 'Files & Documents', detail: 'Download CSV, Excel, JSON, text, and PDF artifacts.', state: 'Available', provider: undefined },
  ]
  return <section className="workspace"><PageTitle title="Integrations" description="Inspect local capabilities and optional connections.">
    <button className="button" onClick={async () => { const result = await caps.refetch(); setChecked(result.isSuccess) }}><Activity size={17} /> Check configuration</button></PageTitle>
    {caps.isError && <Notice error={caps.error} />}{error != null && <Notice error={error} />}{checked && <p className="inline-success"><CircleCheck size={16} /> Backend capability configuration loaded.</p>}
    {caps.isPending && <Loading />}
    {caps.data && <div className="tiles">{items.map(item => <article className="card tile" key={item.name}><div className="tile-head"><Glyph group={item.group} /><small>{item.state}</small></div>
      <h3>{item.name}</h3><p>{item.detail}</p>{item.provider && <button className="button" disabled={pending !== undefined || !caps.data?.ai_setup[item.provider]}
        onClick={() => { if (item.provider) void checkProvider(item.provider) }}>Check {item.name}</button>}</article>)}</div>}
  </section>
}

export function SettingsPage() {
  const { theme, toggle } = usePreferences()
  const status = useApi<{ database: string; worker: string; version: string; mode: string }>('/system/status')
  return <section className="workspace"><PageTitle title="Settings" description="Manage appearance and inspect your local environment." />
    {status.isError && <Notice error={status.error} />}
    <div className="detail-grid balanced"><article className="card"><div className="section-head"><div><h2>Workspace appearance</h2><p>Stored in this browser.</p></div><Layers3 size={18} /></div>
      <div className="quick-row"><Glyph group="Workflows" /><span><strong>{titleCase(theme)} theme</strong><small>Current appearance</small></span><button className="button" onClick={toggle}>Switch theme</button></div></article>
    <article className="card"><div className="section-head"><div><h2>Local service</h2><p>AgentForge {status.data?.version}</p></div><ClipboardList size={18} /></div><dl className="stat-list">
      <div><dt>Database</dt><dd>{status.data?.database ?? '—'}</dd></div><div><dt>Worker</dt><dd>{status.data?.worker ?? '—'}</dd></div></dl>
      <a className="quick-row" href="/api/v1/system/status" target="_blank" rel="noreferrer"><Glyph group="Integrations" /><span><strong>System status JSON</strong><small>Live backend metadata</small></span><ArrowUpRight size={15} /></a></article></div>
    <article className="card list-card"><div className="section-head"><div><h2>Workspace resources</h2><p>Starter workflows and reference material</p></div><BookOpen size={18} /></div>
      <Link className="quick-row" to="/templates"><Glyph group="Reporting" /><span><strong>Workflow templates</strong><small>Import an offline example</small></span><ChevronRight size={15} /></Link>
      <Link className="quick-row" to="/nodes"><Glyph group="Utilities" /><span><strong>Node configuration schemas</strong><small>View documented inputs and outputs</small></span><FileJson size={17} /></Link></article>
  </section>
}
