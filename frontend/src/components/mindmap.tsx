import dagre from '@dagrejs/dagre'
import { Background, Controls, type Edge, type Node, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'

import type { MindMapResponse } from '@/client/types.gen'

const W = 190
const H = 56

function layout(data: MindMapResponse): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 90 })
  g.setDefaultEdgeLabel(() => ({}))
  data.nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }))
  data.edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)
  return {
    nodes: data.nodes.map((n) => {
      const p = g.node(n.id)
      return {
        id: n.id,
        position: { x: p.x - W / 2, y: p.y - H / 2 },
        data: { label: n.label },
        style: { width: W, height: H, fontSize: 13, borderRadius: 10, border: '1px solid var(--border)', background: 'var(--card)', color: 'var(--card-foreground)' },
        draggable: false,
      }
    }),
    edges: data.edges.map((e, i) => ({
      id: `${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      label: e.relation,
      labelStyle: { fontSize: 11 },
      labelBgStyle: { fill: 'var(--background)' },
    })),
  }
}

export function MindMap({ data }: { data: MindMapResponse }) {
  const { nodes, edges } = useMemo(() => layout(data), [data])
  const [selected, setSelected] = useState<string | null>(null)
  const node = data.nodes.find((n) => n.id === selected)

  if (data.nodes.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing to map yet. It appears once a lecture has been processed.</p>
  }
  return (
    <div className="space-y-3">
      <div className="h-[30rem] overflow-hidden rounded-md border">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesConnectable={false} onNodeClick={(_, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)}>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <p className="min-h-6 text-sm">
        {node ? (
          <>
            <strong>{node.label}</strong>: {node.summary}
          </>
        ) : (
          <span className="text-muted-foreground">Click a concept to read its summary.</span>
        )}
      </p>
    </div>
  )
}
