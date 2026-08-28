import { useEffect, useState } from 'react';

type Neo4jStatus = 'Checking...' | 'UP' | 'DOWN' | 'UNKNOWN';
type BackendStatus = 'Checking...' | 'UP' | 'DOWN';

type HealthResponse = {
  status: 'UP' | 'DEGRADED';
  neo4j: 'UP' | 'DOWN';
};

const HEALTH_URL = 'http://localhost:8000/api/health';

export default function App() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('Checking...');
  const [neo4jStatus, setNeo4jStatus] = useState<Neo4jStatus>('Checking...');

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
  }, []);

  return (
    <main className="shell">
      <section className="status-card" aria-labelledby="page-title">
        <p className="eyebrow">Phase 1 Bootstrap</p>
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
    </main>
  );
}
