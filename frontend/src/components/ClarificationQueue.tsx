import { FormEvent, useEffect, useState } from 'react';

type Candidate = { entity_id: string; canonical_name: string; entity_type: string; aliases: string[]; description: string | null };
type Mention = {
  id: string; namespace: string; status: 'OPEN' | 'RESOLVED'; entity_id: string | null;
  observed: { name: string; entity_type: string; aliases: string[] };
  candidates: Candidate[]; reason: string | null; human_reason: string | null; method: string;
};
type Clarification = {
  mention: Mention; source_title: string; document_title: string | null;
  document_version: number | null; locator: string | null; excerpt: string; deferred_claims: number;
  application_pending?: boolean;
};
type EntityOption = { id: string; canonical_name: string; entity_type: string; aliases: string[] };

export function ClarificationQueue({ apiRoot, refreshVersion, onKnowledgeUpdated, namespace, onNamespaceChange }: { apiRoot: string; refreshVersion: number; onKnowledgeUpdated: () => void; namespace: string; onNamespaceChange: (value: string) => void }) {
  const [status, setStatus] = useState<'OPEN' | 'RESOLVED'>('OPEN');
  const [items, setItems] = useState<Clarification[]>([]);
  const [selected, setSelected] = useState<Clarification | null>(null);
  const [options, setOptions] = useState<EntityOption[]>([]);
  const [entityId, setEntityId] = useState('');
  const [decision, setDecision] = useState<'MATCH' | 'CREATE'>('MATCH');
  const [canonicalName, setCanonicalName] = useState('');
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setSelected(null);
    if (!namespace.trim()) { setItems([]); return () => controller.abort(); }
    setLoading(true);
    void fetch(`${apiRoot}/api/learning/clarifications?${new URLSearchParams({ namespace: namespace.trim(), status })}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load learning questions.');
        setItems(await response.json() as Clarification[]);
      })
      .catch((error: Error) => { if (!controller.signal.aborted) { setItems([]); setMessage(error.message); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [apiRoot, namespace, status, revision, refreshVersion]);

  useEffect(() => {
    const controller = new AbortController();
    setOptions([]);
    if (selected === null) return () => controller.abort();
    void fetch(`${apiRoot}/api/learning/entities?${new URLSearchParams({ namespace: selected.mention.namespace, entity_type: selected.mention.observed.entity_type })}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load entity choices.');
        setOptions(await response.json() as EntityOption[]);
      })
      .catch((error: Error) => { if (!controller.signal.aborted) setMessage(error.message); });
    return () => controller.abort();
  }, [apiRoot, selected]);

  function select(item: Clarification) {
    setSelected(item);
    setDecision('MATCH');
    setEntityId(item.mention.entity_id ?? '');
    setCanonicalName(item.mention.observed.name);
    setReason(item.mention.human_reason ?? '');
    setMessage('');
  }

  async function resolve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    setBusy(true);
    setMessage('');
    try {
      const response = await fetch(`${apiRoot}/api/learning/clarifications/${encodeURIComponent(selected.mention.id)}/resolve?${new URLSearchParams({ namespace: selected.mention.namespace })}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, entity_id: decision === 'MATCH' ? entityId : null, canonical_name: decision === 'CREATE' ? canonicalName.trim() : null, reason: reason.trim() }),
      });
      if (!response.ok) {
        const error = await response.json() as { detail?: unknown };
        throw new Error(typeof error.detail === 'string' ? error.detail : 'Could not record this decision.');
      }
      const result = await response.json() as { claims_applied: number; pending_mentions: number };
      setSelected(null);
      setRevision((value) => value + 1);
      onKnowledgeUpdated();
      setMessage(`Decision remembered. ${result.claims_applied} supported claim(s) applied; ${result.pending_mentions} mention(s) still need clarification in this source.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not resolve this identity.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="status-card curator-card clarification-card" aria-labelledby="clarification-title">
      <p className="eyebrow">Learning over time</p>
      <h2 id="clarification-title">Questions for the team</h2>
      <p className="muted">Help connect unfamiliar names to the right application or concept. Questions and original evidence are saved until the team resolves them or their source is replaced.</p>
      <div className="graph-filters">
        <label>Team namespace<input value={namespace} disabled={busy} onChange={(event) => { setMessage(''); onNamespaceChange(event.target.value); }} /></label>
        <label>Show<select value={status} disabled={busy} onChange={(event) => { setMessage(''); setStatus(event.target.value as 'OPEN' | 'RESOLVED'); }}><option value="OPEN">Needs clarification</option><option value="RESOLVED">Recorded decisions</option></select></label>
        <button type="button" disabled={busy || loading} onClick={() => setRevision((value) => value + 1)}>Refresh</button>
      </div>
      {loading && <p role="status" className="muted">Loading saved questions…</p>}
      {message && <p role="status" className="message">{message}</p>}
      {!loading && items.length === 0 && !message && <p className="muted">{status === 'OPEN' ? 'No saved identity questions for this team.' : 'No recorded identity decisions for this team.'}</p>}
      <div className="clarification-layout">
        <div className="resolution-list">
          {items.map((item) => (
            <button className="clarification-choice" type="button" key={item.mention.id} disabled={busy} aria-pressed={selected?.mention.id === item.mention.id} onClick={() => select(item)}>
              <strong>{item.mention.status === 'OPEN' ? `What does “${item.mention.observed.name}” refer to?` : item.mention.observed.name}</strong>
              <span>{item.mention.observed.entity_type.replaceAll('_', ' ')} · {item.document_title ?? item.source_title}</span>
              <span>{item.application_pending ? 'Decision saved; applying facts needs a retry' : item.mention.status === 'OPEN' ? `${item.deferred_claims} related claim(s) waiting` : `${item.mention.method === 'HUMAN' ? 'Team decision' : 'Recorded interpretation'}`}</span>
            </button>
          ))}
        </div>
        {selected && (
          <aside className="clarification-detail">
            <h3>{selected.mention.observed.name}</h3>
            <p className="muted">Source: {selected.document_title ?? selected.source_title}{selected.document_version !== null && ` · version ${selected.document_version}`}{selected.locator && ` · ${selected.locator}`}</p>
            {selected.mention.reason && <p className="muted">Why it was questioned: {selected.mention.reason}</p>}
            <details><summary>Read original evidence</summary><blockquote>{selected.excerpt}</blockquote></details>
            {selected.mention.status === 'RESOLVED' ? (
              <div><p>Resolved to {options.find((entity) => entity.id === selected.mention.entity_id)?.canonical_name ?? selected.mention.entity_id}.</p>{selected.mention.human_reason && <p>Team's reason: {selected.mention.human_reason}</p>}<p className="muted">Re-applying this same decision safely retries any waiting claims.</p></div>
            ) : selected.mention.candidates.length > 0 && (
              <div><h4>Possible matches</h4><ul className="compact-list">{selected.mention.candidates.map((candidate) => <li key={candidate.entity_id}><strong>{candidate.canonical_name}</strong> · {candidate.entity_type}{candidate.description && <p>{candidate.description}</p>}</li>)}</ul></div>
            )}
            <form className="answer-form" onSubmit={(event) => void resolve(event)}>
              {selected.mention.status === 'OPEN' && <label>This mention refers to<select value={decision} disabled={busy} onChange={(event) => setDecision(event.target.value as 'MATCH' | 'CREATE')}><option value="MATCH">An existing entity</option><option value="CREATE">A separate, new entity</option></select></label>}
              {decision === 'MATCH' ? <label>Canonical entity<select value={entityId} disabled={busy || selected.mention.status === 'RESOLVED'} onChange={(event) => setEntityId(event.target.value)}><option value="">Choose the correct entity</option>{options.map((entity) => <option value={entity.id} key={entity.id}>{entity.canonical_name} ({entity.entity_type})</option>)}</select></label> : <label>Canonical name<input value={canonicalName} disabled={busy} onChange={(event) => setCanonicalName(event.target.value)} /></label>}
              <label>Explain the decision<textarea value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} rows={3} placeholder="For example: Tactical STVS is the internal name for TSTVS System." /></label>
              <button disabled={busy || !reason.trim() || (decision === 'MATCH' ? !entityId : !canonicalName.trim())} type="submit">{busy ? 'Remembering decision…' : selected.mention.status === 'RESOLVED' ? 'Re-apply recorded decision' : 'Remember and apply'}</button>
            </form>
          </aside>
        )}
      </div>
    </section>
  );
}
