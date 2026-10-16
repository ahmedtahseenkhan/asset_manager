import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import clsx from 'clsx';

interface RelAsset { id: number; name: string; asset_tag: string }
interface RelEdge { id: number; label: string; asset: RelAsset }
type AssetNodeData = { asset: RelAsset; center: boolean };

const W = 200, H = 48;

function AssetNode({ data }: NodeProps<Node<AssetNodeData>>) {
  return (
    <div className={clsx('rounded-xl border px-3 py-2 w-[200px] bg-slate-900 cursor-pointer',
      data.center ? 'border-indigo-500 ring-2 ring-indigo-500/30' : 'border-slate-600 hover:border-slate-400')}>
      <Handle type="target" position={Position.Left} className="!bg-slate-500 !w-1.5 !h-1.5" />
      <span className="block text-xs font-semibold text-slate-100 truncate">{data.asset.name}</span>
      <span className="block text-[10px] font-mono text-slate-500">{data.asset.asset_tag}</span>
      <Handle type="source" position={Position.Right} className="!bg-slate-500 !w-1.5 !h-1.5" />
    </div>
  );
}

const nodeTypes = { asset: AssetNode };

/** One-hop CMDB graph around an asset: what it relates to (right) and what relates to it (left). */
export default function RelationshipGraph({ center, outgoing, incoming }: {
  center: RelAsset; outgoing: RelEdge[]; incoming: RelEdge[];
}) {
  const navigate = useNavigate();
  const flow = useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 20, ranksep: 120 });
    g.setDefaultEdgeLabel(() => ({}));
    const assets = new Map<number, RelAsset>([[center.id, center]]);
    [...outgoing, ...incoming].forEach((e) => assets.set(e.asset.id, e.asset));
    assets.forEach((_a, id) => g.setNode(String(id), { width: W, height: H }));
    const edges: Edge[] = [];
    const add = (from: number, to: number, label: string, key: string) => {
      g.setEdge(String(from), String(to));
      edges.push({ id: key, source: String(from), target: String(to), label,
                   labelStyle: { fontSize: 10, fill: '#475569' }, labelBgStyle: { fill: '#f8fafc' },
                   style: { stroke: '#6366f1' }, markerEnd: { type: MarkerType.ArrowClosed, color: '#6366f1' } });
    };
    outgoing.forEach((e) => add(center.id, e.asset.id, e.label, `o${e.id}`));
    incoming.forEach((e) => add(e.asset.id, center.id, e.label, `i${e.id}`));
    dagre.layout(g);
    const nodes: Node<AssetNodeData>[] = [...assets.values()].map((a) => {
      const p = g.node(String(a.id));
      return { id: String(a.id), type: 'asset', position: { x: p.x - W / 2, y: p.y - H / 2 },
               data: { asset: a, center: a.id === center.id } };
    });
    return { nodes, edges };
  }, [center, outgoing, incoming]);

  return (
    <div className="h-80 rounded-xl border border-slate-700/50 bg-slate-800/80 overflow-hidden">
      <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} fitView nodesConnectable={false}
        onNodeClick={(_e, n) => Number(n.id) !== center.id && navigate(`/assets/${n.id}`)}
        proOptions={{ hideAttribution: true }} />
    </div>
  );
}
