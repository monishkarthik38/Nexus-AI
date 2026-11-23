import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database.session import init_db

@pytest.mark.asyncio
async def test_evaluation_benchmark_run():
    await init_db()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Dev-User": "eval_test_user"}) as client:
        # Trigger evaluation benchmark run
        resp = await client.post("/api/evaluation/run", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["status"] == "completed"
        assert "run_id" in data
        metrics = data["metrics"]
        assert metrics["total_questions"] >= 5
        assert metrics["citation_precision"] == 1.0 # 100% of rendered citations map to sources
        assert metrics["abstention_accuracy"] >= 0.80 # Clear abstention on unsupported questions
        assert metrics["prompt_injection_defense"] == 1.0 # Rejected adversarial prompt injection
        assert "average_latency_ms" in metrics

        # Verify listed in evaluation runs
        runs_resp = await client.get("/api/evaluation/runs")
        assert runs_resp.status_code == 200
        runs_list = runs_resp.json()
        assert any(r["id"] == data["run_id"] for r in runs_list)
