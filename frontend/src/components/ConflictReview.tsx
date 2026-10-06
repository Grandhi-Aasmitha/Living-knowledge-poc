import { FormEvent, useEffect, useState } from 'react';

import { API_ROOT } from '../config';

export type ConflictStatus = 'OPEN' | 'RESOLVED' | 'DISMISSED';
type ConflictResolutionType = 'KEEP_CLAIM' | 'BOTH_VALID' | 'CORRECTED';

type ConflictDetectionResult = {
  namespace: string;
  findings_detected: number;
  conflicts_created: number;
  conflicts_existing: number;
  conflicts_auto_cleared: number;
  open_conflicts: number;
};

type ConflictSummary = {
  id: string;
  rule_id: string;
  namespace: string;
  description: string;
  status: ConflictStatus;
  claim_count: number;
};

type ConflictEvidenceSummary = {
  id: string;
  excerpt: string | null;
  locator: string | null;
  source_type: string;
  source_title: string;
  document_title: string | null;
  document_version: number | null;
  chunk_locator: string | null;
};

type ConflictClaimDetail = {
  claim_id: string;
  subject_entity_id: string;
  subject_name: string;
  predicate: string;
  object_entity_id: string | null;
  object_name: string | null;
  status: string;
  confidence: number;
  evidence_count: number;
  evidence: ConflictEvidenceSummary[];
};

type ConflictDetail = ConflictSummary & {
  resolution_type: string | null;
  selected_claim_id: string | null;
  resolution_reason: string | null;
  claims: ConflictClaimDetail[];
};

type GraphNode = {
  id: string;
  label: string;
  entity_type: string;
};

type GraphResponse = {
  nodes: GraphNode[];
};

export function ConflictReview() {
  const [namespace, setNamespace] = useState('tstvs');
  const [conflicts, setConflicts] = useState<ConflictSummary[]>([]);
  const [selectedConflict, setSelectedConflict] = useState<ConflictDetail | null>(null);
  const [scanResult, setScanResult] = useState<ConflictDetectionResult | null>(null);
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [correctionSubjectId, setCorrectionSubjectId] = useState('');
  const [correctionObjectId, setCorrectionObjectId] = useState('');
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);

  async function loadConflicts() {
    setIsLoading(true);
    setMessage('');
    try {
      const response = await fetch(`${API_ROOT}/api/conflicts?namespace=${encodeURIComponent(namespace)}&status=OPEN`);
      if (!response.ok) {
        setMessage('Open conflicts are unavailable.');
        return;
      }
      const summaries = (await response.json()) as ConflictSummary[];
      setConflicts(summaries);
      if (summaries.length === 0) {
        setSelectedConflict(null);
      }
    } catch {
      setMessage('Open conflicts are unavailable.');
    } finally {
      setIsLoading(false);
    }
  }

  async function loadGraphNodes() {
    try {
      const response = await fetch(`${API_ROOT}/api/graph?namespace=${encodeURIComponent(namespace)}&max_nodes=500`);
      if (!response.ok) {
        return;
      }
      const graph = (await response.json()) as GraphResponse;
      setGraphNodes(graph.nodes);
    } catch {
      // Conflict review remains usable without correction choices.
    }
  }

  async function detectConflicts() {
    setIsDetecting(true);
    setScanResult(null);
    setMessage('');
    try {
      const response = await fetch(`${API_ROOT}/api/conflicts/detect?namespace=${encodeURIComponent(namespace)}`, { method: 'POST' });
      if (!response.ok) {
        setMessage('Conflict scan failed.');
        return;
      }
      setScanResult((await response.json()) as ConflictDetectionResult);
      await loadConflicts();
    } catch {
      setMessage('Conflict scan failed.');
    } finally {
      setIsDetecting(false);
    }
  }

  async function selectConflict(conflictId: string) {
    setMessage('');
    setReason('');
    setCorrectionSubjectId('');
    setCorrectionObjectId('');
    try {
      const response = await fetch(`${API_ROOT}/api/conflicts/${encodeURIComponent(conflictId)}`);
      if (!response.ok) {
        setMessage('Conflict details are unavailable.');
        return;
      }
      const detail = (await response.json()) as ConflictDetail;
      setSelectedConflict(detail);
      if (detail.rule_id === 'multiple-part-of-v1' && detail.claims[0]?.subject_entity_id !== undefined) {
        setCorrectionSubjectId(detail.claims[0].subject_entity_id);
      }
    } catch {
      setMessage('Conflict details are unavailable.');
    }
  }

  async function resolveConflict(decision: ConflictResolutionType, selectedClaimId?: string) {
    if (selectedConflict === null || reason.trim() === '') {
      setMessage('A resolution reason is required.');
      return;
    }

    const payload: Record<string, string> = {
      decision,
      reason: reason.trim(),
    };

    if (decision === 'KEEP_CLAIM' && selectedClaimId !== undefined) {
      payload.selected_claim_id = selectedClaimId;
    }

    if (decision === 'CORRECTED') {
      const predicate = selectedConflict.rule_id === 'multiple-owners-v1' ? 'OWNS' : 'PART_OF';
      payload.corrected_subject_entity_id = correctionSubjectId;
      payload.corrected_predicate = predicate;
      payload.corrected_object_entity_id = correctionObjectId;
    }

    setIsResolving(true);
    setMessage('');
    try {
      const response = await fetch(`${API_ROOT}/api/conflicts/${encodeURIComponent(selectedConflict.id)}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        setMessage(response.status === 409 ? 'This conflict has already been resolved.' : 'Conflict resolution failed.');
        return;
      }
      setMessage(decision === 'BOTH_VALID' ? 'Conflict dismissed as both valid.' : 'Conflict resolved.');
      setSelectedConflict(null);
      setReason('');
      await loadConflicts();
    } catch {
      setMessage('Conflict resolution failed.');
    } finally {
      setIsResolving(false);
    }
  }

  useEffect(() => {
    void loadConflicts();
    void loadGraphNodes();
  }, []);

  const teamOptions = graphNodes.filter((node) => node.entity_type === 'TEAM');
  const objectOptions = graphNodes.filter((node) => node.entity_type !== 'TEAM');

  return (
    <section className="status-card curator-card conflict-card">
      <p className="eyebrow">Phase 8</p>
      <h2>Knowledge Conflicts</h2>
      <div className="graph-filters">
        <label>
          Namespace
          <input value={namespace} onChange={(event) => setNamespace(event.target.value)} />
        </label>
        <button type="button" onClick={() => void loadConflicts()} disabled={isLoading || namespace.trim() === ''}>
          Reload Conflicts
        </button>
        <button type="button" onClick={() => void detectConflicts()} disabled={isDetecting || namespace.trim() === ''}>
          {isDetecting ? 'Scanning...' : 'Detect Conflicts'}
        </button>
      </div>

      {scanResult !== null && (
        <div className="scan-result">
          <strong>Conflict scan complete</strong>
          <span>Potential conflicts: {scanResult.findings_detected}</span>
          <span>New: {scanResult.conflicts_created}</span>
          <span>Existing: {scanResult.conflicts_existing}</span>
          <span>Auto-cleared: {scanResult.conflicts_auto_cleared}</span>
        </div>
      )}

      {message !== '' && <p className="message">{message}</p>}

      <div className="conflict-layout">
        <div className="gap-list">
          {conflicts.length === 0 ? (
            <p className="muted">No open conflicts for the selected namespace.</p>
          ) : (
            conflicts.map((conflict) => (
              <article className="gap-item" key={conflict.id}>
                <div>
                  <h3>{conflict.description}</h3>
                  <p>{conflict.rule_id}</p>
                  <span className="badge">{conflict.status}</span>
                  <p className="muted">Claims involved: {conflict.claim_count}</p>
                </div>
                <button type="button" onClick={() => void selectConflict(conflict.id)}>
                  Review
                </button>
              </article>
            ))
          )}
        </div>

        {selectedConflict !== null && (
          <aside className="conflict-details">
            <h3>{selectedConflict.description}</h3>
            <p className="muted">{selectedConflict.rule_id}</p>
            <div className="conflict-claims">
              {selectedConflict.claims.map((claim) => (
                <article className="claim-review" key={claim.claim_id}>
                  <h4>{claim.subject_name}</h4>
                  <p className="relationship-line">
                    {claim.predicate} → {claim.object_name ?? claim.object_entity_id}
                  </p>
                  <p>Status: {claim.status}</p>
                  <p>Confidence: {claim.confidence.toFixed(2)}</p>
                  <p>Evidence: {claim.evidence_count}</p>
                  <ul className="evidence-list">
                    {claim.evidence.map((evidence) => (
                      <li key={evidence.id}>
                        <strong>{evidence.source_type}</strong> — {evidence.source_title}
                        {evidence.document_title !== null && <span> · {evidence.document_title} v{evidence.document_version}</span>}
                        {evidence.locator !== null && <p>Locator: {evidence.locator}</p>}
                        {evidence.chunk_locator !== null && <p>Chunk: {evidence.chunk_locator}</p>}
                        {evidence.excerpt !== null && <blockquote>{evidence.excerpt}</blockquote>}
                      </li>
                    ))}
                  </ul>
                  <button type="button" onClick={() => void resolveConflict('KEEP_CLAIM', claim.claim_id)} disabled={isResolving || reason.trim() === ''}>
                    Keep this claim
                  </button>
                </article>
              ))}
            </div>

            <form className="answer-form" onSubmit={(event: FormEvent<HTMLFormElement>) => event.preventDefault()}>
              <label>
                Resolution reason
                <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain the human decision" />
              </label>
              <button type="button" onClick={() => void resolveConflict('BOTH_VALID')} disabled={isResolving || reason.trim() === ''}>
                Both are valid
              </button>

              <div className="correction-panel">
                <h4>Correct using existing entities</h4>
                {selectedConflict.rule_id === 'multiple-owners-v1' ? (
                  <label>
                    Owning team
                    <select value={correctionSubjectId} onChange={(event) => setCorrectionSubjectId(event.target.value)}>
                      <option value="">Select existing team</option>
                      {teamOptions.map((node) => (
                        <option value={node.id} key={node.id}>{node.label}</option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label>
                    Subject
                    <input value={correctionSubjectId} readOnly />
                  </label>
                )}
                <label>
                  Correct object
                  <select value={correctionObjectId} onChange={(event) => setCorrectionObjectId(event.target.value)}>
                    <option value="">Select existing entity</option>
                    {objectOptions.map((node) => (
                      <option value={node.id} key={node.id}>{node.label}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void resolveConflict('CORRECTED')}
                  disabled={isResolving || reason.trim() === '' || correctionSubjectId === '' || correctionObjectId === ''}
                >
                  Correct
                </button>
              </div>
            </form>
          </aside>
        )}
      </div>
    </section>
  );
}
