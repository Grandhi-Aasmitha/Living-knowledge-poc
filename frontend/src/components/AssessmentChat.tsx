import { FormEvent, useEffect, useState } from 'react';

type Finding = {
  stage: string;
  summary: string;
  completeness: 'FULL' | 'PARTIAL' | 'IN_PROGRESS';
  claim_ids: string[];
  evidence_ids: string[];
  outcome: 'MIGRATE' | 'MODERNIZE' | 'RETIRE' | 'RETAIN' | 'NEEDS_REVIEW' | null;
  risks: string[];
  prerequisites: string[];
};

type Assessment = {
  assessment_id: string;
  namespace: string;
  source_application: string;
  target_application: string | null;
  status: 'RUNNING' | 'WAITING_FOR_INPUT' | 'WAITING_FOR_REVIEW' | 'APPROVED';
  current_stage: string | null;
  question: string | null;
  findings: Finding[];
  clarifications: { stage: string; question: string; answer: string }[];
  review_history: { decision: string; reviewer: string; comment: string }[];
  evidence: { claim_id: string; subject: string; predicate: string; object: string | null; status: string; sources: {
    evidence_id: string; title: string; version: number | null; locator: string | null; excerpt: string | null;
  }[] }[];
  context_limited: boolean;
};

const stageLabel = (value: string) => value.replaceAll('_', ' ').toLowerCase();

export function AssessmentChat({ apiRoot, namespace }: { apiRoot: string; namespace: string }) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [source, setSource] = useState('');
  const [target, setTarget] = useState('');
  const [answer, setAnswer] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    setAssessment(null);
    setMessage('');
    if (!namespace.trim()) return;
    const id = window.localStorage.getItem(`assessment:${namespace.trim()}`);
    if (!id) return;
    let cancelled = false;
    void fetch(`${apiRoot}/api/assessments/${encodeURIComponent(id)}`).then(async (response) => {
      if (cancelled) return;
      if (response.ok) setAssessment(await response.json() as Assessment);
      else if (response.status === 404) window.localStorage.removeItem(`assessment:${namespace.trim()}`);
    }).catch(() => { if (!cancelled) setMessage('Saved assessment could not be loaded.'); });
    return () => { cancelled = true; };
  }, [apiRoot, namespace]);

  async function send(path: string, body: object) {
    setBusy(true);
    setMessage('');
    try {
      const response = await fetch(`${apiRoot}/api/assessments${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!response.ok) {
        const error = await response.json() as { detail?: string };
        setMessage(error.detail ?? `Assessment request failed (HTTP ${response.status}).`);
        return;
      }
      const next = await response.json() as Assessment;
      setAssessment(next);
      window.localStorage.setItem(`assessment:${next.namespace}`, next.assessment_id);
      setAnswer('');
      setComment('');
    } catch {
      setMessage('Could not connect to the assessment service.');
    } finally {
      setBusy(false);
    }
  }

  function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send('', { namespace: namespace.trim(), source_application: source.trim(), target_application: target.trim() || null });
  }

  function reply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (assessment) void send(`/${assessment.assessment_id}/answers`, { answer: answer.trim() });
  }

  function review(decision: 'APPROVE' | 'REVISE') {
    if (assessment) void send(`/${assessment.assessment_id}/review`, { decision, reviewer: reviewer.trim(), comment: comment.trim() });
  }

  return (
    <section className="status-card assessment-card" aria-labelledby="assessment-title">
      <p className="eyebrow">Application lifecycle advisor</p>
      <h2 id="assessment-title">Migration and retirement assessment</h2>
      <p className="muted">Assess an application using the claims and document evidence in the active namespace. Enter its exact knowledge graph name.</p>
      <form className="answer-form" onSubmit={start}>
        <label htmlFor="assessment-source">Source application or service</label>
        <input id="assessment-source" value={source} onChange={(event) => setSource(event.target.value)} placeholder="Exact name from the graph" maxLength={200} />
        <label htmlFor="assessment-target">Possible target (optional)</label>
        <input id="assessment-target" value={target} onChange={(event) => setTarget(event.target.value)} maxLength={200} />
        <button type="submit" disabled={busy || !namespace.trim() || !source.trim()}>{busy ? 'Assessing…' : 'Start new assessment'}</button>
      </form>
      {message && <p className="message" role="alert">{message}</p>}
      {assessment && <div className="assessment-thread">
        <p><strong>{assessment.source_application}</strong>{assessment.target_application ? ` → ${assessment.target_application}` : ''} · {assessment.status.replaceAll('_', ' ')}</p>
        {assessment.context_limited && <p className="message">The knowledge context reached its size limit. Review the evidence before approving.</p>}
        {assessment.clarifications.map((item, index) => <div className="assessment-exchange" key={`${item.stage}-${index}`}>
          <p><strong>Advisor:</strong> {item.question}</p><p><strong>You:</strong> {item.answer}</p>
        </div>)}
        {assessment.findings.map((finding) => <article className="assessment-finding" key={finding.stage}>
          <h3>{stageLabel(finding.stage)}</h3>
          <span className="badge">{finding.completeness}</span>
          {finding.outcome && <span className="badge">{finding.outcome.replaceAll('_', ' ')}</span>}
          <p>{finding.summary}</p>
          {finding.risks.length > 0 && <div><strong>Risks</strong><ul>{finding.risks.map((risk, index) => <li key={index}>{risk}</li>)}</ul></div>}
          {finding.prerequisites.length > 0 && <div><strong>Prerequisites</strong><ul>{finding.prerequisites.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
          {finding.claim_ids.length > 0 && <details><summary>Supporting knowledge ({finding.claim_ids.length} claims)</summary>
            {assessment.evidence.filter((row) => finding.claim_ids.includes(row.claim_id)).map((row) => <div key={row.claim_id} className="assessment-source">
              <strong>{row.subject} {row.predicate.replaceAll('_', ' ')} {row.object}</strong> <span className="badge">{row.status}</span>
              {row.sources.filter((sourceItem) => finding.evidence_ids.includes(sourceItem.evidence_id)).map((sourceItem) => <p key={sourceItem.evidence_id}>{sourceItem.title}{sourceItem.version ? `, v${sourceItem.version}` : ''}{sourceItem.locator ? ` · ${sourceItem.locator}` : ''}{sourceItem.excerpt ? ` — ${sourceItem.excerpt}` : ''}</p>)}
            </div>)}
          </details>}
        </article>)}
        {assessment.status === 'WAITING_FOR_INPUT' && <form className="answer-form" onSubmit={reply}>
          <p><strong>Advisor asks ({stageLabel(assessment.current_stage ?? '')}):</strong> {assessment.question}</p>
          <label htmlFor="assessment-answer">Your answer</label>
          <textarea id="assessment-answer" value={answer} onChange={(event) => setAnswer(event.target.value)} rows={3} maxLength={4000} placeholder="Give the detail, or say unknown" />
          <button type="submit" disabled={busy || !answer.trim()}>{busy ? 'Continuing…' : 'Answer and continue'}</button>
        </form>}
        {assessment.status === 'WAITING_FOR_REVIEW' && <div className="answer-form">
          <h3>Architect review</h3>
          <p className="muted">Check the findings and evidence. Approval records your decision; revision runs the assessment again with your comments.</p>
          <label htmlFor="assessment-reviewer">Reviewer name</label>
          <input id="assessment-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={120} />
          <label htmlFor="assessment-comment">Comment or requested changes</label>
          <textarea id="assessment-comment" value={comment} onChange={(event) => setComment(event.target.value)} rows={3} maxLength={2000} />
          <div className="review-actions">
            <button type="button" disabled={busy || !reviewer.trim()} onClick={() => review('APPROVE')}>Approve assessment</button>
            <button type="button" disabled={busy || !reviewer.trim() || !comment.trim()} onClick={() => review('REVISE')}>Request revision</button>
          </div>
        </div>}
        {assessment.status === 'APPROVED' && <p className="message">Approved assessment. Its findings and evidence are saved with this assessment ID.</p>}
        {assessment.review_history.length > 0 && <details><summary>Review history</summary><ul>{assessment.review_history.map((item, index) => <li key={index}>{item.reviewer}: {item.decision}{item.comment ? ` — ${item.comment}` : ''}</li>)}</ul></details>}
      </div>}
    </section>
  );
}
