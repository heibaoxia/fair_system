from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List

from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app
from seed_demo_data import seed_demo_data


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def assert_true(condition: bool, success: str, failure: str) -> str:
    if not condition:
        raise AssertionError(failure)
    return success


def get_project_by_name(db, name: str) -> models.Project:
    project = db.query(models.Project).filter(models.Project.name == name).first()
    if project is None:
        raise AssertionError(f"缺少验收项目：{name}")
    return project


def get_modules_by_project(db, project_id: int) -> List[models.Module]:
    return db.query(models.Module).filter(models.Module.project_id == project_id).order_by(models.Module.id.asc()).all()


def collect_assignments(preview_payload: Dict) -> Dict[str, List[int]]:
    assignments: Dict[str, List[int]] = {}
    for item in preview_payload.get("member_loads", []):
        module_ids = list(item.get("assigned_modules", []))
        if module_ids:
            assignments[str(item["member_id"])] = module_ids
    return assignments


def run_check(name: str, fn: Callable[[], str]) -> CheckResult:
    try:
        detail = fn()
        return CheckResult(name=name, passed=True, detail=detail)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, passed=False, detail=str(exc))


def main() -> None:
    seed_demo_data()
    client = TestClient(app)
    db = SessionLocal()

    try:
        active_project = get_project_by_name(db, "验收-T7A-评分期进行中")
        ended_project = get_project_by_name(db, "验收-T7A-评分期已结束")

        ended_pending_modules = [
            module for module in get_modules_by_project(db, ended_project.id) if module.status == "待分配"
        ]
        ended_non_pending_modules = [
            module for module in get_modules_by_project(db, ended_project.id) if module.status != "待分配"
        ]
        ended_creator_id = int(ended_project.created_by)
        ended_non_creator_id = next(int(member.id) for member in ended_project.members if int(member.id) != ended_creator_id)

        results = [
            run_check(
                "T9-1 页面包含一键分配与微调 UI",
                lambda: assert_true(
                    all(
                        token in client.get(f"/project/{ended_project.id}").text
                        for token in [
                            "batch-assignment-trigger",
                            "batch-assignment-modal",
                            "confirmBatchAssignmentPreview",
                            "enterBatchAdjustmentMode",
                            "confirmBatchAdjustmentMode",
                            "评分期内禁止手动分配",
                        ]
                    ),
                    "项目详情页已包含 T9 关键 UI 与交互函数",
                    "项目详情页缺少 T9 关键 UI 或交互函数",
                ),
            ),
            run_check(
                "T9-2 评分未完成时 batch 返回 400",
                lambda: assert_true(
                    client.post(f"/assignments/batch/{active_project.id}").status_code == 400,
                    f"项目 {active_project.id} 在评分期内正确拒绝一键分配预览",
                    f"项目 {active_project.id} 未按预期返回 400",
                ),
            ),
            run_check(
                "T9-3 已结束项目可返回预览数据",
                lambda: preview_check(client, ended_project.id),
            ),
            run_check(
                "T9-4 预览不修改数据库",
                lambda: preview_no_mutation_check(client, db, ended_project.id, len(ended_pending_modules)),
            ),
            run_check(
                "T9-5 非创建者不能直接开工",
                lambda: non_creator_confirm_check(client, ended_project.id, ended_non_creator_id),
            ),
            run_check(
                "T9-6 直接开工后模块变开发中且记录 assigned_at",
                lambda: confirm_and_persist_check(
                    client,
                    db,
                    ended_project.id,
                    ended_creator_id,
                    ended_pending_modules,
                ),
            ),
            run_check(
                "T9-7 非待分配模块不参与 batch",
                lambda: non_pending_not_included_check(client, ended_project.id, ended_non_pending_modules),
            ),
            run_check(
                "T9-8 开工后没有待分配模块",
                lambda: no_pending_after_confirm_check(db, ended_project.id),
            ),
        ]

        print("=== T9 自动化验收结果 ===")
        failures = 0
        for result in results:
            prefix = "[PASS]" if result.passed else "[FAIL]"
            print(f"{prefix} {result.name} - {result.detail}")
            if not result.passed:
                failures += 1

        if failures:
            raise SystemExit(1)

        print("全部通过。若要恢复初始验收数据，可再次运行 `python seed_demo_data.py`。")
    finally:
        db.close()


def preview_check(client: TestClient, project_id: int) -> str:
    response = client.post(f"/assignments/batch/{project_id}")
    payload = response.json()
    if response.status_code != 200:
        raise AssertionError(f"预览接口返回 {response.status_code}: {payload}")

    member_loads = payload.get("member_loads", [])
    if not member_loads:
        raise AssertionError("预览结果缺少 member_loads")

    required_fields = {
        "member_id",
        "member_name",
        "existing_30day_score",
        "new_assigned_score",
        "total_30day_score",
        "assigned_modules",
    }
    first_item = member_loads[0]
    if not required_fields.issubset(first_item.keys()):
        raise AssertionError(f"预览结果字段不完整: {first_item}")

    fairness_index = payload.get("fairness_index")
    if fairness_index is None:
        raise AssertionError("预览结果缺少 fairness_index")

    return f"预览返回 {len(member_loads)} 条成员负载数据，fairness_index={fairness_index}"


def preview_no_mutation_check(client: TestClient, db, project_id: int, expected_pending_count: int) -> str:
    before = db.query(models.Module).filter(models.Module.project_id == project_id, models.Module.status == "待分配").count()
    response = client.post(f"/assignments/batch/{project_id}")
    if response.status_code != 200:
        raise AssertionError(f"预览失败，无法验证不落库: {response.json()}")
    after = db.query(models.Module).filter(models.Module.project_id == project_id, models.Module.status == "待分配").count()
    if before != expected_pending_count or after != expected_pending_count:
        raise AssertionError(f"预览前后待分配数量异常: before={before}, after={after}, expected={expected_pending_count}")
    return f"预览前后待分配模块数量保持 {after}，未改数据库"


def non_creator_confirm_check(client: TestClient, project_id: int, current_member_id: int) -> str:
    preview_payload = client.post(f"/assignments/batch/{project_id}").json()
    assignments = collect_assignments(preview_payload)
    response = client.post(
        f"/assignments/batch/{project_id}/confirm",
        params={"current_member_id": current_member_id},
        json={"assignments": assignments},
    )
    if response.status_code != 403:
        raise AssertionError(f"非创建者确认未被拒绝: {response.status_code}, {response.json()}")
    return "非创建者调用 confirm 正确返回 403"


def confirm_and_persist_check(
    client: TestClient,
    db,
    project_id: int,
    current_member_id: int,
    pending_modules: Iterable[models.Module],
) -> str:
    preview_payload = client.post(f"/assignments/batch/{project_id}").json()
    assignments = collect_assignments(preview_payload)
    if not assignments:
        raise AssertionError("预览结果没有任何待确认分配模块")

    response = client.post(
        f"/assignments/batch/{project_id}/confirm",
        params={"current_member_id": current_member_id},
        json={"assignments": assignments},
    )
    payload = response.json()
    if response.status_code != 200:
        raise AssertionError(f"直接开工失败: {payload}")

    pending_ids = sorted(int(module.id) for module in pending_modules)
    db.expire_all()
    refreshed_modules = db.query(models.Module).filter(models.Module.id.in_(pending_ids)).all()
    invalid = [
        (module.id, module.status, module.assigned_to, getattr(module, "assigned_at", None))
        for module in refreshed_modules
        if module.status != "开发中" or module.assigned_to is None or getattr(module, "assigned_at", None) is None
    ]
    if invalid:
        raise AssertionError(f"以下模块未正确开工: {invalid}")
    return f"{len(refreshed_modules)} 个待分配模块已进入开发中并记录 assigned_at"


def non_pending_not_included_check(client: TestClient, project_id: int, non_pending_modules: Iterable[models.Module]) -> str:
    response = client.post(f"/assignments/batch/{project_id}")
    if response.status_code == 200:
        preview_payload = response.json()
        assigned_ids = {module_id for ids in collect_assignments(preview_payload).values() for module_id in ids}
    else:
        assigned_ids = set()

    non_pending_ids = {int(module.id) for module in non_pending_modules}
    overlap = assigned_ids & non_pending_ids
    if overlap:
        raise AssertionError(f"非待分配模块被错误纳入预览: {sorted(overlap)}")
    return "预览方案未包含任何非待分配模块"


def no_pending_after_confirm_check(db, project_id: int) -> str:
    remaining = db.query(models.Module).filter(models.Module.project_id == project_id, models.Module.status == "待分配").count()
    if remaining != 0:
        raise AssertionError(f"确认开工后仍有 {remaining} 个待分配模块")
    return "确认开工后项目已无待分配模块，可对应前端禁用一键分配按钮"


if __name__ == "__main__":
    main()
