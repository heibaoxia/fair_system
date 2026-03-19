from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.dependencies import CurrentMemberContext, get_current_member_context, get_db
from app.api.project_access import ensure_project_manager, ensure_project_visible, get_project_or_404
from app.utils.dependency_checker import would_create_cycle

router = APIRouter(tags=["project-dependencies"])


def _get_dependency_or_404(project_id: int, dependency_id: int, db: Session) -> models.FileDependency:
    dependency = db.query(models.FileDependency).filter(models.FileDependency.id == dependency_id).first()
    if dependency is None:
        raise HTTPException(status_code=404, detail="Dependency not found.")

    module_ids = {
        module.id for module in db.query(models.Module).filter(models.Module.project_id == project_id).all()
    }
    if dependency.preceding_module_id not in module_ids or dependency.dependent_module_id not in module_ids:
        raise HTTPException(status_code=404, detail="Dependency does not belong to this project.")
    return dependency


@router.get("/projects/{project_id}/dependencies", response_model=List[schemas.ModuleDependency])
def read_project_dependencies(
    project_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_visible(project, context)
    project_module_ids = db.query(models.Module.id).filter(models.Module.project_id == project_id).all()
    module_ids = [module_id for (module_id,) in project_module_ids]
    if not module_ids:
        return []

    return db.query(models.FileDependency).filter(
        models.FileDependency.preceding_module_id.in_(module_ids),
        models.FileDependency.dependent_module_id.in_(module_ids),
    ).all()


def _create_dependency_records(
    project_id: int,
    dependency_items: List[schemas.ModuleDependencyCreate],
    db: Session,
) -> List[models.FileDependency]:
    if not dependency_items:
        raise HTTPException(status_code=400, detail="At least one dependency is required.")

    project_modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()
    project_module_map = {module.id: module for module in project_modules}
    existing_pairs = {
        (item.preceding_module_id, item.dependent_module_id)
        for item in db.query(models.FileDependency).filter(
            models.FileDependency.preceding_module_id.in_(project_module_map.keys()),
            models.FileDependency.dependent_module_id.in_(project_module_map.keys()),
        ).all()
    }
    pending_pairs = set()
    created_dependencies = []

    for dependency_in in dependency_items:
        pair = (dependency_in.preceding_module_id, dependency_in.dependent_module_id)
        if dependency_in.preceding_module_id == dependency_in.dependent_module_id:
            raise HTTPException(status_code=400, detail="A module cannot depend on itself.")
        if (
            dependency_in.preceding_module_id not in project_module_map
            or dependency_in.dependent_module_id not in project_module_map
        ):
            raise HTTPException(status_code=404, detail="Dependency modules must belong to the current project.")
        if pair in existing_pairs or pair in pending_pairs:
            raise HTTPException(status_code=400, detail="Duplicate dependency detected.")
        if would_create_cycle(
            dependency_in.preceding_module_id,
            dependency_in.dependent_module_id,
            db,
            extra_edges=pending_pairs,
        ):
            raise HTTPException(status_code=400, detail="Dependencies would create a cycle.")

        pending_pairs.add(pair)
        created_dependencies.append(
            models.FileDependency(
                preceding_module_id=dependency_in.preceding_module_id,
                dependent_module_id=dependency_in.dependent_module_id,
            )
        )

    db.add_all(created_dependencies)
    db.commit()
    for dependency in created_dependencies:
        db.refresh(dependency)
    return created_dependencies


@router.post("/projects/{project_id}/dependencies", response_model=Union[schemas.ModuleDependency, List[schemas.ModuleDependency]])
def create_project_dependency(
    project_id: int,
    dependency_in: Union[schemas.ModuleDependencyCreate, schemas.ModuleDependencyBatchCreate],
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can change dependencies.")
    if isinstance(dependency_in, schemas.ModuleDependencyBatchCreate):
        return _create_dependency_records(project_id, dependency_in.dependencies, db)
    return _create_dependency_records(project_id, [dependency_in], db)[0]


@router.delete("/projects/{project_id}/dependencies/{dependency_id}", status_code=204)
def delete_project_dependency(
    project_id: int,
    dependency_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can change dependencies.")
    dependency = _get_dependency_or_404(project_id, dependency_id, db)
    db.delete(dependency)
    db.commit()
