"""
生成一组基于项目自定义评分维度的演示数据。
"""

from datetime import datetime, timedelta

from sqlalchemy import text

from app import models
from app.database import Base, SessionLocal, engine
from app.services.auth_service import _hash_password, register_account
from app.services.schema_bootstrap import bootstrap_schema


MEMBER_DEFINITIONS = [
    {"name": "刘峰", "tel": "13800001001", "email": "liufeng@example.com", "skills": "后端,数据库,架构", "available_hours": 42, "is_virtual_identity": False},
    {"name": "陈雨", "tel": "13800001002", "email": "chenyu@example.com", "skills": "UI,交互,前端", "available_hours": 36, "is_virtual_identity": False},
    {"name": "赵宁", "tel": "13800001003", "email": "zhaoning@example.com", "skills": "Python,接口,测试", "available_hours": 38, "is_virtual_identity": False},
    {"name": "孙悦", "tel": "13800001004", "email": "sunyue@example.com", "skills": "前端,可视化,产品", "available_hours": 34, "is_virtual_identity": False},
    {"name": "周航", "tel": "13800001005", "email": "zhouhang@example.com", "skills": "运维,DevOps,数据分析", "available_hours": 40, "is_virtual_identity": False},
]
VIRTUAL_MEMBER_DEFINITIONS = [
    {"name": "测试-产品视角", "tel": "13800009001", "skills": "产品,需求,验收", "available_hours": 0, "is_virtual_identity": True},
    {"name": "测试-前端视角", "tel": "13800009002", "skills": "前端,交互,样式", "available_hours": 0, "is_virtual_identity": True},
    {"name": "测试-后端视角", "tel": "13800009003", "skills": "后端,接口,数据库", "available_hours": 0, "is_virtual_identity": True},
]
SUPER_ACCOUNT_LOGIN_ID = "god"
SUPER_ACCOUNT_PASSWORD = "888888"
LEGACY_SUPER_ACCOUNT_LOGIN_IDS = ("seed_super_admin",)


def ensure_base_schema() -> None:
    bootstrap_schema(engine)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        module_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(modules)"))}
        if "assigned_at" not in module_columns:
            connection.execute(text("ALTER TABLE modules ADD COLUMN assigned_at DATETIME"))
        if "created_at" not in module_columns:
            connection.execute(text("ALTER TABLE modules ADD COLUMN created_at DATETIME"))


def normalize_member_payload(payload):
    normalized = dict(payload)
    email = normalized.get("email")
    if email is not None:
        email = email.strip() or None
    normalized["email"] = email
    if email is None:
        normalized["is_virtual_identity"] = True
    return normalized


def get_or_create_member(db, payload):
    normalized_payload = normalize_member_payload(payload)
    member = db.query(models.Member).filter(models.Member.tel == normalized_payload["tel"]).first()
    if member is None:
        member = models.Member(**normalized_payload)
        db.add(member)
    else:
        for key, value in normalized_payload.items():
            setattr(member, key, value)
    db.commit()
    db.refresh(member)
    return member


def ensure_virtual_members_without_accounts(db, members):
    virtual_member_ids = [member.id for member in members if member.is_virtual_identity]
    if not virtual_member_ids:
        return 0

    virtual_account_ids = [
        row[0]
        for row in db.query(models.Account.id)
        .filter(models.Account.member_id.in_(virtual_member_ids))
        .all()
    ]
    if not virtual_account_ids:
        return 0

    db.query(models.EmailVerificationToken).filter(
        models.EmailVerificationToken.account_id.in_(virtual_account_ids)
    ).delete(synchronize_session=False)
    db.query(models.AuthSession).filter(
        models.AuthSession.account_id.in_(virtual_account_ids)
    ).delete(synchronize_session=False)
    db.query(models.Account).filter(models.Account.id.in_(virtual_account_ids)).delete(
        synchronize_session=False
    )
    db.commit()
    return len(virtual_account_ids)


def ensure_seed_super_account(db):
    existing = (
        db.query(models.Account)
        .filter(models.Account.login_id == SUPER_ACCOUNT_LOGIN_ID)
        .first()
    )
    if existing is None:
        account = register_account(
            db,
            login_id=SUPER_ACCOUNT_LOGIN_ID,
            password=SUPER_ACCOUNT_PASSWORD,
            is_super_account=True,
        )
    else:
        existing.password_hash = _hash_password(SUPER_ACCOUNT_PASSWORD)
        existing.email = None
        existing.email_verified_at = datetime.now()
        existing.registration_status = "active"
        existing.is_super_account = True
        existing.member_id = None
        existing.is_active = True
        db.query(models.AuthSession).filter(
            models.AuthSession.account_id == existing.id
        ).delete(synchronize_session=False)
        account = existing

    legacy_accounts = (
        db.query(models.Account)
        .filter(models.Account.login_id.in_(LEGACY_SUPER_ACCOUNT_LOGIN_IDS))
        .all()
    )
    for legacy_account in legacy_accounts:
        db.query(models.AuthSession).filter(
            models.AuthSession.account_id == legacy_account.id
        ).delete(synchronize_session=False)
        db.delete(legacy_account)

    db.commit()
    db.refresh(account)
    return account


def clear_all_projects(db) -> None:
    module_ids = [row[0] for row in db.query(models.Module.id).all()]
    project_ids = [row[0] for row in db.query(models.Project.id).all()]

    if module_ids:
        db.query(models.FileDependency).filter(
            (models.FileDependency.preceding_module_id.in_(module_ids))
            | (models.FileDependency.dependent_module_id.in_(module_ids))
        ).delete(synchronize_session=False)
        db.query(models.ModuleFile).filter(models.ModuleFile.module_id.in_(module_ids)).delete(synchronize_session=False)
        db.query(models.ModuleSwapRequest).filter(
            (models.ModuleSwapRequest.module_id.in_(module_ids))
            | (models.ModuleSwapRequest.swap_module_id.in_(module_ids))
        ).delete(synchronize_session=False)

    assessment_ids = [row[0] for row in db.query(models.ModuleAssessment.id).all()]
    if assessment_ids:
        db.query(models.DimensionScore).filter(
            models.DimensionScore.assessment_id.in_(assessment_ids)
        ).delete(synchronize_session=False)

    if module_ids:
        db.query(models.ModuleAssessment).filter(
            models.ModuleAssessment.module_id.in_(module_ids)
        ).delete(synchronize_session=False)
        db.query(models.Module).filter(models.Module.id.in_(module_ids)).delete(synchronize_session=False)

    if project_ids:
        db.query(models.ScoringDimension).filter(
            models.ScoringDimension.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        db.query(models.ModuleSwapRequest).filter(
            models.ModuleSwapRequest.project_id.in_(project_ids)
        ).delete(synchronize_session=False)
        db.execute(models.project_members_association.delete())
        db.query(models.Project).delete(synchronize_session=False)

    db.commit()


def create_project(db, payload, members):
    dimensions = payload.pop("scoring_dimensions")
    modules = payload.pop("modules")

    project = models.Project(**payload)
    project.members = list(members)
    db.add(project)
    db.commit()
    db.refresh(project)

    db_dimensions = []
    for index, item in enumerate(dimensions):
        dimension = models.ScoringDimension(
            project_id=project.id,
            name=item["name"],
            weight=item["weight"],
            sort_order=index,
        )
        db.add(dimension)
        db_dimensions.append(dimension)
    db.commit()

    for dimension in db_dimensions:
        db.refresh(dimension)

    for module_payload in modules:
        profile = module_payload.pop("profile")
        add_module_with_assessments(db, project, module_payload, profile, db_dimensions)

    db.refresh(project)
    return project


def add_module_with_assessments(db, project, module_payload, assessment_profiles, dimensions):
    module = models.Module(project_id=project.id, **module_payload)
    db.add(module)
    db.commit()
    db.refresh(module)

    for member_id, scores in assessment_profiles.items():
        assessment = models.ModuleAssessment(member_id=member_id, module_id=module.id)
        db.add(assessment)
        db.flush()
        for dimension, score in zip(dimensions, scores):
            db.add(
                models.DimensionScore(
                    assessment_id=assessment.id,
                    dimension_id=dimension.id,
                    score=score,
                )
            )
    db.commit()


def build_profiles(base_scores):
    tweaks = [
        (0.0, 0.0, 0.0, 0.0),
        (-0.6, -0.4, -0.5, -0.3),
        (0.3, 0.4, 0.2, 0.5),
        (0.7, 0.5, 0.4, 0.6),
        (-0.4, -0.2, 0.1, -0.5),
    ]
    profiles = {}
    for index, tweak in enumerate(tweaks, start=1):
        profiles[index] = tuple(
            round(max(0.5, min(10.0, base + delta)), 1)
            for base, delta in zip(base_scores, tweak)
        )
    return profiles


def seed_demo_data():
    ensure_base_schema()
    print("正在重建演示项目数据...")
    db = SessionLocal()
    now = datetime.now()

    try:
        clear_all_projects(db)
        members = [get_or_create_member(db, payload) for payload in MEMBER_DEFINITIONS]
        virtual_members = [get_or_create_member(db, payload) for payload in VIRTUAL_MEMBER_DEFINITIONS]
        removed_virtual_accounts = ensure_virtual_members_without_accounts(
            db,
            members + virtual_members,
        )
        super_account = ensure_seed_super_account(db)
        liu_feng, chen_yu, zhao_ning, sun_yue, zhou_hang = members

        common_dimensions = [
            {"name": "复杂度", "weight": 0.30},
            {"name": "工作量", "weight": 0.30},
            {"name": "协作成本", "weight": 0.20},
            {"name": "业务价值", "weight": 0.20},
        ]

        active_project = create_project(
            db,
            {
                "name": "验收-T7A-评分期进行中",
                "description": "用于验证评分期内禁止手动拖拽分配，且模块评分全部基于项目自定义维度。",
                "status": "进行中",
                "created_by": liu_feng.id,
                "total_revenue": 120000.0,
                "assessment_start": now - timedelta(hours=1),
                "assessment_end": now + timedelta(days=2),
                "scoring_dimensions": common_dimensions,
                "modules": [
                    {
                        "name": "核心表结构设计",
                        "description": "历史已分配模块，给刘峰形成较高历史负载。",
                        "status": "已完成",
                        "assigned_to": liu_feng.id,
                        "assigned_at": now - timedelta(days=20),
                        "created_at": now - timedelta(days=22),
                        "estimated_hours": 14.0,
                        "allowed_file_types": ".sql,.md",
                        "profile": build_profiles((8.2, 8.8, 6.0, 8.5)),
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
                        "profile": build_profiles((8.0, 7.6, 5.5, 7.8)),
                    },
                    {
                        "name": "评分提醒消息中心",
                        "description": "T7A 验证专用：已评分但未分配，评分期内应禁止拖拽。",
                        "status": "待分配",
                        "assigned_to": None,
                        "assigned_at": None,
                        "created_at": now - timedelta(days=1),
                        "estimated_hours": 8.0,
                        "allowed_file_types": ".zip",
                        "profile": build_profiles((6.8, 6.3, 4.8, 7.1)),
                    },
                    {
                        "name": "综合分导出报表",
                        "description": "T7A 验证专用：已评分但未分配，评分期内应禁止拖拽。",
                        "status": "待分配",
                        "assigned_to": None,
                        "assigned_at": None,
                        "created_at": now - timedelta(days=1),
                        "estimated_hours": 9.0,
                        "allowed_file_types": ".xlsx,.pdf",
                        "profile": build_profiles((7.5, 7.2, 5.2, 7.4)),
                    },
                ],
            },
            members,
        )

        ended_project = create_project(
            db,
            {
                "name": "验收-T7A-评分期已结束",
                "description": "用于验证评分期结束后拖拽分配恢复正常。",
                "status": "进行中",
                "created_by": zhao_ning.id,
                "total_revenue": 98000.0,
                "assessment_start": now - timedelta(days=5),
                "assessment_end": now - timedelta(hours=12),
                "scoring_dimensions": [
                    {"name": "复杂度", "weight": 0.25},
                    {"name": "工作量", "weight": 0.35},
                    {"name": "协作成本", "weight": 0.15},
                    {"name": "交付价值", "weight": 0.25},
                ],
                "modules": [
                    {
                        "name": "审批流接口改造",
                        "description": "历史模块，给刘峰。",
                        "status": "已完成",
                        "assigned_to": liu_feng.id,
                        "assigned_at": now - timedelta(days=12),
                        "created_at": now - timedelta(days=13),
                        "estimated_hours": 13.0,
                        "allowed_file_types": ".zip,.md",
                        "profile": build_profiles((8.1, 8.0, 6.1, 8.3)),
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
                        "profile": build_profiles((6.6, 6.5, 4.5, 6.9)),
                    },
                    {
                        "name": "供应商对账导入",
                        "description": "T7A 验证专用：评分期结束后应可正常拖拽分配。",
                        "status": "待分配",
                        "assigned_to": None,
                        "assigned_at": None,
                        "created_at": now - timedelta(days=2),
                        "estimated_hours": 9.0,
                        "allowed_file_types": ".xlsx,.zip",
                        "profile": build_profiles((7.1, 7.4, 5.4, 7.6)),
                    },
                    {
                        "name": "项目毛利看板",
                        "description": "T7A 验证专用：评分期结束后应可正常拖拽分配。",
                        "status": "待分配",
                        "assigned_to": None,
                        "assigned_at": None,
                        "created_at": now - timedelta(days=2),
                        "estimated_hours": 11.0,
                        "allowed_file_types": ".zip,.pdf",
                        "profile": build_profiles((7.8, 7.7, 5.0, 8.1)),
                    },
                ],
            },
            members,
        )

        history_project = create_project(
            db,
            {
                "name": "验收-T7B-公平负载历史",
                "description": "用于制造 30 天历史负载差异，便于验证公平批量分配。",
                "status": "进行中",
                "created_by": zhou_hang.id,
                "total_revenue": 168000.0,
                "assessment_start": None,
                "assessment_end": None,
                "scoring_dimensions": [
                    {"name": "复杂度", "weight": 0.25},
                    {"name": "工作量", "weight": 0.35},
                    {"name": "风险系数", "weight": 0.20},
                    {"name": "业务价值", "weight": 0.20},
                ],
                "modules": [
                    {
                        "name": "分账规则引擎",
                        "description": "高负载模块，给刘峰。",
                        "status": "已完成",
                        "assigned_to": liu_feng.id,
                        "assigned_at": now - timedelta(days=28),
                        "created_at": now - timedelta(days=29),
                        "estimated_hours": 18.0,
                        "allowed_file_types": ".zip,.md",
                        "profile": build_profiles((9.2, 9.4, 8.6, 8.8)),
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
                        "profile": build_profiles((8.9, 8.8, 8.0, 8.4)),
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
                        "profile": build_profiles((8.3, 8.0, 7.2, 7.9)),
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
                        "profile": build_profiles((5.3, 5.1, 4.2, 6.4)),
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
                        "profile": build_profiles((5.8, 5.9, 4.8, 6.6)),
                    },
                ],
            },
            members,
        )

        print("已生成 5 个成员、3 个自定义维度项目和完整评分记录。")
        print(f"- 项目1（评分期进行中）: /project/{active_project.id}")
        print(f"- 项目2（评分期已结束）: /project/{ended_project.id}")
        print(f"- 项目3（公平负载历史）: /project/{history_project.id}")
        print(
            f"- 测试超级号: login_id={super_account.login_id}, password={SUPER_ACCOUNT_PASSWORD}"
        )
        print(f"- 虚拟角色池: {len(virtual_members)} 个成员（清理了 {removed_virtual_accounts} 个虚拟成员账号）")
        print("建议验证：")
        print("1. 项目创建页只能在创建时设置评分维度和权重")
        print("2. 打分页只能填分，不能修改权重")
        print("3. 项目详情页的综合分拆解会按动态维度展示")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
