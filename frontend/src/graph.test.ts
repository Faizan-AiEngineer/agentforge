import { describe, expect, it } from 'vitest'
import { attach, blankGraph, edgeId, removeNode } from './graph'
import type { Graph, NodeSpec } from './types'

const spec = (type: string, trigger: string | null = null, ports = ['out']): NodeSpec => ({
  type, name: type, trigger, ports, category: 'Utilities', description: '', schema: {},
  available: true, input_kind: 'object', output_kind: 'object',
})
const specs = [spec('manual', 'manual'), spec('values'), spec('condition', null, ['true', 'false'])]
const graph: Graph = { ...blankGraph, nodes: specs.map(({ type }, index) => ({
  id: 'n' + index, type, label: type, x: index * 100, y: 0, retries: 0, timeout: 20, config: {},
})) }

describe('builder connections', () => {
  it('routes separately named branches and preserves stable edge IDs', () => {
    const wire = { source: 'n2', target: 'n1', port: 'true' }
    const edited = attach(graph, wire, specs)
    expect(edited.edges.map(edgeId)).toEqual(['n2:true:n1'])
    expect(attach(edited, wire, specs)).toBe(edited)
  })
  it('rejects cycles, invalid ports, and connections into triggers', () => {
    const edited = attach(graph, { source: 'n1', target: 'n2', port: 'out' }, specs)
    expect(() => attach(edited, { source: 'n2', target: 'n1', port: 'true' }, specs)).toThrow('cycle')
    expect(() => attach(graph, { source: 'n2', target: 'n1', port: 'out' }, specs)).toThrow('valid output port')
    expect(() => attach(graph, { source: 'n2', target: 'n0', port: 'true' }, specs)).toThrow('cannot receive')
  })
  it('cascades removal to connected edges', () => {
    const edited = attach(graph, { source: 'n0', target: 'n1', port: 'out' }, specs)
    expect(removeNode(edited, 'n1').edges).toHaveLength(0)
    expect(removeNode(edited, 'n1').nodes).toHaveLength(2)
  })
})
