from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from seed_demo_data import seed_demo_data


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label} 应为 {expected}，实际为 {actual}")


def main() -> None:
    seed_demo_data()
    client = TestClient(app)

    response = client.get("/projects/3/completion-status")
    if response.status_code != 200:
        raise AssertionError(f"completion-status 应返回 200，实际为 {response.status_code}，响应 {response.text}")

    payload = response.json()
    assert_equal(payload.get("total_modules"), 6, "total_modules")
    assert_equal(payload.get("completed_modules"), 3, "completed_modules")
    assert_equal(payload.get("pending_modules"), 3, "pending_modules")
    assert_equal(payload.get("completion_percentage"), 50.0, "completion_percentage")
    assert_equal(payload.get("is_all_done"), False, "is_all_done")

    print("T12C 验收通过：项目完成度接口返回结构和统计结果均符合预期")


if __name__ == "__main__":
    main()
