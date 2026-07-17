"""FastAPI smoke and pipeline execution tests."""

from fastapi.testclient import TestClient
from pydantic_ai.exceptions import AgentRunError

import src.api as api_module
from src.api import app

client = TestClient(app)


def test_health_and_openapi_are_available() -> None:
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/execute" in schema["paths"]
    assert "/execute/full" in schema["paths"]


def test_execute_requires_symptom() -> None:
    response = client.post("/execute")
    assert response.status_code == 422


def test_execute_returns_structured_offline_result() -> None:
    response = client.post(
        "/execute",
        params={
            "symptom": "Why did checkout abandonment spike?",
            "systems": "b",
            "mode": "offline",
            "include_judge": "true",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["system"] == "System B"
    assert payload["results"][0]["grounded_in_query_results"] is True
    assert payload["results"][0]["hypothesis"]["affected_cohort"]
    assert payload["results"][0]["judge"]["score"] in range(1, 6)


def test_agent_failure_is_returned_as_json_not_unhandled_500(monkeypatch) -> None:
    def fail_agent(*args, **kwargs):
        del args, kwargs
        raise AgentRunError("invalid model tool sequence")

    monkeypatch.setattr(api_module, "_run_system", fail_agent)
    response = client.post(
        "/execute",
        params={"symptom": "Why did checkout fail?", "systems": "b"},
    )

    assert response.status_code == 422
    assert "could not produce a valid grounded result" in response.json()["detail"]
