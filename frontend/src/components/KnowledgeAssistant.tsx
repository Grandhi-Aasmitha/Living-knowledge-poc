import { FormEvent, useState } from 'react';

type KnowledgeStatus = 'CONFIRMED' | 'PROPOSED' | 'INCOMPLETE' | 'CONFLICTING';

type MatchedEntity = {
  id: string;
  label: string;
  entity_type: string;
  namespace: string;
};

type AssistantCitation = {
  claim_id: string;
  claim_status: string;
  predicate: string;
  evidence_id: string;
  source_type: string;
  source_title: string;
  excerpt: string | null;
  locator: string | null;
  document_title: string | null;
  document_version: number | null;
  source_url: string | null;
  subject_name: string;
  object_name: string | null;
  object_value: string | null;
};

type OpenGap = {
  id: string;
  entity_id: string;
  gap_type: string;
  description: string;
  priority: string;
};

type OpenConflict = {
  id: string;
  rule_id: string;
  description: string;
  claim_ids: string[];
};

type AssistantResponse = {
  question: string;
  answer: string;
  insufficient_knowledge: boolean;
  knowledge_status: KnowledgeStatus;
  matched_entities: MatchedEntity[];
  citations: AssistantCitation[];
  open_gaps: OpenGap[];
  open_conflicts: OpenConflict[];
  context_truncated: boolean;
};

type KnowledgeAssistantProps = {
  apiRoot: string;
};

export function KnowledgeAssistant({ apiRoot }: KnowledgeAssistantProps) {
  const [question, setQuestion] = useState('');
  const [namespace, setNamespace] = useState('tstvs');
  const [response, setResponse] = useState<AssistantResponse | null>(null);
  const [message, setMessage] = useState('');
  const [isAsking, setIsAsking] = useState(false);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (question.trim() === '' || namespace.trim() === '') {
      return;
    }

    setIsAsking(true);
    setMessage('');
    setResponse(null);

    try {
      const result = await fetch(`${apiRoot}/api/assistant/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, namespace }),
      });

      if (!result.ok) {
        if (result.status === 503) {
          setMessage('Knowledge Assistant is unavailable until AI is configured.');
        } else if (result.status === 422) {
          setMessage('Please enter a valid question.');
        } else {
          setMessage('Knowledge Assistant could not answer that question.');
        }
        return;
      }

      setResponse((await result.json()) as AssistantResponse);
    } catch {
      setMessage('Knowledge Assistant is unavailable.');
    } finally {
      setIsAsking(false);
    }
  }

  return (
    <section className="status-card assistant-card" aria-labelledby="assistant-title">
      <p className="eyebrow">Phase 9 Capability</p>
      <h2 id="assistant-title">Knowledge Assistant</h2>
      <p className="muted">Ask a single-turn question answered only from source-backed knowledge in Neo4j.</p>

      <form className="answer-form" onSubmit={(event) => void ask(event)}>
        <label htmlFor="assistant-question">Ask about the knowledge base</label>
        <textarea
          id="assistant-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Who owns Scheduler Service?"
          rows={3}
        />
        <label htmlFor="assistant-namespace">Namespace</label>
        <input id="assistant-namespace" value={namespace} onChange={(event) => setNamespace(event.target.value)} />
        <button disabled={isAsking || question.trim() === '' || namespace.trim() === ''} type="submit">
          {isAsking ? 'Asking...' : 'Ask'}
        </button>
      </form>

      {message !== '' && <p className="message">{message}</p>}

      {response !== null && (
        <div className="assistant-response">
          <div className={`knowledge-status knowledge-status-${response.knowledge_status.toLowerCase()}`}>
            {response.knowledge_status}
          </div>
          {response.context_truncated && <p className="message">The retrieved context was limited. Refine the question for a narrower answer.</p>}
          <p className="assistant-answer">{response.answer}</p>

          {response.matched_entities.length > 0 && (
            <div>
              <h3>Matched entities</h3>
              <ul className="compact-list">
                {response.matched_entities.map((entity) => (
                  <li key={entity.id}>
                    {entity.label} <span className="muted">{entity.entity_type}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {response.citations.length > 0 && (
            <div>
              <h3>Supporting evidence</h3>
              <div className="citation-list">
                {response.citations.map((citation) => (
                  <article className="citation-card" key={`${citation.claim_id}:${citation.evidence_id}`}>
                    <strong>
                      {citation.subject_name} {citation.predicate.replaceAll('_', ' ')}{' '}
                      {citation.object_name ?? citation.object_value ?? '(literal)'}
                    </strong>
                    <span className="badge">{citation.claim_status}</span>
                    <p>
                      Source: {citation.source_type} — {citation.source_title}
                    </p>
                    {citation.document_title !== null && (
                      <p>
                        Document: {citation.document_title}
                        {citation.document_version !== null ? `, version ${citation.document_version}` : ''}
                      </p>
                    )}
                    {citation.locator !== null && <p>Location: {citation.locator}</p>}
                    {citation.excerpt !== null && <blockquote>{citation.excerpt}</blockquote>}
                    {citation.source_url !== null && (
                      <a href={citation.source_url} target="_blank" rel="noreferrer">
                        Open source
                      </a>
                    )}
                  </article>
                ))}
              </div>
            </div>
          )}

          {response.open_gaps.length > 0 && (
            <div>
              <h3>Relevant open gaps</h3>
              <ul className="compact-list">
                {response.open_gaps.map((gap) => (
                  <li key={gap.id}>
                    {gap.gap_type}: {gap.description} <span className="badge">{gap.priority}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {response.open_conflicts.length > 0 && (
            <div>
              <h3>Relevant open conflicts</h3>
              <ul className="compact-list">
                {response.open_conflicts.map((conflict) => (
                  <li key={conflict.id}>
                    {conflict.rule_id}: {conflict.description}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
