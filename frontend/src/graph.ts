import type { Graph, NodeDefinition, NodeSpec, Wire } from './types'

export const blankGraph: Graph = { schema_version: 1, nodes: [], edges: [], timeout: 300 }

export function attach(graph: Graph, wire: Wire, specs: NodeSpec[]) {
  const source = graph.nodes.find(node => node.id === wire.source)
  const target = graph.nodes.find(node => node.id === wire.target)
  if (!source || !target || wire.source === wire.target) throw new Error('Connect two different nodes.')
  if (specs.find(spec => spec.type === target.type)?.trigger) throw new Error('A trigger cannot receive a connection.')
  if (!specs.find(spec => spec.type === source.type)?.ports.includes(wire.port)) throw new Error('Select a valid output port.')
  if (graph.edges.some(edge => edgeId(edge) === edgeId(wire))) return graph
  const pending = [wire.target]
  const seen = new Set<string>()
  for (const id of pending) {
    if (id === wire.source) throw new Error('This connection would create a cycle.')
    if (seen.has(id)) continue
    seen.add(id)
    pending.push(...graph.edges.filter(edge => edge.source === id).map(edge => edge.target))
  }
  return { ...graph, edges: [...graph.edges, wire] }
}

export function edgeId(wire: Wire) { return [wire.source, wire.port, wire.target].join(':') }

export function removeNode(graph: Graph, id: string) {
  return { ...graph, nodes: graph.nodes.filter(node => node.id !== id), edges: graph.edges.filter(edge => edge.source !== id && edge.target !== id) }
}

export function createNode(spec: NodeSpec, index: number): NodeDefinition {
  return { id: 'n' + crypto.randomUUID().replaceAll('-', '').slice(0, 12), type: spec.type, label: spec.name,
    x: 55 + (index % 4) * 230, y: 100 + Math.floor(index / 4) * 145,
    config: {}, retries: 0, timeout: spec.category === 'Browser Automation' ? 45 : 20 }
}
