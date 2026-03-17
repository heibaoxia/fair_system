from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app
from seed_demo_data import seed_demo_data


def assert_true(condition: bool, success: str, failure: str) -> str:
    if not condition:
        raise AssertionError(failure)
    return success


def get_module_by_name(db, name: str) -> models.Module:
    module = db.query(models.Module).filter(models.Module.name == name).first()
    if module is None:
        raise AssertionError(f"缺少验收模块：{name}")
    return module


def upload(client: TestClient, module_id: int, uploaded_by: int, filename: str) -> int:
    response = client.post(
        "/files/upload/",
        data={"module_id": str(module_id), "uploaded_by": str(uploaded_by)},
        files={"file": (filename, io.BytesIO(b"demo content"), "application/octet-stream")},
    )
    return response.status_code


def main() -> None:
    seed_demo_data()
    client = TestClient(app)
    db = SessionLocal()

    try:
        in_progress = get_module_by_name(db, "数据看板前端实现")
        completed = get_module_by_name(db, "核心表结构设计")

        assignee_id = int(in_progress.assigned_to)
        other_member_id = db.query(models.Member).filter(models.Member.id != assignee_id).first().id

        non_assignee_status = upload(client, in_progress.id, int(other_member_id), "not-owner.zip")
        assert_true(
            non_assignee_status == 403,
            "非负责人上传被正确拒绝",
            f"非负责人上传应返回 403，实际为 {non_assignee_status}",
        )

        wrong_status_code = upload(client, completed.id, int(completed.assigned_to), "completed.sql")
        assert_true(
            wrong_status_code == 400,
            "非开发中模块上传被正确拒绝",
            f"非开发中模块上传应返回 400，实际为 {wrong_status_code}",
        )

        success_code = upload(client, in_progress.id, assignee_id, "deliverable.zip")
        assert_true(
            success_code == 200,
            "负责人可正常上传文件",
            f"负责人上传应返回 200，实际为 {success_code}",
        )

        db.expire_all()
        refreshed = db.query(models.Module).filter(models.Module.id == in_progress.id).first()
        assert_true(
            refreshed is not None and refreshed.status == "待审核",
            "上传成功后模块状态已进入待审核",
            f"上传成功后模块状态应为 待审核，实际为 {None if refreshed is None else refreshed.status}",
        )

        print("T12A 验收通过：上传权限、状态校验、待审核流转均符合预期")
    finally:
        db.close()


if __name__ == "__main__":
    main()
