import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import { getDeviceLocation, getTopologyGraph } from '../api';
import SwitchPorts from '../components/topology/SwitchPorts';
import type { TopologyGraph, TopologyNode, TopologyRole } from '../types';
import { errorText } from '../lib/errors';
import {
  Network, Router, Laptop, Monitor, Printer, Phone, Server, HelpCircle, Share2, X, ArrowUpRight,
} from 'lucide-react';
import { formatDistanceToNowStrict } from 'date-fns';
import clsx from 'clsx';

const NODE_W = 190, NODE_H = 56;

const ROLE_ICON: Record<TopologyRole, typeof Network> = {
  switch: Network, router: Router, windows: Monitor, mac: Laptop, linux: Server, printer: Printer, phone: Phone,
  device: HelpCircle,
};

type NodeData = { node: TopologyNode; selected: boolean };

function DeviceNode({ data }: NodeProps<Node<NodeData>>) {
  const { node, selected } = data;
  const Icon = ROLE_ICON[node.role] ?? HelpCircle;
  const infra = node.kind === 'infrastructure';
  return (
    <div className={clsx('flex items-center gap-2.5 rounded-xl border px-3 py-2 shadow-sm w-[190px] bg-slate-900',
      selected ? 'border-indigo-500 ring-2 ring-indigo-500/30' : infra ? 'border-slate-600' : 'border-slate-700/70',
      node.kind === 'external' && 'border-dashed opacity-80')}>
      <Handle type="target" position={Position.Top} className="!bg-slate-500 !w-1.5 !h-1.5" />
      <span className={clsx('w-8 h-8 rounded-lg grid place-items-center shrink-0',
        infra ? 'bg-indigo-500/15 text-indigo-400' : 'bg-slate-700/40 text-slate-400')}>
        <Icon className="w-4 h-4" />
      </span>
      <span className="min-w-0">
        <span className="block text-xs font-semibold text-slate-100 truncate">{node.label}</span>
        <span className="block text-[10px] text-slate-500 truncate">{node.ip ?? (node.kind === 'external' ? 'not scanned' : node.role)}</span>
      </span>
      <Handle type="source" position={Position.Bottom} className="!bg-slate-500 !w-1.5 !h-1.5" />
    </div>
  );
}

const nodeTypes = { device: DeviceNode };

function layout(graph: TopologyGraph, selectedId: string | null): { nodes: Node<NodeData>[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: 30, ranksep: 90 });
  g.setDefaultEdgeLabel(() => ({}));
  graph.nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  graph.edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const nodes: Node<NodeData>[] = graph.nodes.map((n) => {
    const p = g.node(n.id);
    return { id: n.id, type: 'device', position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 },
             data: { node: n, selected: n.id === selectedId } };
  });
  const edges: Edge[] = graph.edges.map((e) => {
    const link = e.kind === 'link';
    const label = link ? [e.source_port, e.target_port].filter(Boolean).join(' ↔ ') : e.source_port ?? '';
    return {
      id: e.id, source: e.source, target: e.target, label: label || undefined,
      style: { stroke: link ? '#6366f1' : '#94a3b8', strokeWidth: link ? 2 : 1, strokeDasharray: link ? undefined : '4 3' },
      labelStyle: { fontSize: 10, fill: '#475569' }, labelBgStyle: { fill: '#f8fafc' },
      markerEnd: link ? undefined : { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#94a3b8' },
    };
  });
  return { nodes, edges };
}

function EndpointPanel({ node }: { node: TopologyNode }) {
  const { data } = useQuery({
    queryKey: ['device-location', node.device_id], queryFn: () => getDeviceLocation(node.device_id!), enabled: !!node.device_id,
  });
  const locs = (data?.data ?? []).filter((l) => !l.uplink);
  if (!locs.length) return <p className="text-sm text-slate-500">Not seen on an access port.</p>;
  return (
    <ul className="space-y-2">
      {locs.map((l) => (
        <li key={`${l.switch_id}-${l.port_id}-${l.mac}`} className="text-sm">
          <span className="text-slate-200">{l.switch} · {l.port}</span>
          <span className="block text-xs text-slate-500">VLAN {l.vlan ?? '—'} · {l.mac}</span>
        </li>
      ))}
    </ul>
  );
}

export default function Topology() {
  const [endpoints, setEndpoints] = useState(false);
  const [vlanText, setVlanText] = useState('');
  const vlan = /^\d+$/.test(vlanText) ? Number(vlanText) : null;
  const [selected, setSelected] = useState<string | null>(null);

  const { data, error, isLoading } = useQuery({
    queryKey: ['topology', endpoints, vlan], queryFn: () => getTopologyGraph(endpoints, vlan), retry: false,
  });
  const graph = data?.data;
  const flow = useMemo(() => (graph ? layout(graph, selected) : null), [graph, selected]);
  const node = graph?.nodes.find((n) => n.id === selected) ?? null;
  const unlicensed = (error as { response?: { status?: number } } | null)?.response?.status === 403;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <Share2 className="w-8 h-8 text-indigo-400" /> Network map
          </h1>
          <p className="text-slate-400 mt-1">
            Switches, routers and the links between them from LLDP / CDP, and which port each device is plugged into.
          </p>
        </div>
        {graph && (
          <div className="flex items-center gap-4">
            <label className="inline-flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" checked={endpoints} onChange={(e) => setEndpoints(e.target.checked)} className="accent-indigo-500" />
              Show connected devices
            </label>
            {endpoints && (
              <input value={vlanText} onChange={(e) => setVlanText(e.target.value)} placeholder="VLAN"
                className="w-24 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/60" />
            )}
          </div>
        )}
      </div>

      {graph && (
        <p className="text-sm text-slate-500">
          {graph.stats.infrastructure} switches & routers · {graph.stats.links} links · {graph.stats.macs.toLocaleString()} MAC addresses learned
          {graph.stats.external > 0 && ` · ${graph.stats.external} neighbours not scanned yet`}
          {graph.stats.last_collected && ` · updated ${formatDistanceToNowStrict(new Date(graph.stats.last_collected))} ago`}
          {graph.stats.endpoints_capped && ' · showing the first 500 devices; filter by VLAN to see more'}
        </p>
      )}

      {unlicensed && (
        <p className="text-sm text-slate-400 bg-slate-800/60 border border-slate-700/60 rounded-xl p-4">
          The network map needs the <b>topology</b> licence module. {errorText(error)}
        </p>
      )}
      {!unlicensed && error && <p className="text-sm text-rose-400">{errorText(error)}</p>}
      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {graph && graph.nodes.length === 0 && (
        <div className="bg-slate-800/80 border border-slate-700/50 rounded-2xl p-8 text-center">
          <Network className="w-10 h-10 mx-auto text-slate-600" />
          <p className="text-slate-200 font-medium mt-3">No topology collected yet</p>
          <p className="text-sm text-slate-500 mt-1 max-w-xl mx-auto">
            Add an SNMP credential under Scanning → Credentials, tick <b>SNMP</b> on a scan target that covers your switches and
            routers, and run it. Each switch's neighbours (LLDP/CDP) and MAC table, and each router's ARP table, are read
            automatically.
          </p>
          <Link to="/scanning" className="inline-flex items-center gap-1.5 mt-4 text-sm text-indigo-400 hover:text-indigo-300">
            Open Scanning <ArrowUpRight className="w-4 h-4" />
          </Link>
        </div>
      )}

      {flow && graph && graph.nodes.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_24rem] gap-5">
          <div className="h-[640px] bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
            <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} fitView minZoom={0.2}
              nodesConnectable={false} onNodeClick={(_e, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)}
              proOptions={{ hideAttribution: true }}>
              <Background gap={24} color="#e2e8f0" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-5 h-fit max-h-[640px] overflow-y-auto">
            {!node ? (
              <p className="text-sm text-slate-500">Select a switch to see its ports, or a device to see where it is plugged in.</p>
            ) : (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-base font-semibold text-slate-50 truncate">{node.label}</p>
                    <p className="text-xs text-slate-500">{[node.ip, node.model].filter(Boolean).join(' · ') || node.role}</p>
                  </div>
                  <button onClick={() => setSelected(null)} className="p-1 text-slate-500 hover:text-slate-200" aria-label="Close"><X className="w-4 h-4" /></button>
                </div>
                {node.device_id && (
                  <Link to={`/devices/${node.device_id}`} className="inline-flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300">
                    Open device <ArrowUpRight className="w-4 h-4" />
                  </Link>
                )}
                {node.kind === 'external' && (
                  <p className="text-sm text-slate-400">Seen as a neighbour but not scanned. Add its address to an SNMP scan target to include its own ports.</p>
                )}
                {node.kind === 'infrastructure' && <SwitchPorts deviceId={node.device_id!} />}
                {node.kind === 'endpoint' && <EndpointPanel node={node} />}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
