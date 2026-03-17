"""
生成一组用于 T7A / T7B 手动验收的演示数据。
"""

from datetime import datetime, timedelta

from sqlalchemy import text

from app import models
from app.database import Base, SessionLocal, engine


MEMBER_DEFINITIONS = [
    {"name": "刘峰", "tel": "13800001001", "skills": "后端,数据库,架构", "available_hours": 42},
    {"name": "陈雨", "tel": "13800001002", "skills": "UI,交互,前端", "available_hours": 36},
    {"name": "赵宁", "tel": "13800001003", "skills": "Python,接口,测试", "available_hours": 38},
    {"name": "孙悦", "tel": "13800001004", "skills": "前端,可视化,产品", "available_hours": 34},
    {"name": "周航", "tel": "13800001005", "skills": "运维,DevOps,数据分析", "available_hours": 40},
]


def ensure_module_columns() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(modules)"))}
        if "assigned_at" not in columns:
            connection.execute(text("ALTER TABLE modules ADD COLUMN assigned_at DATETIME"))
        if "created_at" not in columns:
            connection.execute(text("ALTER TABLE modules ADD COLUMN created_at DATETIME"))
        member_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(members)"))}
        if "total_earnings" not in member_columns:
            connection.execute(text("ALTER TABLE members ADD COLUMN total_earnings FLOAT DEFAULT 0.0"))


def get_or_create_member(db, payload):
    member = db.query(models.Member).filter(models.Member.tel == payload["tel"]).first()
    if member is None:
        member = models.Member(**payload)
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    for key, value in payload.items():
        setattr(member, key, value)
    db.commit()
    db.refresh(member)
    return member


def clear_project_modules(db, project):
    module_ids = [module.id for module in db.query(models.Module).filter(models.Module.project_id == project.id).all()]
    if module_ids:
        db.query(models.FileDependency).filter(
            (models.FileDependency.preceding_module_id.in_(module_ids))
            | (models.FileDependency.dependent_module_id.in_(module_ids))
        ).delete(synchronize_session=False)
        db.query(models.ModuleFile).filter(models.ModuleFile.module_id.in_(module_ids)).delete(synchronize_session=False)
        db.query(models.ModuleAssessment).filter(models.ModuleAssessment.module_id.in_(module_ids)).delete(synchronize_session=False)
        db.query(models.Module).filter(models.Module.id.in_(module_ids)).delete(synchronize_session=False)
        db.commit()


def get_or_create_project(db, payload, members):
    project = db.query(models.Project).filter(models.Project.name == payload["name"]).first()
    if project is None:
        project = models.Project(**payload)
        db.add(project)
        db.commit()
        db.refresh(project)
    else:
        clear_project_modules(db, project)
        for key, value in payload.items():
            setattr(project, key, value)
        db.commit()
        db.refresh(project)

    project.members = list(members)
    db.commit()
    db.refresh(project)
    return project


def add_module_with_assessments(db, project, module_payload, assessment_profiles):
    module = models.Module(project_id=project.id, **module_payload)
    db.add(module)
    db.commit()
    db.refresh(module)

    assessments = []
    for member_id, profile in assessment_profiles.items():
        assessments.append(
            models.ModuleAssessment(
                member_id=member_id,
                module_id=module.id,
                difficulty_score=profile[0],
                estimated_hours=profile[1],
                boredom_score=profile[2],
                intensity_score=profile[3],
            )
        )

    db.add_all(assessments)
    db.commit()
    return module


def build_profiles(base_difficulty, base_hours, base_boredom, base_intensity):
    tweaks = [
        (0, 0.0, 0, 0),
        (-1, -1.0, -1, -1),
        (0, 1.0, 0, 0),
        (1, 0.5, 1, 1),
        (-1, -0.5, 0, -1),
    ]
    profiles = {}
    for index, tweak in enumerate(tweaks, start=1):
        profiles[index] = (
            max(1, min(5, base_difficulty + tweak[0])),
            round(max(1.0, base_hours + tweak[1]), 1),
            max(1, min(5, base_boredom + tweak[2])),
            max(1, min(5, base_intensity + tweak[3])),
        )
    return profiles


def seed_demo_data():
    ensure_module_columns()
    print("正在生成 T7A / T7B 验收数据...")
    db = SessionLocal()
    now = datetime.now()

    try:
        members = [get_or_create_member(db, payload) for payload in MEMBER_DEFINITIONS]
        liu_feng, chen_yu, zhao_ning, sun_yue, zhou_hang = members

        active_project = get_or_create_project(
            db,
            {
                "name": "验收-T7A-评分期进行中",
                "description": "用于验证评分期内禁止手动拖拽分配。包含已分配历史模块和两个已评分待分配模块。",
                "status": "进行中",
                "created_by": liu_feng.id,
                "total_revenue": 120000.0,
                "assessment_start": now - timedelta(hours=1),
                "assessment_end": now + timedelta(days=2),
                "weight_difficulty": 0.30,
                "weight_hours": 0.30,
                "weight_boredom": 0.20,
                "weight_intensity": 0.20,
            },
            members,
        )

        ended_project = get_or_create_project(
            db,
            {
                "name": "验收-T7A-评分期已结束",
                "description": "用于验证评分期结束后拖拽分配恢复正常。包含两个已评分待分配模块。",
                "status": "进行中",
                "created_by": zhao_ning.id,
                "total_revenue": 98000.0,
                "assessment_start": now - timedelta(days=5),
                "assessment_end": now - timedelta(hours=12),
                "weight_difficulty": 0.25,
                "weight_hours": 0.35,
                "weight_boredom": 0.20,
                "weight_intensity": 0.20,
            },
            members,
        )

        history_project = get_or_create_project(
            db,
            {
                "name": "验收-T7B-公平负载历史",
                "description": "用于制造 30 天历史负载差异，便于后续验证公平批量分配。",
                "status": "进行中",
                "created_by": zhou_hang.id,
                "total_revenue": 168000.0,
                "assessment_start": None,
                "assessment_end": None,
                "weight_difficulty": 0.25,
                "weight_hours": 0.40,
                "weight_boredom": 0.15,
                "weight_intensity": 0.20,
            },
            members,
        )

        active_modules = [
            {
                "name": "核心表结构设计",
                "description": "历史已分配模块，给刘峰形成较高历史负载。",
                "status": "已完成",
                "assigned_to": liu_feng.id,
                "assigned_at": now - timedelta(days=20),
                "created_at": now - timedelta(days=22),
                "estimated_hours": 14.0,
                "allowed_file_types": ".sql,.md",
                "profile": build_profiles(4, 15.0, 3, 4),
            },
            {
                "name": "登录与权限接口",
                "description": "历史已分配模块，给赵宁。",
                "status": "已完成",
                "assigned_to": zhao_ning.id,
                "assigned_at": now - timedelta(days=18),
                "created_at": now - timedelta(days=19),
                "estimated_hours": 12.0,
                "allowed_file_types": ".zip,.md",
                "profile": build_profiles(4, 12.0, 2, 4),
            },
            {
                "name": "交互原型与视觉稿",
                "description": "历史已分配模块，给陈雨。",
                "status": "已完成",
                "assigned_to": chen_yu.id,
                "assigned_at": now - timedelta(days=15),
                "created_at": now - timedelta(days=16),
                "estimated_hours": 11.0,
                "allowed_file_types": ".fig,.pdf",
                "profile": build_profiles(3, 11.0, 2, 2),
            },
            {
                "name": "数据看板前端实现",
                "description": "历史已分配模块，给孙悦。",
                "status": "开发中",
                "assigned_to": sun_yue.id,
                "assigned_at": now - timedelta(days=10),
                "created_at": now - timedelta(days=11),
                "estimated_hours": 10.0,
                "allowed_file_types": ".zip,.md",
                "profile": build_profiles(3, 10.0, 3, 3),
            },
            {
                "name": "评分提醒消息中心",
                "description": "T7A 手动验证专用：已评分但未分配，评分期内应禁止拖拽。",
                "status": "待分配",
                "assigned_to": None,
                "assigned_at": None,
                "created_at": now - timedelta(days=1),
                "estimated_hours": 8.0,
                "allowed_file_types": ".zip",
                "profile": build_profiles(3, 8.0, 2, 3),
            },
            {
                "name": "综合分导出报表",
                "description": "T7A 手动验证专用：已评分但未分配，评分期内应禁止拖拽。",
                "status": "待分配",
                "assigned_to": None,
                "assigned_at": None,
                "created_at": now - timedelta(days=1),
                "estimated_hours": 9.0,
                "allowed_file_types": ".xlsx,.pdf",
                "profile": build_profiles(4, 9.5, 3, 3),
            },
        ]

        ended_modules = [
            {
                "name": "需求访谈纪要整理",
                "description": "历史模块，给周航。",
                "status": "已完成",
                "assigned_to": zhou_hang.id,
                "assigned_at": now - timedelta(days=14),
                "created_at": now - timedelta(days=16),
                "estimated_hours": 7.0,
                "allowed_file_types": ".docx,.pdf",
                "profile": build_profiles(2, 7.0, 2, 2),
            },
            {
                "name": "审批流接口改造",
                "description": "历史模块，给刘峰。",
                "status": "已完成",
                "assigned_to": liu_feng.id,
                "assigned_at": now - timedelta(days=12),
                "created_at": now - timedelta(days=13),
                "estimated_hours": 13.0,
                "allowed_file_types": ".zip,.md",
                "profile": build_profiles(4, 13.0, 3, 4),
            },
            {
                "name": "移动端适配样式",
                "description": "历史模块，给陈雨。",
                "status": "开发中",
                "assigned_to": chen_yu.id,
                "assigned_at": now - timedelta(days=9),
                "created_at": now - timedelta(days=10),
                "estimated_hours": 8.5,
                "allowed_file_types": ".fig,.zip",
                "profile": build_profiles(3, 8.5, 2, 2),
            },
            {
                "name": "审计日志追踪",
                "description": "历史模块，给赵宁。",
                "status": "已完成",
                "assigned_to": zhao_ning.id,
                "assigned_at": now - timedelta(days=7),
                "created_at": now - timedelta(days=8),
                "estimated_hours": 10.0,
                "allowed_file_types": ".zip,.sql",
                "profile": build_profiles(4, 10.0, 3, 4),
            },
            {
                "name": "供应商对账导入",
                "description": "T7A 手动验证专用：评分期结束后应可正常拖拽分配。",
                "status": "待分配",
                "assigned_to": None,
                "assigned_at": None,
                "created_at": now - timedelta(days=2),
                "estimated_hours": 9.0,
                "allowed_file_types": ".xlsx,.zip",
                "profile": build_profiles(3, 9.0, 3, 3),
            },
            {
                "name": "项目毛利看板",
                "description": "T7A 手动验证专用：评分期结束后应可正常拖拽分配。",
                "status": "待分配",
                "assigned_to": None,
                "assigned_at": None,
                "created_at": now - timedelta(days=2),
                "estimated_hours": 11.0,
                "allowed_file_types": ".zip,.pdf",
                "profile": build_profiles(4, 11.0, 2, 3),
            },
        ]

        history_modules = [
            {
                "name": "分账规则引擎",
                "description": "高负载模块，给刘峰。",
                "status": "已完成",
                "assigned_to": liu_feng.id,
                "assigned_at": now - timedelta(days=28),
                "created_at": now - timedelta(days=29),
                "estimated_hours": 18.0,
                "allowed_file_types": ".zip,.md",
                "profile": build_profiles(5, 18.0, 4, 5),
            },
            {
                "name": "结算批处理任务",
                "description": "高负载模块，给刘峰。",
                "status": "已完成",
                "assigned_to": liu_feng.id,
                "assigned_at": now - timedelta(days=24),
                "created_at": now - timedelta(days=25),
                "estimated_hours": 16.0,
                "allowed_file_types": ".zip,.sql",
                "profile": build_profiles(5, 16.0, 4, 4),
            },
            {
                "name": "经营数据宽表整理",
                "description": "中高负载模块，给赵宁。",
                "status": "已完成",
                "assigned_to": zhao_ning.id,
                "assigned_at": now - timedelta(days=21),
                "created_at": now - timedelta(days=22),
                "estimated_hours": 14.0,
                "allowed_file_types": ".sql,.csv",
                "profile": build_profiles(4, 14.0, 3, 4),
            },
            {
                "name": "权限矩阵梳理",
                "description": "中负载模块，给陈雨。",
                "status": "已完成",
                "assigned_to": chen_yu.id,
                "assigned_at": now - timedelta(days=17),
                "created_at": now - timedelta(days=18),
                "estimated_hours": 9.0,
                "allowed_file_types": ".fig,.xlsx",
                "profile": build_profiles(3, 9.0, 2, 2),
            },
            {
                "name": "移动端筛选组件",
                "description": "中负载模块，给孙悦。",
                "status": "已完成",
                "assigned_to": sun_yue.id,
                "assigned_at": now - timedelta(days=13),
                "created_at": now - timedelta(days=14),
                "estimated_hours": 8.0,
                "allowed_file_types": ".zip,.fig",
                "profile": build_profiles(3, 8.0, 2, 3),
            },
            {
                "name": "监控告警落库",
                "description": "中低负载模块，给周航。",
                "status": "已完成",
                "assigned_to": zhou_hang.id,
                "assigned_at": now - timedelta(days=11),
                "created_at": now - timedelta(days=12),
                "estimated_hours": 7.0,
                "allowed_file_types": ".yaml,.md",
                "profile": build_profiles(3, 7.0, 2, 2),
            },
            {
                "name": "归档策略脚本",
                "description": "中低负载模块，再给周航。",
                "status": "开发中",
                "assigned_to": zhou_hang.id,
                "assigned_at": now - timedelta(days=6),
                "created_at": now - timedelta(days=7),
                "estimated_hours": 6.5,
                "allowed_file_types": ".py,.md",
                "profile": build_profiles(2, 6.5, 2, 2),
            },
            {
                "name": "视觉规范补充",
                "description": "低负载模块，再给陈雨。",
                "status": "已完成",
                "assigned_to": chen_yu.id,
                "assigned_at": now - timedelta(days=4),
                "created_at": now - timedelta(days=5),
                "estimated_hours": 5.5,
                "allowed_file_types": ".fig,.pdf",
                "profile": build_profiles(2, 5.5, 1, 1),
            },
        ]

        for item in active_modules:
            profile = item.pop("profile")
            add_module_with_assessments(db, active_project, item, profile)

        for item in ended_modules:
            profile = item.pop("profile")
            add_module_with_assessments(db, ended_project, item, profile)

        for item in history_modules:
            profile = item.pop("profile")
            add_module_with_assessments(db, history_project, item, profile)

        print("已生成 5 个验收成员、3 个验收项目和完整评分数据。")
        print(f"- 项目1（评分期进行中）: /projects/{active_project.id}/detail")
        print(f"- 项目2（评分期已结束）: /projects/{ended_project.id}/detail")
        print(f"- 项目3（公平负载历史）: /projects/{history_project.id}/detail")
        print("建议手动验证：")
        print("1. 在项目1里拖拽“评分提醒消息中心”或“综合分导出报表”，应被禁止")
        print("2. 在项目2里拖拽“供应商对账导入”或“项目毛利看板”，应允许成功")
        print("3. 用项目3观察 30 天历史负载分布，刘峰应明显高于其他成员")
    except Exception as exc:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
