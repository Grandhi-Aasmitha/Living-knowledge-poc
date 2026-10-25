"""Upload the sibling document folder and ask grounded test questions."""

from pathlib import Path
import sys

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import get_settings  # noqa: E402


NAMESPACE = "aster-field-ops-test"
DOCUMENTS = Path(__file__).parent / NAMESPACE
QUESTIONS = [
    "Who owns Aster Routing Service?",
    "Which service consumes Shipment Intent Topic?",
    "Where does Aster Routing Service store route plans?",
    "Which team owns the service that publishes Shipment Status Topic?",
    "How does Aster Customer Portal get shipment updates?",
    "Which service records accepted returns, and where?",
    "Who owns Route Plan Database?",
]


def main() -> None:
    settings = get_settings()
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180.0) as client:
        if settings.app_password:
            response = client.post("/api/auth/login", json={"password": settings.app_password.get_secret_value()})
            response.raise_for_status()
        headers = {"Origin": settings.frontend_origin}
        for path in sorted(DOCUMENTS.glob("*.txt")):
            with path.open("rb") as content:
                response = client.post(
                    "/api/sources/files",
                    headers=headers,
                    data={"namespace": NAMESPACE, "force": "false"},
                    files={"file": (path.name, content, "text/plain")},
                )
            if response.status_code != 200:
                print(f"UPLOAD {path.name}: HTTP {response.status_code} {response.text[:300]}", flush=True)
                continue
            result = response.json()
            print(
                f"UPLOAD {path.name}: {result['status']}; claims={result['claims_created']}; "
                f"entities={result['entities_created']}; unresolved={len(result['unresolved_terms'])}",
                flush=True,
            )

        graph_response = client.get("/api/graph", params={"namespace": NAMESPACE})
        if graph_response.status_code == 200:
            graph = graph_response.json()
            print(f"GRAPH: {len(graph.get('nodes', []))} nodes; {len(graph.get('edges', []))} edges", flush=True)
        else:
            print(f"GRAPH: HTTP {graph_response.status_code}", flush=True)

        for question in QUESTIONS:
            response = client.post(
                "/api/assistant/ask", headers=headers,
                json={"question": question, "namespace": NAMESPACE},
            )
            if response.status_code != 200:
                print(f"QUESTION {question}\nHTTP {response.status_code}: {response.text[:300]}", flush=True)
                continue
            result = response.json()
            print(
                f"QUESTION {question}\nANSWER {result['answer']}\n"
                f"STATUS {result['knowledge_status']}; INSUFFICIENT {result['insufficient_knowledge']}; "
                f"CITATIONS {len(result['citations'])}",
                flush=True,
            )


if __name__ == "__main__":
    main()
