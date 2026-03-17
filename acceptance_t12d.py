from __future__ import annotations

from fastapi.testclient import TestClient

from app import models
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
        project = db.query(models.Project).filter(models.Project.name == "验收-T7A-评分期已结束").first()
        if project is None:
            raise AssertionError("缺少验收项目：验收-T7A-评分期已结束")

        pm_id = int(project.created_by)
        non_pm_id = int(db.query(models.Member).filter(models.Member.id != pm_id).first().id)

        not_done = client.post(f"/projects/{project.id}/settle", params={"current_member_id": pm_id})
        assert_true(not_done.status_code == 400, f"未全部完成时结算应返回 400，实际为 {not_done.status_code}")

        modules = db.query(models.Module).filter(models.Module.project_id == project.id).order_by(models.Module.id.asc()).all()
        fallback_member_ids = [int(member.id) for member in project.members]
        fallback_index = 0
        for module in modules:
            if module.assigned_to is None:
                module.assigned_to = fallback_member_ids[fallback_index % len(fallback_member_ids)]
                fallback_index += 1
            module.status = "已完成"
        db.commit()

        forbidden = client.post(f"/projects/{project.id}/settle", params={"current_member_id": non_pm_id})
        assert_true(forbidden.status_code == 403, f"非 PM 结算应返回 403，实际为 {forbidden.status_code}")

        expected_amounts = {}
        total_score = 0.0
        for module in modules:
            summary = client.get(f"/scoring/module/{module.id}/summary")
            if summary.status_code != 200:
                raise AssertionError(f"读取模块 {module.id} 综合分失败：{summary.status_code} {summary.text}")
            composite_score = float(summary.json().get("composite_score", 0.0) or 0.0)
            total_score += composite_score
            expected_amounts[module.assigned_to] = expected_amounts.get(module.assigned_to, 0.0) + composite_score

        earnings_before = {
            int(member.id): float(getattr(member, "total_earnings", 0.0) or 0.0)
            for member in db.query(models.Member).all()
        }

        settled = client.post(f"/projects/{project.id}/settle", params={"current_member_id": pm_id})
        assert_true(settled.status_code == 200, f"PM 结算应返回 200，实际为 {settled.status_code}，响应 {settled.text}")

        payload = settled.json()
        settlements = payload.get("settlements", [])
        assert_true(bool(settlements), "结算结果中应包含 settlements")

        db.expire_all()
        refreshed_project = db.query(models.Project).filter(models.Project.id == project.id).first()
        assert_true(refreshed_project is not None and refreshed_project.status == "已完成", "结算后项目状态应为 已完成")

        returned_total = 0.0
        for item in settlements:
            member_id = int(item["member_id"])
            amount = round(float(item["settlement_amount"]), 2)
            score = round(float(item["composite_score_total"]), 2)
            expected_score = round(float(expected_amounts.get(member_id, 0.0)), 2)
            expected_amount = round((expected_score / total_score) * float(project.total_revenue), 2) if total_score else 0.0
            assert_true(score == expected_score, f"成员 {member_id} 综合分应为 {expected_score}，实际为 {score}")
            assert_true(amount == expected_amount, f"成员 {member_id} 结算金额应为 {expected_amount}，实际为 {amount}")

            refreshed_member = db.query(models.Member).filter(models.Member.id == member_id).first()
            current_earnings = round(float(getattr(refreshed_member, "total_earnings", 0.0) or 0.0), 2)
            before_earnings = round(earnings_before.get(member_id, 0.0), 2)
            assert_true(current_earnings == round(before_earnings + amount, 2), f"成员 {member_id} 累计收入未正确更新")
            returned_total += amount

        assert_true(abs(returned_total - float(project.total_revenue)) <= 0.05, f"结算总额应接近 {project.total_revenue}，实际为 {returned_total}")

        print("T12D 验收通过：PM 结算权限、完成态校验、收入分配与项目收尾均符合预期")
    finally:
        db.close()


if __name__ == "__main__":
    main()
