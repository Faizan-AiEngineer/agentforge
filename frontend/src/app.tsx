import { useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Activity, Bell, Boxes, Cable, ChevronRight, CircleHelp, Command, GitFork, KeyRound, LayoutGrid,
  ListChecks, Menu, Moon, Plus, Search, Settings, Sun, Timer, X, Workflow as WorkflowIcon } from 'lucide-react'
import { create } from 'zustand'
import { useApi } from './api'
import { BuilderRoute } from './builder'
import { ApprovalPage, Credentials, Details, History, Integrations, Library, Overview, Schedules, SettingsPage,
  Templates, Workflows } from './pages'
import type { Metrics, Page, Workflow } from './types'

export const usePreferences = create<{theme: string; toggle: () => void}>(set => ({
  theme: localStorage.getItem('agentforge-theme') ?? 'dark',
  toggle: () => set(state => {
    const theme = state.theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem('agentforge-theme', theme)
    return { theme }
  }),
}))

export const useToast = create<{ text: string; show: (text: string) => void }>(set => ({
  text: '', show: text => set({ text }),
}))

const groups = [
  { name: 'WORKSPACE', items: [
    { title: 'Overview', path: '/', icon: LayoutGrid },
    { title: 'Workflow Builder', path: '/builder', icon: GitFork },
    { title: 'My Workflows', path: '/workflows', icon: WorkflowIcon },
    { title: 'Execution History', path: '/executions', icon: Activity },
  ] },
  { name: 'RESOURCES', items: [
    { title: 'Node Library', path: '/nodes', icon: Boxes },
    { title: 'Templates', path: '/templates', icon: LayoutGrid },
    { title: 'Integrations', path: '/integrations', icon: Cable },
  ] },
  { name: 'OPERATIONS', items: [
    { title: 'Schedules & Triggers', path: '/schedules', icon: Timer },
    { title: 'Approvals', path: '/approvals', icon: ListChecks },
    { title: 'Monitoring', path: '/monitoring', icon: Activity },
    { title: 'Credentials', path: '/credentials', icon: KeyRound },
    { title: 'Settings', path: '/settings', icon: Settings },
  ] },
]

const entries = groups.flatMap(group => group.items)

export function App() {
  const { theme, toggle } = usePreferences()
  const { text, show } = useToast()
  const [menu, setMenu] = useState(false)
  const [search, setSearch] = useState(false)
  const [term, setTerm] = useState('')
  const [notifications, setNotifications] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const system = useApi<{ mode: string; database: string }>('/system/status', 15000)
  const engine = system.data?.mode === 'distributed' ? 'Distributed engine' : 'Local engine'
  const database = system.data?.database === 'sqlite' ? 'SQLite' : system.data?.database === 'postgresql' ? 'PostgreSQL' : system.data?.database
  const metrics = useApi<Metrics>('/monitoring', 3000)
  const workflows = useApi<Page<Workflow>>('/workflows')
  const pending = metrics.data?.pending_approvals ?? 0
  const selected = entries.find(item => item.path === (location.pathname === '/' ? '/' : '/' + location.pathname.split('/')[1]))
  const openSearch = () => { setTerm(''); setSearch(true) }
  const matches = [
    ...entries.map(item => ({ title: item.title, path: item.path })),
    ...(workflows.data?.items ?? []).map(item => ({ title: item.name, path: '/builder/' + item.id })),
  ].filter(item => item.title.toLowerCase().includes(term.toLowerCase())).slice(0, 12)

  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => {
    if (!text) return
    const timer = setTimeout(() => show(''), 3300)
    return () => clearTimeout(timer)
  }, [text, show])
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setTerm('')
        setSearch(open => !open)
      }
      if (event.key === 'Escape') { setSearch(false); setNotifications(false); setMenu(false) }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])

  return <div className={'shell' + (menu ? ' mobile-open' : '')}>
    <aside className="sidebar">
      <Link className="brand" to="/" onClick={() => setMenu(false)}>
        <span className="brand-mark"><GitFork size={22} /></span><span>Agent<span>Forge</span><small>WORKFLOW STUDIO</small></span>
      </Link>
      <Link className="workspace-picker" to="/settings" onClick={() => setMenu(false)}>
        <span className="workspace-avatar">A</span><span><strong>AgentForge Studio</strong><small>Workspace settings</small></span><ChevronRight size={14} />
      </Link>
      <nav aria-label="Workspace navigation">
      {groups.map(group => <div className="nav-group" key={group.name}><div className="nav-heading">{group.name}</div>
        {group.items.map(({ path, icon: Icon, title }) => <NavLink key={path} to={path} end={path === '/'} onClick={() => setMenu(false)}>
          <Icon size={17} strokeWidth={1.8} /><span>{title}</span>{path === '/approvals' && pending > 0 && <em>{pending}</em>}
        </NavLink>)}</div>)}
      </nav>
      <div className="sidebar-footer">
        <div className={'system-dot' + (system.isError ? ' disconnected' : '')} />
        <div><strong>{system.isError ? 'Backend disconnected' : system.data ? engine + ' online' : 'Connecting…'}</strong><small>{database ? database + ' workspace' : 'AgentForge workspace'}</small></div>
        <Link to="/settings" aria-label="Workspace help"><CircleHelp size={17} /></Link>
      </div>
    </aside>
    {menu && <button className="mobile-shade" aria-label="Close navigation" onClick={() => setMenu(false)} />}
    <main>
      <header className="topbar">
        <button className="icon-button mobile-button" aria-label="Open navigation" onClick={() => setMenu(!menu)}><Menu size={21} /></button>
        <div className="breadcrumb"><span>Workspace</span><span className="slash">/</span><strong>{selected?.title ?? 'AgentForge'}</strong></div>
        <div className="top-actions">
          <button className="search-button" aria-label="Search workspace" onClick={openSearch}><Search size={16} /><span>Search workspace</span><kbd><Command size={11} /> K</kbd></button>
          <button className="icon-button top-icon" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={toggle}>{theme === 'dark' ? <Sun size={19} /> : <Moon size={18} />}</button>
          <button className="icon-button top-icon notify-button" aria-label="Notifications" aria-expanded={notifications} onClick={() => setNotifications(!notifications)}><Bell size={18} />{pending > 0 && <i />}</button>
          <Link className="operator" to="/settings" aria-label="Local operator">AF</Link>
          {notifications && <section className="notification card"><h3>Notifications</h3>
            <p>{pending ? pending + ' workflow approval' + (pending === 1 ? ' is' : 's are') + ' waiting for review.' : 'You’re up to date.'}</p>
            {pending > 0 && <Link to="/approvals" onClick={() => setNotifications(false)}>Open approvals</Link>}</section>}
        </div>
      </header>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/builder/:id?" element={<BuilderRoute />} />
        <Route path="/workflows" element={<Workflows />} />
        <Route path="/executions" element={<History />} />
        <Route path="/executions/:id" element={<Details />} />
        <Route path="/nodes" element={<Library />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="/integrations" element={<Integrations />} />
        <Route path="/schedules" element={<Schedules />} />
        <Route path="/approvals" element={<ApprovalPage />} />
        <Route path="/monitoring" element={<Overview monitoring />} />
        <Route path="/credentials" element={<Credentials />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<div className="workspace"><h1>Page unavailable</h1><Link to="/">Return to overview</Link></div>} />
      </Routes>
    </main>
    {search && <div className="overlay" onClick={() => setSearch(false)}>
      <div className="dialog search-dialog" role="dialog" aria-modal="true" aria-label="Search workspace" onClick={event => event.stopPropagation()}>
        <div className="dialog-search"><Search size={20} /><input autoFocus placeholder="Find a page or workflow…" value={term} onChange={event => setTerm(event.target.value)} aria-label="Search pages and workflows"
          onKeyDown={event => { if (event.key === 'Enter' && matches[0]) { navigate(matches[0].path); setSearch(false) } }} />
          <button className="icon-button" aria-label="Close search" onClick={() => setSearch(false)}><X size={18} /></button></div>
        <div className="search-results">{matches.map(item => <Link key={item.path} to={item.path} onClick={() => setSearch(false)}><WorkflowIcon size={16} />{item.title}</Link>)}
          {!matches.length && <p>No results found.</p>}<Link to="/builder" onClick={() => setSearch(false)}><Plus size={16} /> New workflow</Link></div>
      </div>
    </div>}
    {text && <div className="toast" role="status">{text}<button className="icon-button" aria-label="Dismiss notification" onClick={() => show('')}><X size={16} /></button></div>}
  </div>
}
