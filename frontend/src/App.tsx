import { ChangeEvent, FormEvent, useEffect, useRef, useState } from 'react';

import { ConflictReview } from './components/ConflictReview';
import { GraphExplorer } from './components/GraphExplorer';
import { KnowledgeAssistant } from './components/KnowledgeAssistant';
import { IngestionResponse, LearningReport } from './components/LearningReport';
import { ClarificationQueue } from './components/ClarificationQueue';
import { ClaimReview } from './components/ClaimReview';
import { API_ROOT } from './config';

type Neo4jStatus = 'Checking...' | 'UP' | 'DOWN' | 'UNKNOWN';
type BackendStatus = 'Checking...' | 'UP' | 'DOWN';
type AuthSession = { required: boolean; authenticated: boolean };

type HealthResponse = {
  status: 'UP' | 'DEGRADED';
  neo4j: 'UP' | 'DOWN';
};

type KnowledgeGap = {
  id: string;
  entity_id: string;
  gap_type: string;
  description: string;
  priority: 'HIGH' | 'MEDIUM' | 'LOW';
  status: 'OPEN' | 'RESOLVED' | 'SKIPPED';
};

type StartCurationResponse = {
  workflow_id: string;
  gap_id: string;
  status: 'WAITING_FOR_HUMAN';
  question: string;
};

type SubmitAnswerResponse = {
  workflow_id: string;
  status: 'RESOLVED' | 'NEEDS_REVIEW';
  gap_id?: string;
  entity_id?: string;
  claim_id?: string;
  review_reason?: 'ANSWER_UNCLEAR' | 'ENTITY_TYPE_MISMATCH' | 'ENTITY_IDENTITY_REVIEW';
};

type GapDetectionResult = {
  namespace: string;
  findings_detected: number;
  gaps_created: number;
  gaps_existing: number;
  gaps_reopened: number;
  gaps_resolved: number;
  open_automatic_gaps: number;
};

const HEALTH_URL = `${API_ROOT}/api/health`;
const GAPS_URL = `${API_ROOT}/api/gaps`;
const SOURCES_URL = `${API_ROOT}/api/sources/files`;

export default function App() {
  const [auth, setAuth] = useState<AuthSession | null>(null);
  const [loginPassword, setLoginPassword] = useState('');
  const [loginMessage, setLoginMessage] = useState('');
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('Checking...');
  const [neo4jStatus, setNeo4jStatus] = useState<Neo4jStatus>('Checking...');
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [curation, setCuration] = useState<StartCurationResponse | null>(null);
  const [answer, setAnswer] = useState('');
  const [message, setMessage] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [namespace, setNamespace] = useState('');
  const [ingestionMessage, setIngestionMessage] = useState('');
  const [lastIngestion, setLastIngestion] = useState<{ result: IngestionResponse; filename: string } | null>(null);
  const [graphRevision, setGraphRevision] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [forceReprocess, setForceReprocess] = useState(false);
  const [detectionResult, setDetectionResult] = useState<GapDetectionResult | null>(null);
  const [isDetecting, setIsDetecting] = useState(false);

  async function loadGaps() {
    if (namespace.trim() === '') {
      setGaps([]);
      return;
    }
    try {
      const response = await fetch(`${GAPS_URL}?namespace=${encodeURIComponent(namespace.trim())}`);
      if (!response.ok) {
        setMessage('Open gaps are unavailable.');
        return;
      }
      const openGaps = (await response.json()) as KnowledgeGap[];
      setGaps(openGaps);
    } catch {
      setMessage('Open gaps are unavailable.');
    }
  }

  async function detectMissingKnowledge() {
    setIsDetecting(true);
    setMessage('');
    setDetectionResult(null);

    try {
      const response = await fetch(`${GAPS_URL}/detect?namespace=${encodeURIComponent(namespace.trim())}`, { method: 'POST' });
      if (!response.ok) {
        setMessage('Knowledge scan failed.');
        return;
      }
      setDetectionResult((await response.json()) as GapDetectionResult);
      await loadGaps();
    } catch {
      setMessage('Knowledge scan failed.');
    } finally {
      setIsDetecting(false);
    }
  }

  useEffect(() => {
    async function loadSession() {
      try {
        const response = await fetch(`${API_ROOT}/api/auth/session`);
        if (!response.ok) throw new Error('Session unavailable');
        setAuth((await response.json()) as AuthSession);
      } catch {
        setLoginMessage('Could not connect to the backend. Start the backend and reload this page.');
      }
    }
    async function loadHealth() {
      try {
        const response = await fetch(HEALTH_URL);

        if (!response.ok) {
          setBackendStatus('DOWN');
          setNeo4jStatus('UNKNOWN');
          return;
        }

        const health = (await response.json()) as HealthResponse;
        setBackendStatus('UP');
        setNeo4jStatus(health.neo4j);
      } catch {
        setBackendStatus('DOWN');
        setNeo4jStatus('UNKNOWN');
      }
    }

    void loadSession();
    void loadHealth();
  }, []);

  useEffect(() => {
    if (auth?.authenticated) folderInputRef.current?.setAttribute('webkitdirectory', '');
  }, [auth?.authenticated]);

  useEffect(() => {
    if (auth?.authenticated) {
      void loadGaps();
    }
  }, [namespace, auth?.authenticated]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginMessage('');
    try {
      const response = await fetch(`${API_ROOT}/api/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: loginPassword }),
      });
      if (!response.ok) {
        setLoginMessage('Incorrect password.');
        return;
      }
      setAuth((await response.json()) as AuthSession);
      setLoginPassword('');
    } catch {
      setLoginMessage('Could not connect to the backend.');
    }
  }

  async function signOut() {
    await fetch(`${API_ROOT}/api/auth/logout`, { method: 'POST' });
    setAuth({ required: true, authenticated: false });
    setNamespace('');
    setSelectedFiles([]);
    setLastIngestion(null);
    setIngestionMessage('');
    setDetectionResult(null);
    setCuration(null);
    setAnswer('');
    setMessage('');
    setGaps([]);
  }

  async function startCuration(gapId: string) {
    setIsBusy(true);
    setMessage('');
    setCuration(null);
    setAnswer('');

    try {
      const response = await fetch(`${API_ROOT}/api/curation/gaps/${encodeURIComponent(gapId)}/start`, {
        method: 'POST',
      });

      if (!response.ok) {
        setMessage(response.status === 503 ? 'Knowledge curation is unavailable until AI is configured.' : 'Could not start curation.');
        return;
      }

      setCuration((await response.json()) as StartCurationResponse);
    } catch {
      setMessage('Could not start curation.');
    } finally {
      setIsBusy(false);
    }
  }

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (curation === null || answer.trim() === '') {
      return;
    }

    setIsBusy(true);
    setMessage('');

    try {
      const response = await fetch(`${API_ROOT}/api/curation/workflows/${curation.workflow_id}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer }),
      });

      if (!response.ok) {
        if (response.status === 404) {
          setCuration(null);
          setAnswer('');
          setMessage('This question is no longer waiting for an answer. Select Resolve on the open gap to try again.');
        } else {
          setMessage(response.status === 502 ? 'The AI service could not interpret this answer. Please try again.' : 'Could not submit the answer. Please try again.');
        }
        return;
      }

      const result = (await response.json()) as SubmitAnswerResponse;
      if (result.status === 'RESOLVED') {
        setMessage('Knowledge updated successfully.');
        setCuration(null);
        setAnswer('');
        await loadGaps();
        setGraphRevision((revision) => revision + 1);
        return;
      }

      setCuration(null);
      setAnswer('');
      if (result.review_reason === 'ENTITY_IDENTITY_REVIEW') {
        setMessage('The answer was saved, but the entity name needs review. Open Questions for the team below to choose the correct entity; the gap will then resolve.');
      } else if (result.review_reason === 'ENTITY_TYPE_MISMATCH') {
        setMessage('The answer named the wrong kind of entity for this gap. The gap remains open; select Resolve to try again with a team or service name as requested.');
      } else {
        setMessage('The answer did not identify a specific entity. The gap remains open; select Resolve to try again with the exact name requested.');
      }
      await loadGaps();
    } catch {
      setMessage('Could not submit the answer.');
    } finally {
      setIsBusy(false);
    }
  }

  function selectFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    setSelectedFiles(files);
    const folderNames = [...new Set(files.map((file) => file.webkitRelativePath.split('/')[0]).filter(Boolean))];
    if (folderNames.length === 1) setNamespace(folderNames[0]);
    setForceReprocess(false);
    setIngestionMessage('');
    setLastIngestion(null);
  }

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedFiles.length === 0 || namespace.trim() === '') {
      return;
    }

    const filenames = selectedFiles.map((file) => file.name.toLocaleLowerCase());
    if (new Set(filenames).size !== filenames.length) {
      setIngestionMessage('Two selected files have the same name. Upload them separately or rename one file.');
      return;
    }

    setIsUploading(true);
    setIngestionMessage('');
    setLastIngestion(null);

    try {
      let completed = 0;
      let unchanged = 0;
      const failures: string[] = [];
      for (const file of selectedFiles) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('namespace', namespace.trim());
        formData.append('force', String(forceReprocess));
        try {
          const response = await fetch(SOURCES_URL, { method: 'POST', body: formData });
          if (!response.ok) {
            if (response.status === 401) {
              setAuth({ required: true, authenticated: false });
              setLoginMessage('Your session expired. Sign in again, then retry the upload.');
              return;
            }
            const error = response.status === 422 ? await response.json() as { detail?: unknown } : null;
            const detail = typeof error?.detail === 'string' ? error.detail : response.status === 413 ? 'File exceeds the upload size limit' : response.status === 503 ? 'AI provider is unavailable' : `HTTP ${response.status}`;
            failures.push(`${file.name}: ${detail}`);
            continue;
          }
          const result = (await response.json()) as IngestionResponse;
          setLastIngestion({ result, filename: file.name });
          if (result.status === 'UNCHANGED') unchanged += 1;
          else completed += 1;
        } catch {
          failures.push(`${file.name}: upload failed`);
        }
      }
      setIngestionMessage(`${completed} learned, ${unchanged} unchanged, ${failures.length} failed.${failures.length ? ` ${failures.join('; ')}` : ''}`);
      if (completed > 0) setGraphRevision((revision) => revision + 1);
    } catch {
      setIngestionMessage('Document ingestion failed.');
    } finally {
      setIsUploading(false);
    }
  }

  if (auth === null || !auth.authenticated) {
    return (
      <main className="shell">
        <section className="status-card" aria-labelledby="login-title">
          <h1 id="login-title">Living Knowledge POC</h1>
          {auth === null ? <p>Connecting to backend…</p> : (
            <form className="answer-form" onSubmit={(event) => void signIn(event)}>
              <label htmlFor="shared-password">Shared password</label>
              <input id="shared-password" type="password" autoComplete="current-password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} />
              <button type="submit" disabled={loginPassword === ''}>Sign in</button>
            </form>
          )}
          {loginMessage !== '' && <p className="message" role="alert">{loginMessage}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <section className="status-card" aria-labelledby="page-title">
        <p className="eyebrow">Living Knowledge</p>
        <h1 id="page-title">Living Knowledge POC</h1>
        {auth.required && <button type="button" onClick={() => void signOut()}>Sign out</button>}
        <dl className="status-list">
          <div className="status-row">
            <dt>Backend</dt>
            <dd>{backendStatus}</dd>
          </div>
          <div className="status-row">
            <dt>Neo4j</dt>
            <dd>{neo4jStatus}</dd>
          </div>
        </dl>
      </section>

      <section className="status-card" aria-label="Active namespace">
        <label htmlFor="active-namespace">Active namespace</label>
        <input id="active-namespace" value={namespace} onChange={(event) => setNamespace(event.target.value)} placeholder="Enter a namespace" />
        <p className="muted">Enter the namespace you want to use. Uploads and questions use this name; selecting a folder can fill it for you.</p>
      </section>

      <KnowledgeAssistant apiRoot={API_ROOT} namespace={namespace} onNamespaceChange={setNamespace} />

      <GraphExplorer apiRoot={API_ROOT} namespace={namespace} onNamespaceChange={setNamespace} refreshVersion={graphRevision} />

      <section className="status-card curator-card" aria-labelledby="ingestion-title">
        <p className="eyebrow">Grow team knowledge</p>
        <h2 id="ingestion-title">Learn from a document</h2>
        <p className="muted">Add a PDF, DOCX, PPTX, TXT, or Markdown document. The system connects mentions to known entities, remembers alternate names, and adds supported relationships.</p>
        <p className="muted">Local rules mode works without AI for explicit facts such as “Billing Service calls Inventory API.” or “Billing Service | CALLS | Inventory API”. Free-form descriptions still need an AI provider.</p>

        {ingestionMessage !== '' && <p className="message" role="status">{ingestionMessage}</p>}

        <form className="answer-form" onSubmit={(event) => void uploadDocument(event)}>
          <label htmlFor="source-file">Source documents</label>
          <input id="source-file" type="file" multiple accept=".pdf,.docx,.pptx,.txt,.md" onChange={selectFiles} disabled={isUploading} />
          <label htmlFor="source-folder">Or select a folder of documents</label>
          <input id="source-folder" ref={folderInputRef} type="file" multiple accept=".pdf,.docx,.pptx,.txt,.md" onChange={selectFiles} disabled={isUploading} />
          <p className="muted">{selectedFiles.length} file(s) selected. A selected folder suggests its name as the namespace; you can edit it before uploading. Every selected file goes to the active namespace.</p>
          <label htmlFor="namespace">Namespace</label>
          <input id="namespace" value={namespace} onChange={(event) => setNamespace(event.target.value)} disabled={isUploading} />
          <label className="inline-option">
            <input type="checkbox" checked={forceReprocess} disabled={isUploading} onChange={(event) => setForceReprocess(event.target.checked)} />
            Reprocess even if unchanged
          </label>
          <p className="muted">Use reprocess for earlier uploads or to reassess the document after a learning-policy change. It creates a new processing revision and preserves prior evidence.</p>
          <button disabled={isUploading || selectedFiles.length === 0 || namespace.trim() === ''} type="submit">
            {isUploading ? 'Reading and connecting knowledge…' : 'Upload and learn'}
          </button>
        </form>

        {isUploading && <p className="muted" role="status">Reading the document, resolving names, and checking supporting evidence. Larger documents may take a few minutes.</p>}

        {lastIngestion !== null && <LearningReport key={lastIngestion.result.version_id ?? lastIngestion.result.document_id} result={lastIngestion.result} filename={lastIngestion.filename} />}

      </section>

      <ClaimReview apiRoot={API_ROOT} namespace={namespace} onNamespaceChange={setNamespace} refreshVersion={graphRevision} onKnowledgeUpdated={() => setGraphRevision((revision) => revision + 1)} />

      <section className="status-card curator-card" aria-labelledby="curator-title">
        <p className="eyebrow">Phase 6 Workflow</p>
        <h2 id="curator-title">Knowledge Curator</h2>
        <button disabled={isDetecting || namespace.trim() === ''} type="button" onClick={() => void detectMissingKnowledge()}>
          {isDetecting ? 'Scanning...' : 'Detect Missing Knowledge'}
        </button>

        {detectionResult !== null && (
          <div className="scan-result" role="status">
            <strong>Knowledge scan complete</strong>
            <span>Findings: {detectionResult.findings_detected}</span>
            <span>New gaps: {detectionResult.gaps_created}</span>
            <span>Resolved automatically: {detectionResult.gaps_resolved}</span>
          </div>
        )}

        {message !== '' && <p className="message">{message}</p>}

        {gaps.length === 0 ? (
          <p className="muted">No open knowledge gaps.</p>
        ) : (
          <div className="gap-list">
            {gaps.map((gap) => (
              <article className="gap-item" key={gap.id}>
                <div>
                  <h3>{gap.gap_type}</h3>
                  <p>{gap.description}</p>
                  <span className="badge">{gap.priority}</span>
                </div>
                <button disabled={isBusy} type="button" onClick={() => void startCuration(gap.id)}>
                  Resolve
                </button>
              </article>
            ))}
          </div>
        )}

        {curation !== null && (
          <form className="answer-form" onSubmit={(event) => void submitAnswer(event)}>
            <label htmlFor="engineer-answer">{curation.question}</label>
            <input
              id="engineer-answer"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="Enter the specific name requested above"
            />
            <button disabled={isBusy || answer.trim() === ''} type="submit">
              Submit Answer
            </button>
          </form>
        )}
      </section>

      <ClarificationQueue apiRoot={API_ROOT} namespace={namespace} onNamespaceChange={setNamespace} refreshVersion={graphRevision} onKnowledgeUpdated={() => { setGraphRevision((revision) => revision + 1); void loadGaps(); }} />

      <ConflictReview namespace={namespace} onNamespaceChange={setNamespace} />
    </main>
  );
}
