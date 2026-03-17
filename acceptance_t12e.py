from __future__ import annotations

from fastapi.testclient import TestClient

from app import models
from app.api.scoring import _calc_module_summary
from app.database import SessionLocal
from app.main import app
from seed_demo_data import seed_demo_data


def assert_true(condition: bool, failure: str) -> None:
    if not condition:
        raise AssertionError(failure)


def main() -> None:
    seed_demo_data()
    client = TestClient(app)
    db = SessionLocal()

    try:
        member = db.query(models.Member).filter(models.Member.name == "陈雨").first()
        if member is None:
            raise AssertionError("缺少验收成员：陈雨")

        member.total_earnings = 1234.56
        db.commit()

        response = client.get(f"/todo?member_id={member.id}")
        assert_true(response.status_code == 200, f"todo 页面应返回 200，实际为 {response.status_code}")
        html = response.text

        assert_true("移动端适配样式" in html, "todo 页面未展示开发中的模块名")
        assert_true("验收-T7A-评分期已结束" in html, "todo 页面未展示开发中模块所属项目名")
        assert_true("状态：开发中" in html, "todo 页面未展示开发中模块状态")
        assert_true(f'/project/3?module_id=' in html, "todo 页面未展示上传文件跳转链接")

        expected_pending = 0.0
        completed_modules = db.query(models.Module).filter(
            models.Module.assigned_to == member.id,
            models.Module.status == "已完成",
        ).all()
        for module in completed_modules:
            project = db.query(models.Project).filter(models.Project.id == module.project_id).first()
            if project is None or project.status == "已完成":
                continue
            summary = _calc_module_summary(module, project, db)
            expected_pending += float(summary.get("composite_score", 0.0) or 0.0)

        assert_true("1234.56" in html, "todo 页面未展示已结算金额")
        assert_true(f"{'%.2f' % expected_pending}" in html, "todo 页面未展示待结算预估金额")

        print("T12E 验收通过：todo 页面已动态展示进行中工作与钱包数据")
    finally:
        db.close()


if __name__ == "__main__":
    main()
