"""
Fair-System 前端网页路由
负责渲染 HTML 模板页面，给前端展示带样式的网页。
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit

from app.api.dependencies import (
    SESSION_COOKIE_NAME,
    CurrentMemberContext,
    get_db,
)
from app.api.project_access import (
    build_visible_projects_query,
    ensure_project_visible,
    require_business_member,
)
from app import models
from app.models import Project, Member, Module
from app.services.calculator import ProjectContributionCalculator
from app.api.notifications import get_pending_assessments_for_member
from app.api.scoring import _calc_module_summary, build_project_summary_payload
from app.api.swaps import get_pending_swap_requests
from app.services.auth_service import load_session

router = APIRouter(tags=["前端页面"])

templates = Jinja2Templates(directory="app/templates")


def _build_login_redirect_url(request: Request) -> str:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    safe_next_path = _sanitize_next_path(next_path)
    return f"/login?next={quote(safe_next_path, safe='')}"


def _sanitize_next_path(next_path: str | None) -> str:
    if not next_path:
        return "/"

    parsed = urlsplit(next_path)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    if "\\" in parsed.path:
        return "/"
    return next_path


def _resolve_member_context(request: Request, db: Session) -> CurrentMemberContext | None:
    session_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    session = load_session(db, session_token)
    if session is None:
        return None
    return CurrentMemberContext(
        session=session,
        account=session.account,
        bound_member=session.account.member,
        acting_member=session.acting_member,
    )


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _build_scoring_dimensions_payload(project: Project, db: Session):
    dimensions = db.query(models.ScoringDimension).filter(
        models.ScoringDimension.project_id == project.id
    ).order_by(models.ScoringDimension.sort_order.asc(), models.ScoringDimension.id.asc()).all()

    return [
        {
            "id": dimension.id,
            "name": dimension.name,
            "weight": _as_float(dimension.weight, 0.0),
            "sort_order": _as_int(dimension.sort_order, 0),
            "max_score": _as_float(dimension.max_score, 10.0),
        }
        for dimension in dimensions
    ]


def _build_member_assessment_lookup(project: Project, member_id: int, db: Session):
    modules = db.query(Module).filter(Module.project_id == project.id).order_by(Module.id.asc()).all()
    dimensions = _build_scoring_dimensions_payload(project, db)
    module_ids = [module.id for module in modules]
    assessments = []
    if module_ids:
        assessments = db.query(models.ModuleAssessment).filter(
            models.ModuleAssessment.member_id == member_id,
            models.ModuleAssessment.module_id.in_(module_ids),
        ).all()

    assessment_map = {}
    for assessment in assessments:
        dimension_score_map = {
            score.dimension_id: round(float(score.score or 0.0), 1)
            for score in getattr(assessment, "dimension_scores", []) or []
        }
        review_scores = []
        for dimension in dimensions:
            score_value = dimension_score_map.get(dimension["id"], 0.0)
            review_scores.append({
                "name": dimension["name"],
                "score": score_value,
                "weight": dimension["weight"],
            })

        assessment_map[assessment.module_id] = {
            "assessment_id": assessment.id,
            "review_scores": review_scores,
        }

    module_payload = []
    for module in modules:
        current_assessment = assessment_map.get(module.id)
        module_payload.append({
            "id": module.id,
            "name": module.name,
            "description": module.description or "",
            "status": getattr(module, "status", ""),
            "is_scored": current_assessment is not None,
            "assessment": current_assessment,
        })

    return dimensions, module_payload


@router.get("/")
def show_index(request: Request, db: Session = Depends(get_db)):
    """系统主页面（工作台）"""
    context = _resolve_member_context(request, db)
    if context is None:
        return RedirectResponse(url=_build_login_redirect_url(request), status_code=303)

    projects = build_visible_projects_query(db, context).all()
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
    context = _resolve_member_context(request, db)
    if context is None:
        return RedirectResponse(url=_build_login_redirect_url(request), status_code=303)

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    ensure_project_visible(project, context)
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
    is_project_manager = (
        context.acting_member is not None and context.acting_member.id == project.created_by
    )

    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "project": project,
        "members": project.members,
        "is_project_manager": is_project_manager,
        "modules": modules,
        "dependencies": dependencies,
        "dependency_pairs": dependency_pairs,
    })


@router.get("/members")
def show_members_page(request: Request):
    return templates.TemplateResponse("members.html", {"request": request})


@router.get("/social")
def show_social_page(request: Request, db: Session = Depends(get_db)):
    context = _resolve_member_context(request, db)
    if context is None:
        return RedirectResponse(url=_build_login_redirect_url(request), status_code=303)

    return templates.TemplateResponse("social.html", {"request": request})


@router.get("/overview")
def show_overview_page(request: Request, db: Session = Depends(get_db)):
    context = _resolve_member_context(request, db)
    if context is None:
        return RedirectResponse(url=_build_login_redirect_url(request), status_code=303)

    projects = build_visible_projects_query(db, context).all()
    return templates.TemplateResponse("overview.html", {"request": request, "projects": projects})


@router.get("/todo")
def show_todo_page(request: Request, db: Session = Depends(get_db)):
    """待办页面：显示该成员的待打分模块和其他待办事项"""
    context = _resolve_member_context(request, db)
    if context is None:
        return RedirectResponse(url=_build_login_redirect_url(request), status_code=303)

    member = require_business_member(context, "请选择当前业务身份后再查看待办。")
    member_id = member.id

    pending_data = {"pending": [], "total_pending": 0, "total_expired": 0}
    pending_swaps = []
    active_work_modules = []
    grouped_pending = []
    wallet_summary = {
        "settled_amount": 0.0,
        "pending_estimated_amount": 0.0,
    }

    if member_id > 0:
        pending_data = get_pending_assessments_for_member(member_id, db)
        pending_swaps = get_pending_swap_requests(member_id, db)

        grouped_pending_map = {}
        for item in pending_data.get("pending", []):
            project_id = item.get("project_id")
            if project_id is None or item.get("is_expired"):
                continue

            current_group = grouped_pending_map.get(project_id)
            deadline_text = item.get("assessment_end")
            deadline_value = None
            if isinstance(deadline_text, str):
                try:
                    deadline_value = datetime.fromisoformat(deadline_text)
                except ValueError:
                    deadline_value = None

            if current_group is None:
                grouped_pending_map[project_id] = {
                    "project_id": project_id,
                    "project_name": item.get("project_name", f"项目 #{project_id}"),
                    "module_count": 1,
                    "earliest_deadline": deadline_text,
                    "_deadline_value": deadline_value,
                }
                continue

            current_group["module_count"] += 1
            current_deadline = current_group.get("_deadline_value")
            if deadline_value is not None and (current_deadline is None or deadline_value < current_deadline):
                current_group["earliest_deadline"] = deadline_text
                current_group["_deadline_value"] = deadline_value

        grouped_pending = sorted(
            grouped_pending_map.values(),
            key=lambda item: (item.get("_deadline_value") is None, item.get("_deadline_value") or datetime.max, item["project_name"])
        )
        for item in grouped_pending:
            item.pop("_deadline_value", None)

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
        "grouped_pending": grouped_pending,
        "pending_swaps": pending_swaps,
        "active_work_modules": active_work_modules,
        "wallet_summary": wallet_summary,
    })


@router.get("/login")
def show_login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    safe_next = _sanitize_next_path(next)
    context = _resolve_member_context(request, db)
    if context is not None:
        return RedirectResponse(url=safe_next, status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "next_url": safe_next})


@router.get("/register")
def show_register_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    safe_next = _sanitize_next_path(next)
    context = _resolve_member_context(request, db)
    if context is not None:
        return RedirectResponse(url=safe_next, status_code=303)
    return templates.TemplateResponse("register.html", {"request": request, "next_url": safe_next})


@router.get("/timeline/{project_id}")
def show_timeline(request: Request, project_id: int, db: Session = Depends(get_db)):
    """
    项目全局监控大盘。
    计算真实进度百分比（加权），以及每个模块计划耗时 vs 实际耗时。
    """
    context = _resolve_member_context(request, db)
    if context is None:
        return RedirectResponse(url=_build_login_redirect_url(request), status_code=303)

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    ensure_project_visible(project, context)

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


@router.get("/scoring/{project_id}")
def show_scoring_page(request: Request, project_id: int, db: Session = Depends(get_db)):
    context = _resolve_member_context(request, db)
    if context is None:
        return RedirectResponse(url=_build_login_redirect_url(request), status_code=303)

    member = require_business_member(context, "请选择当前业务身份后再评分。")
    member_id = member.id

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if member not in project.members:
        raise HTTPException(status_code=403, detail="你不是该项目的组员，无权评分")

    scoring_dimensions, modules = _build_member_assessment_lookup(project, member_id, db)

    return templates.TemplateResponse("scoring_page.html", {
        "request": request,
        "project": project,
        "member": member,
        "member_id": member_id,
        "scoring_dimensions": scoring_dimensions,
        "modules": modules,
    })
