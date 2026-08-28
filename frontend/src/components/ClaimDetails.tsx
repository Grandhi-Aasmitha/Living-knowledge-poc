export type EvidenceSummary = {
  id: string;
  excerpt: string | null;
  locator: string | null;
  source_id: string;
  source_type: string;
  source_title: string;
  document_title: string | null;
  document_version: number | null;
  chunk_locator: string | null;
};

export type ClaimProvenance = {
  claim_id: string;
  subject_entity_id: string;
  subject_name: string;
  predicate: string;
  object_entity_id: string | null;
  object_name: string | null;
  object_value: string | null;
  status: string;
  confidence: number;
  evidence: EvidenceSummary[];
};

type ClaimDetailsProps = {
  claim: ClaimProvenance | null;
  isLoading: boolean;
  error: string;
};

export function ClaimDetails({ claim, isLoading, error }: ClaimDetailsProps) {
  if (isLoading) {
    return <p className="muted">Loading claim provenance...</p>;
  }

  if (error !== '') {
    return <p className="message">{error}</p>;
  }

  if (claim === null) {
    return <p className="muted">Select an edge to inspect claim evidence.</p>;
  }

  return (
    <article className="claim-details">
      <h3>{claim.predicate}</h3>
      <dl className="details-list">
        <div>
          <dt>Subject</dt>
          <dd>{claim.subject_name}</dd>
        </div>
        <div>
          <dt>Object</dt>
          <dd>{claim.object_name ?? claim.object_value ?? 'Unknown'}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{claim.status}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{claim.confidence.toFixed(2)}</dd>
        </div>
        <div>
          <dt>Evidence</dt>
          <dd>{claim.evidence.length}</dd>
        </div>
      </dl>

      {claim.evidence.length === 0 ? (
        <p className="muted">No evidence is attached to this claim.</p>
      ) : (
        <div className="evidence-list">
          {claim.evidence.map((item) => (
            <section className="evidence-item" key={item.id}>
              <strong>{item.source_title}</strong>
              <span className="badge">{item.source_type}</span>
              {item.excerpt !== null && <p>{item.excerpt}</p>}
              {item.locator !== null && <p className="muted">Locator: {item.locator}</p>}
              {item.document_title !== null && (
                <p className="muted">
                  Document: {item.document_title}
                  {item.document_version !== null ? ` v${item.document_version}` : ''}
                  {item.chunk_locator !== null ? ` · ${item.chunk_locator}` : ''}
                </p>
              )}
            </section>
          ))}
        </div>
      )}
    </article>
  );
}
