import { useEffect, useState } from 'react';

type Entity = { id: string; canonical_name: string; entity_type: string; aliases: string[] };
type Candidate = { first: Entity; second: Entity; similarity: number };
type MergeResult = { claims_updated: number; gaps_updated: number; mentions_updated: number };

type Props = {
  apiRoot: string;
  namespace: string;
  refreshVersion: number;
  onKnowledgeUpdated: () => void;
};

export function EntityMergeReview({ apiRoot, namespace, refreshVersion, onKnowledgeUpdated }: Props) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [manualFirstId, setManualFirstId] = useState('');
  const [manualSecondId, setManualSecondId] = useState('');
  const [keepId, setKeepId] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => { setMessage(''); }, [namespace]);

  useEffect(() => {
    const controller = new AbortController();
    setSelected(null);
    setManualFirstId('');
    setManualSecondId('');
    if (!namespace.trim()) {
      setCandidates([]);
      setEntities([]);
      return () => controller.abort();
    }
    async function load() {
      try {
        const query = `namespace=${encodeURIComponent(namespace.trim())}`;
        const [suggestionsResponse, entitiesResponse] = await Promise.all([
          fetch(`${apiRoot}/api/entities/duplicates?${query}`, { signal: controller.signal }),
          fetch(`${apiRoot}/api/entities/active?${query}`, { signal: controller.signal }),
        ]);
        if (!suggestionsResponse.ok || !entitiesResponse.ok) throw new Error('Could not load identities');
        const [suggestions, activeEntities] = await Promise.all([
          suggestionsResponse.json() as Promise<Candidate[]>, entitiesResponse.json() as Promise<Entity[]>,
        ]);
        if (!controller.signal.aborted) { setCandidates(suggestions); setEntities(activeEntities); }
      } catch {
        if (!controller.signal.aborted) setMessage('Could not load duplicate suggestions.');
      }
    }
    void load();
    return () => controller.abort();
  }, [apiRoot, namespace, refreshVersion]);

  function choosePair(first: Entity, second: Entity) {
    setSelected({ first, second, similarity: 0 });
    setKeepId(first.id);
    setReason('');
  }

  async function approveMerge() {
    if (!selected || !keepId || !reviewer.trim() || !reason.trim()) return;
    setBusy(true);
    setMessage('');
    const duplicateId = keepId === selected.first.id ? selected.second.id : selected.first.id;
    try {
      const response = await fetch(`${apiRoot}/api/entities/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ namespace: namespace.trim(), keep_id: keepId, duplicate_id: duplicateId, reviewer: reviewer.trim(), reason: reason.trim() }),
      });
      if (!response.ok) {
        const error = await response.json() as { detail?: unknown };
        setMessage(typeof error.detail === 'string' ? error.detail : 'Merge failed. Reload and try again.');
        return;
      }
      const result = await response.json() as MergeResult;
      setMessage(`Merge saved. Reconnected ${result.claims_updated} claims, ${result.gaps_updated} gaps, and ${result.mentions_updated} saved mentions.`);
      setSelected(null);
      setManualFirstId('');
      setManualSecondId('');
      setReason('');
      onKnowledgeUpdated();
    } catch {
      setMessage('Merge failed. Check the backend and try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="status-card review-card" aria-labelledby="entity-merge-title">
      <p className="eyebrow">Identity review</p>
      <h2 id="entity-merge-title">Review possible duplicate names</h2>
      <p className="muted">Suggestions compare names of the same entity type in this namespace. Review the names before merging: a similar name can refer to a different thing. Claims and source evidence remain available after an approved merge.</p>
      {message && <p className="message" role="status">{message}</p>}
      {candidates.length === 0 ? <p className="muted">No likely duplicates found in this namespace.</p> : (
        <div className="review-list">
          {candidates.map((candidate) => (
            <button key={`${candidate.first.id}:${candidate.second.id}`} className="review-choice" type="button" disabled={busy} aria-pressed={selected?.first.id === candidate.first.id && selected?.second.id === candidate.second.id} onClick={() => { setSelected(candidate); setKeepId(candidate.first.id); setReason(''); setManualFirstId(''); setManualSecondId(''); }}>
              <strong>{candidate.first.canonical_name} ↔ {candidate.second.canonical_name}</strong>
              <span>{candidate.first.entity_type} · {Math.round(candidate.similarity * 100)}% name similarity</span>
            </button>
          ))}
        </div>
      )}
      <div className="answer-form">
        <h3>Choose another pair</h3>
        <p className="muted">Use this if two names refer to the same entity but their spelling is too different for a suggestion.</p>
        <label>First entity
          <select value={manualFirstId} disabled={busy} onChange={(event) => { setManualFirstId(event.target.value); setManualSecondId(''); setSelected(null); }}>
            <option value="">Choose an entity</option>
            {entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.canonical_name} ({entity.entity_type})</option>)}
          </select>
        </label>
        <label>Second entity of the same type
          <select value={manualSecondId} disabled={busy || !manualFirstId} onChange={(event) => {
            const first = entities.find((entity) => entity.id === manualFirstId);
            const second = entities.find((entity) => entity.id === event.target.value);
            setManualSecondId(event.target.value);
            if (first && second) choosePair(first, second);
          }}>
            <option value="">Choose an entity</option>
            {entities.filter((entity) => entity.id !== manualFirstId && entity.entity_type === entities.find((item) => item.id === manualFirstId)?.entity_type).map((entity) => <option key={entity.id} value={entity.id}>{entity.canonical_name}</option>)}
          </select>
        </label>
      </div>
      {selected && (
        <div className="answer-form">
          <h3>Approve this merge</h3>
          <p>Keep one name as the main entity. The other name becomes an alias.</p>
          <label>Main entity to keep
            <select value={keepId} onChange={(event) => setKeepId(event.target.value)} disabled={busy}>
              <option value={selected.first.id}>{selected.first.canonical_name}</option>
              <option value={selected.second.id}>{selected.second.canonical_name}</option>
            </select>
          </label>
          <label>Your name
            <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={120} disabled={busy} />
          </label>
          <label>Why these are the same thing
            <textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} rows={3} disabled={busy} />
          </label>
          <button type="button" onClick={() => void approveMerge()} disabled={busy || !reviewer.trim() || !reason.trim()}>{busy ? 'Saving merge…' : 'Approve merge'}</button>
        </div>
      )}
    </section>
  );
}
