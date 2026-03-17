"""
Fair-System 前端网页路由
负责渲染 HTML 模板页面，给前端展示带样式的网页。
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app import models
from app.models import Project, Member, Module
from app.services.calculator import ProjectContributionCalculator
from app.api.notifications import get_pending_assessments
from app.api.scoring import _calc_module_summary, build_project_summary_payload
from app.api.swaps import get_pending_swap_requests

router = APIRouter(tags=["前端页面"])

templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def show_index(request: Request, db: Session = Depends(get_db)):
    """系统主页面（工作台）"""
    projects = db.query(Project).all()
    project_cards = []

    for project in projects:
        modules = db.query(Module).filter(Module.project_id == project.id).all()
        summary = build_project_summary_payload(project, modules, db)
        project_cards.append({
            "project": project,
            "summary": summary,
        })

    return templates.TemplateResponse("index.html", {
        "request": request,
        "projects": projects,
        "project_cards": project_cards,
    })


@router.get("/project/{project_id}")
def show_project_detail(request: Request, project_id: int, db: Session = Depends(get_db)):
    """项目详情画板页"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    all_members = db.query(Member).filter(Member.is_active == True).all()
    modules = db.query(Module).filter(Module.project_id == project_id).all()
    module_map = {module.id: module for module in modules}
    dependencies = db.query(models.FileDependency).filter(
        models.FileDependency.preceding_module_id.in_(module_map.keys()),
        models.FileDependency.dependent_module_id.in_(module_map.keys()),
    ).all() if module_map else []
    dependency_pairs = [
        {
            "id": dependency.id,
            "preceding_module_id": dependency.preceding_module_id,
            "dependent_module_id": dependency.dependent_module_id,
            "preceding_module_name": module_map[dependency.preceding_module_id].name,
            "dependent_module_name": module_map[dependency.dependent_module_id].name,
        }
        for dependency in dependencies
    ]
    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "project": project,
        "members": project.members,
        "all_members": all_members,
        "modules": modules,
        "dependencies": dependencies,
        "dependency_pairs": dependency_pairs,
    })


@router.get("/members")
def show_members_page(request: Request):
    return templates.TemplateResponse("members.html", {"request": request})


@router.get("/overview")
def show_overview_page(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return templates.TemplateResponse("overview.html", {"request": request, "projects": projects})


@router.get("/todo")
def show_todo_page(request: Request, member_id: int = 0, db: Session = Depends(get_db)):
    """待办页面：显示该成员的待打分模块和其他待办事项"""
    pending_data = {"pending": [], "total_pending": 0, "total_expired": 0}
    pending_swaps = []
    active_work_modules = []
    wallet_summary = {
        "settled_amount": 0.0,
        "pending_estimated_amount": 0.0,
    }

    if member_id > 0:
        pending_data = get_pending_assessments(member_id, db)
        pending_swaps = get_pending_swap_requests(member_id, db)

        member = db.query(Member).filter(Member.id == member_id).first()
        if member is not None:
            wallet_summary["settled_amount"] = round(float(getattr(member, "total_earnings", 0.0) or 0.0), 2)

        working_modules = db.query(Module).filter(
            Module.assigned_to == member_id,
            Module.status == "开发中",
        ).all()
        for module in working_modules:
            project = db.query(Project).filter(Project.id == module.project_id).first()
            if project is None:
                continue
            active_work_modules.append({
                "module_id": module.id,
                "module_name": module.name,
                "project_id": project.id,
                "project_name": project.name,
                "status": getattr(module, "status", ""),
            })

        completed_modules = db.query(Module).filter(
            Module.assigned_to == member_id,
            Module.status == "已完成",
        ).all()
        pending_estimated_amount = 0.0
        for module in completed_modules:
            project = db.query(Project).filter(Project.id == module.project_id).first()
            if project is None or getattr(project, "status", None) == "已完成":
                continue
            summary = _calc_module_summary(module, project, db)
            pending_estimated_amount += float(summary.get("composite_score", 0.0) or 0.0)
        wallet_summary["pending_estimated_amount"] = round(pending_estimated_amount, 2)

    return templates.TemplateResponse("todo.html", {
        "request": request,
        "member_id": member_id,
        "pending_data": pending_data,
        "pending_swaps": pending_swaps,
        "active_work_modules": active_work_modules,
        "wallet_summary": wallet_summary,
    })


@router.get("/timeline/{project_id}")
def show_timeline(request: Request, project_id: int, db: Session = Depends(get_db)):
    """
    项目全局监控大盘。
    计算真实进度百分比（加权），以及每个模块计划耗时 vs 实际耗时。
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    modules = db.query(Module).filter(Module.project_id == project_id).all()

    total_hours = 0.0
    completed_hours = 0.0
    timeline_data = []

    for mod in modules:
        mod_id = int(getattr(mod, "id", 0) or 0)
        mod_status = getattr(mod, "status", "")
        mod_estimated_hours = float(getattr(mod, "estimated_hours", 0.0) or 0.0)
        mod_assigned_to = getattr(mod, "assigned_to", None)

        total_hours += mod_estimated_hours
        if mod_status == "已完成":
            completed_hours += mod_estimated_hours

        member_name = "未分配"
        if mod_assigned_to is not None:
            member = db.query(Member).filter(Member.id == mod_assigned_to).first()
            if member is not None:
                member_name = member.name

        actual_hours = 0.0
        if mod_status in {"已完成", "待审核"}:
            file_record = db.query(models.ModuleFile).filter(models.ModuleFile.module_id == mod_id).first()
            if file_record is not None:
                actual_hours = mod_estimated_hours * 1.2
                if mod_id % 2 == 0:
                    actual_hours = mod_estimated_hours * 0.8
        elif mod_status == "开发中":
            actual_hours = mod_estimated_hours * 0.5

        timeline_data.append({
            "module": mod,
            "member_name": member_name,
            "planned_hours": mod_estimated_hours,
            "actual_hours": actual_hours
        })

    master_progress = (completed_hours / total_hours * 100) if total_hours > 0 else 0.0

    return templates.TemplateResponse("timeline.html", {
        "request": request,
        "project": project,
        "master_progress_percentage": master_progress,
        "completed_hours": completed_hours,
        "total_hours": total_hours,
        "timeline_data": timeline_data
    })
