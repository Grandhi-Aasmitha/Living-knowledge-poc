import { useState } from 'react';

export type EntityResolutionSummary = {
  observed_name: string;
  observed_type: string;
  action: 'MATCH' | 'CREATE' | 'NEEDS_REVIEW';
  canonical_entity_id: string | null;
  canonical_name: string | null;
  reason: string | null;
  alias_learned: boolean;
};

export type IngestionResponse = {
  document_id: string;
  version_id: string | null;
  status: 'INGESTED' | 'UNCHANGED';
  chunks_processed: number;
  entities_created: number;
  entities_reused: number;
  claims_created: number;
  claims_reused: number;
  evidence_created: number;
  claims_rejected: number;
  unresolved_terms: string[];
  entity_resolutions?: EntityResolutionSummary[];
  auto_confirmed?: boolean;
};

type ReportFilter = 'ALL' | EntityResolutionSummary['action'];

const ACTION_LABELS = {
  MATCH: 'Recognized',
  CREATE: 'New entity',
  NEEDS_REVIEW: 'Needs clarification',
};

export function LearningReport({ result, filename }: { result: IngestionResponse; filename: string }) {
  const [filter, setFilter] = useState<ReportFilter>('ALL');
  const resolutions = result.entity_resolutions ?? [];
  const visibleResolutions = resolutions.filter((resolution) => filter === 'ALL' || resolution.action === filter);
  const aliasesLearned = resolutions.filter((resolution) => resolution.alias_learned).length;
  const needsReview = resolutions.filter((resolution) => resolution.action === 'NEEDS_REVIEW').length;
  const needsClarification = needsReview > 0 || result.unresolved_terms.length > 0;

  return (
    <section className="learning-report" aria-labelledby="learning-report-title">
      <div className="learning-report-heading">
        <div>
          <p className="eyebrow">Latest learning session</p>
          <h3 id="learning-report-title">What I learned from this document</h3>
          <p className="muted learning-filename">{filename}</p>
        </div>
        <span className={`resolution-status ${needsClarification ? 'resolution-status-review' : 'resolution-status-match'}`}>
          {result.status === 'UNCHANGED' ? 'Already read' : needsClarification ? 'Clarification needed' : 'Processed'}
        </span>
      </div>

      {result.status === 'UNCHANGED' ? (
        <p className="muted">This document has not changed since its last upload. No new learning was run.</p>
      ) : (
        <>
          <dl className="learning-metrics">
            <div><dt>New entities</dt><dd>{result.entities_created}</dd></div>
            <div><dt>Known entities</dt><dd>{result.entities_reused}</dd></div>
            <div><dt>Aliases learned</dt><dd>{aliasesLearned}</dd></div>
            <div><dt>New facts</dt><dd>{result.claims_created}</dd></div>
          </dl>
          <p className="muted">{result.evidence_created} evidence record(s) added. {result.auto_confirmed ? 'New extracted facts were confirmed automatically from this upload.' : 'New extracted facts remain proposed until confirmed.'}</p>

          {resolutions.length > 0 && (
            <>
              <div className="resolution-filters" role="group" aria-label="Filter entity understanding">
                {(['ALL', 'MATCH', 'CREATE', 'NEEDS_REVIEW'] as ReportFilter[]).map((action) => (
                  <button
                    key={action}
                    type="button"
                    aria-pressed={filter === action}
                    onClick={() => setFilter(action)}
                  >
                    {action === 'ALL' ? 'All mentions' : ACTION_LABELS[action]}
                    <span>{resolutions.filter((resolution) => action === 'ALL' || resolution.action === action).length}</span>
                  </button>
                ))}
              </div>
              <ul className="resolution-list" aria-live="polite">
                {visibleResolutions.map((resolution, index) => (
                  <li className={`resolution-item resolution-item-${resolution.action.toLowerCase()}`} key={`${resolution.observed_name}:${index}`}>
                    <div className="resolution-item-heading">
                      <div className="resolution-name">
                        <strong>{resolution.observed_name}</strong>
                        <span className="muted">{resolution.observed_type.replaceAll('_', ' ')}</span>
                      </div>
                      <span className={`resolution-status resolution-status-${resolution.action === 'MATCH' ? 'match' : resolution.action === 'CREATE' ? 'new' : 'review'}`}>
                        {ACTION_LABELS[resolution.action]}
                      </span>
                    </div>
                    {resolution.action === 'MATCH' && (
                      <p>Linked to <strong>{resolution.canonical_name}</strong> in the team's knowledge.</p>
                    )}
                    {resolution.alias_learned && (
                      <p className="resolution-alias">Remembered “{resolution.observed_name}” as another name for this entity.</p>
                    )}
                    {resolution.action === 'CREATE' && (
                      <p>Added <strong>{resolution.canonical_name}</strong> to the team's knowledge.</p>
                    )}
                    {resolution.action === 'NEEDS_REVIEW' && (
                      <p>The identity is uncertain. Relationships using this mention were left out of the graph.</p>
                    )}
                    {resolution.reason && (
                      <details className="resolution-explanation">
                        <summary>Why this decision?</summary>
                        <p>{resolution.reason}</p>
                      </details>
                    )}
                  </li>
                ))}
              </ul>
              {visibleResolutions.length === 0 && <p className="muted">No mentions in this category.</p>}
            </>
          )}
          {resolutions.length === 0 && <p className="muted">No entity-level details were returned for this upload.</p>}
          {result.unresolved_terms.length > 0 && (
            <aside className="learning-clarifications" aria-labelledby="clarifications-title">
              <h4 id="clarifications-title">Still uncertain</h4>
              <p>Identity questions are saved in “Questions for the team” below. Resolve a question there to remember the name and apply its waiting claims.</p>
              <ul>{result.unresolved_terms.map((term, index) => <li key={`${term}:${index}`}>{term}</li>)}</ul>
            </aside>
          )}
          {result.claims_rejected > 0 && <p className="muted">{result.claims_rejected} candidate relationship(s) were left out because evidence or entity identity could not be verified.</p>}
        </>
      )}
      <p className="learning-report-note">This upload summary clears on reload. Identity questions, evidence, and recorded decisions remain saved in the team's knowledge.</p>
    </section>
  );
}
