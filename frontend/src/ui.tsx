import { Component, type ReactNode } from 'react'
import { Activity, Bell, Bot, Boxes, Cable, ChevronLeft, ChevronRight, CircleAlert, Clock3, CodeXml,
  FileText, GitBranch, Globe, Layers3, MousePointer2, Workflow as WorkflowIcon, ShieldCheck, Zap } from 'lucide-react'

export function titleCase(input: string) {
  return input.toLowerCase().split('_').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
}

export function date(seconds: number | null | undefined, full = false) {
  return seconds ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', ...(full ? { timeStyle: 'short' } : {}) })
    .format(seconds * 1000) : '—'
}

export function duration(start: number | null, end: number | null) {
  if (start === null || end === null) return '—'
  const seconds = Math.max(0, end - start)
  return seconds < 1 ? Math.round(seconds * 1000) + ' ms' : seconds.toFixed(1) + ' s'
}

export function Badge({ value }: { value: string }) {
  return <span className={'badge badge-' + value.toLowerCase()}><i />{titleCase(value)}</span>
}

const groupIcons = {
  'Triggers': [Zap, 'amber'],
  'HTTP & APIs': [Globe, 'blue'],
  'Data Processing': [Layers3, 'violet'],
  'Logic & Control': [GitBranch, 'amber'],
  'Files & Documents': [FileText, 'mint'],
  'Human Approval': [ShieldCheck, 'rose'],
  'AI Processing': [Bot, 'violet'],
  'Browser Automation': [MousePointer2, 'blue'],
  'Utilities': [CodeXml, 'blue'],
  'Reporting': [FileText, 'mint'],
  'Data operations': [Layers3, 'violet'],
  'Human approval': [ShieldCheck, 'rose'],
  'Browser automation': [Globe, 'blue'],
  'AI processing': [Bot, 'violet'],
  'Workflows': [WorkflowIcon, 'mint'],
  'Executions': [Activity, 'blue'],
  'Approvals': [Bell, 'amber'],
  'Schedules': [Clock3, 'violet'],
  'Integrations': [Cable, 'blue'],
} as const

export function Glyph({ group, size = 18 }: { group: string; size?: number }) {
  const [Icon, color] = groupIcons[group as keyof typeof groupIcons] ?? [Boxes, 'mint']
  return <span className={'glyph ' + color}><Icon size={size} strokeWidth={1.85} /></span>
}

export function Empty({ title, detail, children }: { title: string; detail: string; children?: ReactNode }) {
  return <div className="empty"><Glyph group="Workflows" /><h3>{title}</h3><p>{detail}</p>{children}</div>
}

export function Notice({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error)
  return <div className="notice" role="alert"><CircleAlert size={18} /><span>{message}</span></div>
}

export function Loading() {
  return <div className="loading" aria-live="polite"><span className="spinner" /> Loading workspace…</div>
}

export function Pager({ offset, limit, total, change }: {
  offset: number; limit: number; total: number; change: (offset: number) => void
}) {
  if (total <= limit) return null
  return <div className="pager"><span>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
    <button className="icon-button" aria-label="Previous page" disabled={offset === 0} onClick={() => change(offset - limit)}><ChevronLeft size={17} /></button>
    <button className="icon-button" aria-label="Next page" disabled={offset + limit >= total} onClick={() => change(offset + limit)}><ChevronRight size={17} /></button></div>
}

export class WorkspaceBoundary extends Component<{ children: ReactNode }, { error?: Error }> {
  state: { error?: Error } = {}

  static getDerivedStateFromError(error: Error) { return { error } }

  render() {
    if (this.state.error) return <section className="workspace"><Notice error={this.state.error} />
      <button className="button" onClick={() => location.reload()}>Reload workspace</button></section>
    return this.props.children
  }
}
