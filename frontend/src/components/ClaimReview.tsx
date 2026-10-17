import { useEffect, useRef, useState } from 'react';

import { ClaimDetails, ClaimProvenance } from './ClaimDetails';

type PendingClaim = {
  claim_id: string;
  subject_name: string;
  predicate: string;
  object_name: string | null;
  object_value: string | null;
  confidence: number;
  created_at: string;
  evidence_count: number;
};

type ReviewRecord = {
  id: string;
  claim_id: string;
  subject_name: string;
  predicate: string;
  object_name: string | null;
  object_value: string | null;
  decision: 'CONFIRMED' | 'REJECTED' | 'REOPENED';
  reviewer: string;
  reason: string;
  created_at: string;
};

type ClaimReviewProps = {
  apiRoot: string;
  namespace: string;
  onNamespaceChange: (namespace: string) => void;
  refreshVersion: number;
  onKnowledgeUpdated: () => void;
};

function claimLabel(claim: PendingClaim | ReviewRecord): string {
  return `${claim.subject_name} ${claim.predicate.replaceAll('_', ' ')} ${claim.object_name ?? claim.object_value ?? 'Unknown'}`;
}

export function ClaimReview({ apiRoot, namespace, onNamespaceChange, refreshVersion, onKnowledgeUpdated }: ClaimReviewProps) {
  const selectionRequest = useRef(0);
  const [pending, setPending] = useState<PendingClaim[]>([]);
  const [history, setHistory] = useState<ReviewRecord[]>([]);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<ClaimProvenance | null>(null);
  const [claimLoading, setClaimLoading] = useState(false);
  const [claimError, setClaimError] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    selectionRequest.current += 1;
    setSelectedClaimId(null);
    setSelectedClaim(null);
    setMessage('');
  }, [namespace]);

  useEffect(() => {
    const controller = new AbortController();
    if (!namespace.trim()) {
      setPending([]);
      setHistory([]);
      return () => controller.abort();
    }

    async function loadReviews() {
      try {
        const query = new URLSearchParams({ namespace: namespace.trim() });
        const [pendingResponse, historyResponse] = await Promise.all([
          fetch(`${apiRoot}/api/claim-reviews?${query}`, { signal: controller.signal }),
          fetch(`${apiRoot}/api/claim-reviews/history?${query}`, { signal: controller.signal }),
        ]);
        if (!pendingResponse.ok || !historyResponse.ok) throw new Error('Review queue unavailable');
        const [pendingClaims, reviewedClaims] = await Promise.all([
          pendingResponse.json() as Promise<PendingClaim[]>,
          historyResponse.json() as Promise<ReviewRecord[]>,
        ]);
        if (!controller.signal.aborted) {
          setPending(pendingClaims);
          setHistory(reviewedClaims);
        }
      } catch {
        if (!controller.signal.aborted) setMessage('Could not load claim reviews. Check the backend.');
      }
    }

    void loadReviews();
    return () => controller.abort();
  }, [apiRoot, namespace, refreshVersion]);

  async function selectClaim(claimId: string) {
    if (busy) return;
    const requestId = ++selectionRequest.current;
    setSelectedClaimId(claimId);
    setSelectedClaim(null);
    setClaimError('');
    setClaimLoading(true);
    setReason('');
    try {
      const response = await fetch(`${apiRoot}/api/graph/claims/${encodeURIComponent(claimId)}`);
      if (!response.ok) throw new Error('Claim evidence unavailable');
      const claim = await response.json() as ClaimProvenance;
      if (selectionRequest.current === requestId) setSelectedClaim(claim);
    } catch {
      if (selectionRequest.current === requestId) setClaimError('Could not load this claim’s evidence.');
    } finally {
      if (selectionRequest.current === requestId) setClaimLoading(false);
    }
  }

  async function submitDecision(decision: 'CONFIRMED' | 'REJECTED' | 'REOPENED') {
    const pendingClaim = pending.some((item) => item.claim_id === selectedClaimId);
    const reviewedClaim = history.some((item) => item.claim_id === selectedClaimId);
    if (!selectedClaimId || !reviewer.trim() || !reason.trim() || (decision === 'REOPENED' ? !reviewedClaim : !pendingClaim)) return;
    setBusy(true);
    setMessage('');
    try {
      const response = await fetch(`${apiRoot}/api/claim-reviews/${encodeURIComponent(selectedClaimId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ namespace: namespace.trim(), decision, reviewer: reviewer.trim(), reason: reason.trim() }),
      });
      if (!response.ok) {
        const error = await response.json() as { detail?: unknown };
        setMessage(typeof error.detail === 'string' ? error.detail : 'Could not save the review. Reload and try again.');
        return;
      }
      const record = await response.json() as ReviewRecord;
      setPending((items) => items.filter((item) => item.claim_id !== record.claim_id));
      setHistory((items) => [record, ...items].slice(0, 100));
      setSelectedClaim((claim) => claim?.claim_id === record.claim_id ? { ...claim, status: decision === 'REOPENED' ? 'PROPOSED' : decision } : claim);
      setReason('');
      setMessage(`Claim ${decision.toLowerCase()}. The decision was recorded.`);
      onKnowledgeUpdated();
    } catch {
      setMessage('Could not save the review. Check the backend and try again.');
    } finally {
      setBusy(false);
    }
  }

  const matchingEvidence = selectedClaimId !== null && selectedClaim?.claim_id === selectedClaimId;
  const canReview = matchingEvidence && pending.some((item) => item.claim_id === selectedClaimId);
  const canReopen = matchingEvidence && history.some((item) => item.claim_id === selectedClaimId) && selectedClaim !== null && ['CONFIRMED', 'REJECTED'].includes(selectedClaim.status);
  const hasCurrentUploadEvidence = selectedClaim?.evidence.some((item) => item.source_type === 'FILE_UPLOAD' && item.is_current !== false) ?? false;
  const displayedClaim = canReview && selectedClaim !== null
    ? { ...selectedClaim, evidence: selectedClaim.evidence.filter((item) => item.source_type === 'FILE_UPLOAD' && item.is_current !== false) }
    : selectedClaim;

  return (
    <section className="status-card review-card" aria-labelledby="claim-review-title">
      <p className="eyebrow">Human review</p>
      <h2 id="claim-review-title">Review uploaded claims</h2>
      <p className="muted">Uploaded facts start as proposed. Check the source text before confirming or rejecting a relationship.</p>
      <label className="review-namespace">Team namespace
        <input value={namespace} onChange={(event) => onNamespaceChange(event.target.value)} disabled={busy} />
      </label>
      {message && <p className="message" role="status">{message}</p>}

      <div className="review-layout">
        <div>
          <h3>Waiting for review ({pending.length})</h3>
          {pending.length === 0 ? <p className="muted">No current uploaded claims are waiting for review in this namespace.</p> : (
            <div className="review-list">
              {pending.map((claim) => (
                <button className="review-choice" aria-pressed={selectedClaimId === claim.claim_id} key={claim.claim_id} type="button" disabled={busy} onClick={() => void selectClaim(claim.claim_id)}>
                  <strong>{claimLabel(claim)}</strong>
                  <span>PROPOSED · {claim.evidence_count} current uploaded source{claim.evidence_count === 1 ? '' : 's'}</span>
                </button>
              ))}
            </div>
          )}

          <h3 className="review-history-title">Recorded decisions</h3>
          {history.length === 0 ? <p className="muted">No uploaded claims have been reviewed in this namespace.</p> : (
            <div className="review-list">
              {history.map((record) => (
                <button className="review-choice" aria-pressed={selectedClaimId === record.claim_id} key={record.id} type="button" disabled={busy} onClick={() => void selectClaim(record.claim_id)}>
                  <strong>{claimLabel(record)}</strong>
                  <span>{record.decision} by {record.reviewer} · {new Date(record.created_at).toLocaleString()}</span>
                  <span>Reason: {record.reason}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <aside className="review-detail">
          <ClaimDetails claim={displayedClaim} isLoading={claimLoading} error={claimError} />
          {(canReview || canReopen) && selectedClaim !== null && (
            <div className="review-form">
              {!hasCurrentUploadEvidence && <p className="message">Current uploaded evidence is required before reviewing this claim.</p>}
              <label>Your name (recorded with the decision)
                <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={120} disabled={busy} />
              </label>
              <label>Reason for this decision
                <textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} rows={3} disabled={busy} />
              </label>
              <div className="review-actions">
                {canReview && <button type="button" onClick={() => void submitDecision('CONFIRMED')} disabled={busy || !hasCurrentUploadEvidence || !reviewer.trim() || !reason.trim()}>Confirm</button>}
                {canReview && <button type="button" onClick={() => void submitDecision('REJECTED')} disabled={busy || !hasCurrentUploadEvidence || !reviewer.trim() || !reason.trim()}>Reject</button>}
                {canReopen && <button type="button" onClick={() => void submitDecision('REOPENED')} disabled={busy || !hasCurrentUploadEvidence || !reviewer.trim() || !reason.trim()}>Reopen for review</button>}
              </div>
              <p className="muted">This local POC records the name you enter; it does not verify your identity.</p>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
