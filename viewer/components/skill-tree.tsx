'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Dagre from '@dagrejs/dagre';
import {
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { LineageEdge } from '@/components/lineage-edge';
import { SkillNode, type SkillNodeData } from '@/components/skill-node';
import type { LineageGraph } from '@/lib/lineage-types';

const NODE_WIDTH = 260;
const NODE_HEIGHT_COLLAPSED = 88;
const NODE_HEIGHT_EXPANDED = 220;

const edgeTypes = { lineage: LineageEdge };
const nodeTypes = { skillNode: SkillNode };

function layoutGraph(
  graph: LineageGraph,
  expandedId: string | null
): { nodes: Node[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 48, ranksep: 72 });

  const flowNodes: Node[] = graph.nodes.map((n) => {
    const expanded = n.id === expandedId;
    const height = expanded ? NODE_HEIGHT_EXPANDED : NODE_HEIGHT_COLLAPSED;
    g.setNode(n.id, { width: NODE_WIDTH, height });
    return {
      id: n.id,
      type: 'skillNode',
      position: { x: 0, y: 0 },
      data: {
        ...n,
        expanded,
        onToggle: () => {},
      },
    };
  });

  const flowEdges: Edge[] = graph.edges.map((e) => {
    g.setEdge(e.source, e.target);
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'lineage',
    };
  });

  Dagre.layout(g);

  for (const node of flowNodes) {
    const pos = g.node(node.id);
    if (pos) {
      node.position = {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - (node.id === expandedId ? NODE_HEIGHT_EXPANDED : NODE_HEIGHT_COLLAPSED) / 2,
      };
    }
  }

  return { nodes: flowNodes, edges: flowEdges };
}

function SkillTreeInner({ graph }: { graph: LineageGraph }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const toggle = useCallback((id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const laidOut = useMemo(
    () => layoutGraph(graph, expandedId),
    [graph, expandedId]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(laidOut.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(laidOut.edges);

  useEffect(() => {
    const { nodes: nextNodes, edges: nextEdges } = layoutGraph(
      graph,
      expandedId
    );
    setNodes(
      nextNodes.map((n) => ({
        ...n,
        data: {
          ...(n.data as SkillNodeData),
          expanded: n.id === expandedId,
          onToggle: toggle,
        },
      }))
    );
    setEdges(nextEdges);
  }, [graph, expandedId, toggle, setNodes, setEdges]);

  if (graph.nodes.length === 0) {
    return (
      <p className="text-sm text-[var(--muted)] font-[family-name:var(--font-mono)] p-8 text-center">
        Lineage will appear after backfill or the first curator pass.
      </p>
    );
  }

  return (
    <div className="w-full h-[min(70vh,720px)] border border-[var(--border)] rounded bg-[var(--background)]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      />
    </div>
  );
}

export function SkillTree({ graph }: { graph: LineageGraph }) {
  return (
    <ReactFlowProvider>
      <SkillTreeInner graph={graph} />
    </ReactFlowProvider>
  );
}
