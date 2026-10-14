import cytoscape, { Core, EdgeSingular, NodeSingular } from 'cytoscape';
import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';

import { ClaimDetails, ClaimProvenance } from './ClaimDetails';

type GraphNode = {
  id: string;
  label: string;
  entity_type: string;
  namespace: string;
  status: string;
  aliases?: string[];
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  predicate: string;
  claim_status: string;
  confidence: number;
  evidence_count: number;
};

type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
};

type RelationshipSummary = {
  direction: 'Incoming' | 'Outgoing';
  predicate: string;
  neighbor: string;
  claimStatus: string;
};

type SelectedEntity = GraphNode & {
  relationships: RelationshipSummary[];
};

type GraphExplorerProps = {
  apiRoot: string;
  refreshVersion?: number;
};

const COMMON_ENTITY_TYPES = ['SERVICE', 'TOPIC', 'TEAM', 'BUSINESS_CONCEPT', 'SYSTEM', 'API', 'DATABASE'];
const STATUS_OPTIONS = ['CONFIRMED', 'PROPOSED'];

export function GraphExplorer({ apiRoot, refreshVersion = 0 }: GraphExplorerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Core | null>(null);
  const [namespace, setNamespace] = useState('tstvs');
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>(STATUS_OPTIONS);
  const [entityType, setEntityType] = useState('');
  const [search, setSearch] = useState('');
  const [graph, setGraph] = useState<GraphResponse>({ nodes: [], edges: [], truncated: false });
  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<ClaimProvenance | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [claimLoading, setClaimLoading] = useState(false);
  const [claimError, setClaimError] = useState('');

  const nodeById = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);

  useEffect(() => {
    async function loadGraph() {
      setIsLoading(true);
      setError('');
      setSelectedEntity(null);
      setSelectedClaim(null);
      setClaimError('');

      const params = new URLSearchParams({ namespace: namespace.trim() || 'tstvs' });
      selectedStatuses.forEach((status) => params.append('statuses', status));
      if (entityType !== '') {
        params.append('entity_types', entityType);
      }

      try {
        const response = await fetch(`${apiRoot}/api/graph?${params.toString()}`);
        if (!response.ok) {
          setError('Knowledge graph is unavailable.');
          return;
        }
        setGraph((await response.json()) as GraphResponse);
      } catch {
        setError('Knowledge graph is unavailable.');
      } finally {
        setIsLoading(false);
      }
    }

    void loadGraph();
  }, [apiRoot, namespace, selectedStatuses, entityType, refreshVersion]);

  useEffect(() => {
    if (containerRef.current === null) {
      return undefined;
    }

    const instance = cytoscape({
      container: containerRef.current,
      elements: [
        ...graph.nodes.map((node) => ({ data: { id: node.id, label: node.label, entityType: node.entity_type } })),
        ...graph.edges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            predicate: edge.predicate,
            claimStatus: edge.claim_status,
            confidence: edge.confidence,
            evidenceCount: edge.evidence_count,
          },
        })),
      ],
      layout: { name: 'cose', animate: false },
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': '#94a3b8',
            color: '#e5eefb',
            'font-size': 11,
            'text-outline-color': '#0f172a',
            'text-outline-width': 2,
            'text-valign': 'center',
            'text-halign': 'center',
            width: 56,
            height: 56,
          },
        },
        { selector: 'node[entityType = "SERVICE"]', style: { 'background-color': '#60a5fa' } },
        { selector: 'node[entityType = "TOPIC"]', style: { 'background-color': '#34d399' } },
        { selector: 'node[entityType = "TEAM"]', style: { 'background-color': '#fbbf24' } },
        { selector: 'node[entityType = "BUSINESS_CONCEPT"]', style: { 'background-color': '#c084fc' } },
        { selector: 'node[entityType = "SYSTEM"]', style: { 'background-color': '#f472b6' } },
        { selector: 'node[entityType = "API"]', style: { 'background-color': '#22d3ee' } },
        { selector: 'node[entityType = "DATABASE"]', style: { 'background-color': '#fb7185' } },
        {
          selector: 'edge',
          style: {
            label: 'data(predicate)',
            width: '2px',
            'curve-style': 'bezier',
            'target-arrow-shape': 'triangle',
            'line-color': '#93c5fd',
            'target-arrow-color': '#93c5fd',
            color: '#dbeafe',
            'font-size': '10px',
            'text-background-color': '#0f172a',
            'text-background-opacity': 0.88,
            'text-background-padding': '3px',
          },
        },
        { selector: 'edge[claimStatus = "PROPOSED"]', style: { 'line-style': 'dashed' } },
        { selector: '.highlighted', style: { 'border-width': '4px', 'border-color': '#f8fafc', 'z-index': 20 } },
        { selector: '.selected-edge', style: { width: '4px', 'line-color': '#facc15', 'target-arrow-color': '#facc15' } },
      ],
    });

    graphRef.current = instance;
    instance.on('tap', 'node', (event) => selectNode(event.target as NodeSingular));
    instance.on('tap', 'edge', (event) => void selectEdge(event.target as EdgeSingular));

    return () => {
      instance.destroy();
      graphRef.current = null;
    };
  }, [graph]);

  function fitGraph() {
    graphRef.current?.fit(undefined, 40);
  }

  function relayoutGraph() {
    graphRef.current?.layout({ name: 'cose', animate: true }).run();
  }

  function toggleStatus(event: ChangeEvent<HTMLInputElement>) {
    const status = event.target.value;
    setSelectedStatuses((current) =>
      event.target.checked ? [...current, status] : current.filter((item) => item !== status),
    );
  }

  function selectNode(node: NodeSingular) {
    const graphNode = nodeById.get(node.id());
    if (graphNode === undefined) {
      return;
    }
    graphRef.current?.elements().removeClass('highlighted selected-edge');
    node.addClass('highlighted');
    graphRef.current?.center(node);
    const relationships = graph.edges
      .filter((edge) => edge.source === graphNode.id || edge.target === graphNode.id)
      .map((edge) => {
        const outgoing = edge.source === graphNode.id;
        const neighbor = nodeById.get(outgoing ? edge.target : edge.source);
        return {
          direction: outgoing ? 'Outgoing' : 'Incoming',
          predicate: edge.predicate,
          neighbor: neighbor?.label ?? (outgoing ? edge.target : edge.source),
          claimStatus: edge.claim_status,
        } satisfies RelationshipSummary;
      });
    setSelectedEntity({ ...graphNode, relationships });
    setSelectedClaim(null);
  }

  async function selectEdge(edge: EdgeSingular) {
    graphRef.current?.elements().removeClass('highlighted selected-edge');
    edge.addClass('selected-edge');
    setClaimLoading(true);
    setClaimError('');
    setSelectedClaim(null);

    try {
      const response = await fetch(`${apiRoot}/api/graph/claims/${encodeURIComponent(edge.id())}`);
      if (!response.ok) {
        setClaimError('Claim provenance is unavailable.');
        return;
      }
      setSelectedClaim((await response.json()) as ClaimProvenance);
    } catch {
      setClaimError('Claim provenance is unavailable.');
    } finally {
      setClaimLoading(false);
    }
  }

  function runSearch() {
    const query = search.trim().toLowerCase();
    if (query === '' || graphRef.current === null) {
      return;
    }
    const match = graph.nodes.find(
      (node) => node.label.toLowerCase().includes(query) || node.id.toLowerCase().includes(query)
        || node.aliases?.some((alias) => alias.toLowerCase().includes(query)),
    );
    if (match === undefined) {
      return;
    }
    const node = graphRef.current.getElementById(match.id);
    if (node.nonempty()) {
      selectNode(node);
    }
  }

  return (
    <section className="status-card graph-card" aria-labelledby="graph-title">
      <p className="eyebrow">Phase 5 Explorer</p>
      <h2 id="graph-title">Knowledge Graph</h2>

      <div className="graph-filters">
        <label>
          Namespace
          <input value={namespace} onChange={(event) => setNamespace(event.target.value)} />
        </label>
        <fieldset>
          <legend>Claim status</legend>
          {STATUS_OPTIONS.map((status) => (
            <label className="inline-option" key={status}>
              <input
                checked={selectedStatuses.includes(status)}
                type="checkbox"
                value={status}
                onChange={toggleStatus}
              />
              {status}
            </label>
          ))}
        </fieldset>
        <label>
          Entity type
          <select value={entityType} onChange={(event) => setEntityType(event.target.value)}>
            <option value="">All</option>
            {COMMON_ENTITY_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label>
          Search loaded graph
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, alias, or entity ID" />
        </label>
        <button type="button" onClick={runSearch}>
          Find
        </button>
      </div>

      <div className="graph-actions">
        <button type="button" onClick={fitGraph}>Fit Graph</button>
        <button type="button" onClick={relayoutGraph}>Re-layout</button>
      </div>

      {isLoading && <p className="muted">Loading graph...</p>}
      {error !== '' && <p className="message">{error}</p>}
      {graph.truncated && <p className="message">Graph is truncated at the node limit. Narrow filters to inspect more.</p>}
      {!isLoading && error === '' && graph.nodes.length === 0 && <p className="muted">No graph relationships match the selected filters.</p>}

      <div className="graph-layout">
        <div className="graph-container" ref={containerRef} aria-label="Knowledge graph visualization" />
        <aside className="graph-details">
          {selectedEntity === null ? (
            <p className="muted">Select a node to inspect entity relationships.</p>
          ) : (
            <article>
              <h3>{selectedEntity.label}</h3>
              <dl className="details-list">
                <div><dt>Type</dt><dd>{selectedEntity.entity_type}</dd></div>
                <div><dt>ID</dt><dd>{selectedEntity.id}</dd></div>
                <div><dt>Namespace</dt><dd>{selectedEntity.namespace}</dd></div>
                <div>
                  <dt>Also known as</dt>
                  <dd>{selectedEntity.aliases?.length ? selectedEntity.aliases.join(', ') : 'No alternate names learned yet.'}</dd>
                </div>
              </dl>
              <h3>Loaded relationships</h3>
              {selectedEntity.relationships.length === 0 ? (
                <p className="muted">No loaded relationships.</p>
              ) : (
                <ul className="relationship-list">
                  {selectedEntity.relationships.map((relationship) => (
                    <li key={`${relationship.direction}:${relationship.predicate}:${relationship.neighbor}`}>
                      <span>{relationship.direction}</span> {relationship.predicate} {relationship.neighbor}{' '}
                      <em>{relationship.claimStatus}</em>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          )}
          <ClaimDetails claim={selectedClaim} isLoading={claimLoading} error={claimError} />
        </aside>
      </div>
    </section>
  );
}
