import { ChangeEvent, FormEvent, useEffect, useState } from 'react';

import { ConflictReview } from './components/ConflictReview';
import { GraphExplorer } from './components/GraphExplorer';
import { KnowledgeAssistant } from './components/KnowledgeAssistant';
import { IngestionResponse, LearningReport } from './components/LearningReport';
import { ClarificationQueue } from './components/ClarificationQueue';
import { API_ROOT } from './config';

type Neo4jStatus = 'Checking...' | 'UP' | 'DOWN' | 'UNKNOWN';
type BackendStatus = 'Checking...' | 'UP' | 'DOWN';

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

type SourceDocument = {
  id: string;
  title: string;
  filename: string;
  namespace: string;
  latest_version: number;
  current_content_hash: string;
  updated_at: string;
};

const HEALTH_URL = `${API_ROOT}/api/health`;
const GAPS_URL = `${API_ROOT}/api/gaps`;
const SOURCES_URL = `${API_ROOT}/api/sources/files`;

export default function App() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('Checking...');
  const [neo4jStatus, setNeo4jStatus] = useState<Neo4jStatus>('Checking...');
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [curation, setCuration] = useState<StartCurationResponse | null>(null);
  const [answer, setAnswer] = useState('');
  const [message, setMessage] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [namespace, setNamespace] = useState('tstvs');
  const [ingestionMessage, setIngestionMessage] = useState('');
  const [lastIngestion, setLastIngestion] = useState<{ result: IngestionResponse; filename: string } | null>(null);
  const [graphRevision, setGraphRevision] = useState(0);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [forceReprocess, setForceReprocess] = useState(false);
  const [detectionResult, setDetectionResult] = useState<GapDetectionResult | null>(null);
  const [isDetecting, setIsDetecting] = useState(false);

  async function loadGaps() {
    try {
      const response = await fetch(GAPS_URL);
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
      const response = await fetch(`${GAPS_URL}/detect?namespace=tstvs`, { method: 'POST' });
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

  async function loadDocuments() {
    try {
      const response = await fetch(SOURCES_URL);
      if (!response.ok) {
        return;
      }
      setDocuments((await response.json()) as SourceDocument[]);
    } catch {
      // Keep document ingestion UI usable even when the list endpoint is temporarily unavailable.
    }
  }

  useEffect(() => {
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

    void loadHealth();
    void loadGaps();
    void loadDocuments();
  }, []);

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
        setMessage('Could not submit the answer.');
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

      setMessage('The answer could not be converted into confirmed knowledge. The gap remains open.');
      await loadGaps();
    } catch {
      setMessage('Could not submit the answer.');
    } finally {
      setIsBusy(false);
    }
  }

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFile(event.target.files?.[0] ?? null);
    setForceReprocess(false);
    setIngestionMessage('');
    setLastIngestion(null);
  }

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedFile === null || namespace.trim() === '') {
      return;
    }

    setIsUploading(true);
    setIngestionMessage('');
    setLastIngestion(null);

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('namespace', namespace.trim());
    formData.append('force', String(forceReprocess));

    try {
      const response = await fetch(SOURCES_URL, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        if (response.status === 503) {
          setIngestionMessage('Document ingestion is unavailable until AI is configured.');
        } else if (response.status === 413) {
          setIngestionMessage('The selected file exceeds the upload size limit.');
        } else {
          setIngestionMessage('Document ingestion failed.');
        }
        return;
      }

      const result = (await response.json()) as IngestionResponse;
      setLastIngestion({ result, filename: selectedFile.name });
      if (result.status === 'UNCHANGED') {
        setIngestionMessage('This document is already part of the team’s knowledge.');
      } else {
        setIngestionMessage('Learning complete. Review the new knowledge and uncertain terms below.');
        setGraphRevision((revision) => revision + 1);
      }
      await loadDocuments();
    } catch {
      setIngestionMessage('Document ingestion failed.');
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <main className="shell">
      <section className="status-card" aria-labelledby="page-title">
        <p className="eyebrow">Living Knowledge</p>
        <h1 id="page-title">Living Knowledge POC</h1>
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

      <KnowledgeAssistant apiRoot={API_ROOT} />

      <GraphExplorer apiRoot={API_ROOT} refreshVersion={graphRevision} />

      <section className="status-card curator-card" aria-labelledby="ingestion-title">
        <p className="eyebrow">Grow team knowledge</p>
        <h2 id="ingestion-title">Learn from a document</h2>
        <p className="muted">Add a PDF, DOCX, PPTX, TXT, or Markdown document. The system connects mentions to known entities, remembers alternate names, and adds supported relationships.</p>

        {ingestionMessage !== '' && <p className="message" role="status">{ingestionMessage}</p>}

        <form className="answer-form" onSubmit={(event) => void uploadDocument(event)}>
          <label htmlFor="source-file">Source document</label>
          <input id="source-file" type="file" accept=".pdf,.docx,.pptx,.txt,.md" onChange={selectFile} disabled={isUploading} />
          <label htmlFor="namespace">Namespace</label>
          <input id="namespace" value={namespace} onChange={(event) => setNamespace(event.target.value)} disabled={isUploading} />
          <label className="inline-option">
            <input type="checkbox" checked={forceReprocess} disabled={isUploading} onChange={(event) => setForceReprocess(event.target.checked)} />
            Reprocess even if unchanged
          </label>
          <p className="muted">Use reprocess for earlier uploads or to reassess the document after a learning-policy change. It creates a new processing revision and preserves prior evidence.</p>
          <button disabled={isUploading || selectedFile === null || namespace.trim() === ''} type="submit">
            {isUploading ? 'Reading and connecting knowledge…' : 'Upload and learn'}
          </button>
        </form>

        {isUploading && <p className="muted" role="status">Reading the document, resolving names, and checking supporting evidence. Larger documents may take a few minutes.</p>}

        {lastIngestion !== null && <LearningReport key={lastIngestion.result.version_id ?? lastIngestion.result.document_id} result={lastIngestion.result} filename={lastIngestion.filename} />}

        {documents.length > 0 && (
          <div className="document-list">
            {documents.map((document) => (
              <article className="document-item" key={document.id}>
                <div>
                  <h3>{document.title}</h3>
                  <p>{document.filename}</p>
                  <p className="muted">Team: {document.namespace}</p>
                </div>
                <span className="badge">{document.latest_version === 0 ? 'Incomplete — retry upload' : `v${document.latest_version}`}</span>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="status-card curator-card" aria-labelledby="curator-title">
        <p className="eyebrow">Phase 6 Workflow</p>
        <h2 id="curator-title">Knowledge Curator</h2>
        <button disabled={isDetecting} type="button" onClick={() => void detectMissingKnowledge()}>
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
              placeholder="Scheduler Service"
            />
            <button disabled={isBusy || answer.trim() === ''} type="submit">
              Submit Answer
            </button>
          </form>
        )}
      </section>

      <ClarificationQueue apiRoot={API_ROOT} namespace={namespace} onNamespaceChange={setNamespace} refreshVersion={graphRevision} onKnowledgeUpdated={() => { setGraphRevision((revision) => revision + 1); void loadGaps(); }} />

      <ConflictReview />
    </main>
  );
}
