from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models
from app.api.scoring import _calc_module_summary


def get_member_30day_load(member_id: int, db: Session) -> float:
    cutoff = datetime.now() - timedelta(days=30)
    modules = db.query(models.Module).filter(
        models.Module.assigned_to == member_id,
        models.Module.status != "待分配",
    ).all()

    recent_modules = []
    for module in modules:
        reference_time = getattr(module, "assigned_at", None) or getattr(module, "created_at", None)
        if reference_time is not None and reference_time >= cutoff:
            recent_modules.append(module)

    if not recent_modules:
        return 0.0

    project_ids = list({module.project_id for module in recent_modules if module.project_id is not None})
    projects = db.query(models.Project).filter(models.Project.id.in_(project_ids)).all()
    project_map = {project.id: project for project in projects}

    total_load = 0.0
    for module in recent_modules:
        project = project_map.get(module.project_id)
        if project is None:
            continue

        summary = _calc_module_summary(module, project, db)
        total_load += float(summary.get("composite_score", 0.0) or 0.0)

    return round(total_load, 2)
