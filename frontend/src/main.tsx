import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { App } from './app'
import { WorkspaceBoundary } from './ui'
import '@xyflow/react/dist/style.css'
import './style.css'

const client = new QueryClient({defaultOptions: { queries: { retry: false, staleTime: 1500 } }})

createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}>
  <BrowserRouter><WorkspaceBoundary><App /></WorkspaceBoundary></BrowserRouter>
</QueryClientProvider></StrictMode>)
