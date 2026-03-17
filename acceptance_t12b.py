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
    if response.status_code != 200:
        raise AssertionError(f"上传验收文件失败，状态码 {response.status_code}，响应 {response.text}")
    return int(response.json()["file_record_id"])


def review(client: TestClient, file_id: int, action: str, current_member_id: int):
    return client.put(
        f"/files/{file_id}/review",
        params={"action": action, "current_member_id": str(current_member_id)},
    )


def main() -> None:
    seed_demo_data()
    client = TestClient(app)
    db = SessionLocal()

    try:
        approve_module = get_module_by_name(db, "数据看板前端实现")
        reject_module = get_module_by_name(db, "移动端适配样式")

        approve_file_id = upload(client, approve_module.id, int(approve_module.assigned_to), "deliverable.zip")
        reject_file_id = upload(client, reject_module.id, int(reject_module.assigned_to), "mobile.zip")

        approve_project = db.query(models.Project).filter(models.Project.id == approve_module.project_id).first()
        reject_project = db.query(models.Project).filter(models.Project.id == reject_module.project_id).first()
        if approve_project is None or reject_project is None:
            raise AssertionError("验收所需项目不存在")

        non_pm_id = db.query(models.Member).filter(models.Member.id != int(approve_project.created_by)).first().id
        forbidden = review(client, approve_file_id, "approve", int(non_pm_id))
        assert_true(
            forbidden.status_code == 403,
            "非 PM 审核被正确拒绝",
            f"非 PM 审核应返回 403，实际为 {forbidden.status_code}",
        )

        approved = review(client, approve_file_id, "approve", int(approve_project.created_by))
        assert_true(
            approved.status_code == 200,
            "PM 可审核通过交付",
            f"PM 审核通过应返回 200，实际为 {approved.status_code}，响应 {approved.text}",
        )

        rejected = review(client, reject_file_id, "reject", int(reject_project.created_by))
        assert_true(
            rejected.status_code == 200,
            "PM 可打回交付",
            f"PM 打回交付应返回 200，实际为 {rejected.status_code}，响应 {rejected.text}",
        )

        db.expire_all()
        approved_file = db.query(models.ModuleFile).filter(models.ModuleFile.id == approve_file_id).first()
        approved_module = db.query(models.Module).filter(models.Module.id == approve_module.id).first()
        rejected_file = db.query(models.ModuleFile).filter(models.ModuleFile.id == reject_file_id).first()
        rejected_module = db.query(models.Module).filter(models.Module.id == reject_module.id).first()

        assert_true(
            approved_file is not None and approved_file.status == "Approved",
            "通过后文件状态为 Approved",
            f"通过后文件状态应为 Approved，实际为 {None if approved_file is None else approved_file.status}",
        )
        assert_true(
            approved_module is not None and approved_module.status == "已完成",
            "通过后模块状态为 已完成",
            f"通过后模块状态应为 已完成，实际为 {None if approved_module is None else approved_module.status}",
        )
        assert_true(
            rejected_file is not None and rejected_file.status == "Rejected",
            "打回后文件状态为 Rejected",
            f"打回后文件状态应为 Rejected，实际为 {None if rejected_file is None else rejected_file.status}",
        )
        assert_true(
            rejected_module is not None and rejected_module.status == "开发中",
            "打回后模块状态回到 开发中",
            f"打回后模块状态应为 开发中，实际为 {None if rejected_module is None else rejected_module.status}",
        )

        print("T12B 验收通过：PM 审核权限、通过与打回状态流转均符合预期")
    finally:
        db.close()


if __name__ == "__main__":
    main()
