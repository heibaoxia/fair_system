from app.database import SessionLocal
from app import models


PROJECT_NAMES = [
    "验收-T7A-评分期进行中",
    "验收-T7A-评分期已结束",
    "验收-T7B-公平负载历史",
]


def main() -> None:
    db = SessionLocal()
    try:
        print("=== T9 验收辅助信息 ===")
        for name in PROJECT_NAMES:
            project = db.query(models.Project).filter(models.Project.name == name).first()
            if project is None:
                print(f"[缺失项目] {name}")
                continue

            print(f"\n项目: {project.name}")
            print(f"- 项目ID: {project.id}")
            print(f"- 创建者ID: {project.created_by}")
            print(f"- 页面地址: http://127.0.0.1:8000/project/{project.id}")
            print("- 成员:")
            for member in project.members:
                print(f"  - {member.id}: {member.name}")

            modules = db.query(models.Module).filter(models.Module.project_id == project.id).all()
            print("- 模块:")
            for module in modules:
                print(
                    f"  - {module.id}: {module.name} | 状态={module.status} | 负责人={module.assigned_to}"
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()
