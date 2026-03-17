"""
【新手必看指北：文件上传 API】
在 FastAPI 中，处理文件上传非常简单，我们用到的是 `UploadFile` 类。
前端网页并不是把文件变成普通文字，而是通过一种叫 `multipart/form-data` 的特殊包裹邮寄过来。
FastAPI 会在内存或者临时文件夹里自动帮你接住这个包裹。

所以在这个文件里，我们会：
1. 把接收到的文件“另存为”到我们刚才建的 `uploads/` 文件夹下。
2. 在数据库这边的 `ModuleFile` 表里记录一笔："某某时间，小明上传了一份文件，存放在 xxx 路径下"。
"""

import os
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.api.dependencies import get_db

router = APIRouter(prefix="/files", tags=["文件成果管理"])

# 确保我们的上传目录一定存在，不存在就建一个 (防止以后别人下载代码运行报错)
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload/")
def upload_module_file(
    module_id: int = Form(...), 
    uploaded_by: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    **业务逻辑说明**：
    大家上传自己做好的文件（比如写好的代码、画好的设计图）。
    注意参数里的 `Form(...)` 和 `File(...)`：
    当一个接口需要收文件的同时还要收文字信息（比如这文件是谁传的、对应哪个模块），
    在这时我们就不能用 Pydantic 表格(JSON)接收了，必须全都改成 Form 表单接收模式。
    """
    
    # 1. 验证下这人和模块在不在
    module = db.query(models.Module).filter(models.Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="模块找不到。")
        
    member = db.query(models.Member).filter(models.Member.id == uploaded_by).first()
    if not member:
        raise HTTPException(status_code=404, detail="上传的用户不存在。")

    if module.assigned_to != uploaded_by:
        raise HTTPException(status_code=403, detail="只有该模块的负责人才能上传文件。")

    if module.status != "开发中":
        raise HTTPException(status_code=400, detail="只有开发中的模块才能上传文件。")

    # 2. 【进阶安全校验】验证文件扩展名是不是这个模块允许的？
    if module.allowed_file_types:
        # 比如 allowed 是 ".pdf,.zip"
        allowed_exts = [ext.strip().lower() for ext in module.allowed_file_types.split(",")]
        # 获取用户传的文件的后缀 (比如 "mydesign.PDF" -> ".pdf")
        _, file_ext = os.path.splitext(file.filename)
        
        if file_ext.lower() not in allowed_exts:
            raise HTTPException(
                status_code=400, 
                detail=f"抱歉，该模块只接受以下扩展名的文件：{module.allowed_file_types}"
            )

    # 3. 开始把文件保存到硬盘！
    # 为了防止重名覆盖，我们在物理硬盘存放时可以建一些子文件夹，比如 uploads/module_5/老王的文件.pdf
    save_dir = os.path.join(UPLOAD_DIR, f"module_{module_id}")
    os.makedirs(save_dir, exist_ok=True)
    
    file_path = os.path.join(save_dir, file.filename)
    
    # 把收到的文件包，一点一点写进真正的硬盘路径里（shutil 帮你做这个搬运工）
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 4. 硬盘里有了，这时候我们要去数据库里记录一下！
    db_file = models.ModuleFile(
        module_id=module_id,
        uploaded_by=uploaded_by,
        file_path=file_path,
        file_name=file.filename,
        status="Pending" # 刚上传，所以是“待审核”状态
    )
    db.add(db_file)
    
    # 【联通逻辑】: 负责人在开发中阶段提交成果后，模块进入待审核
    module.status = "待审核"
    
    db.commit()
    db.refresh(db_file)

    return {
        "message": "文件上传成功！等待项目经理审核。", 
        "file_record_id": db_file.id,
        "saved_path": file_path
    }


def _review_file(file_id: int, action: str, current_member_id: int, db: Session):
    """
    **业务逻辑说明**：
    项目经理的御用专属接口。当组员上传文件后，经理审查过关，调用它改状态。
    action 参数只能填: 'approve' (通过) 或 'reject' (打回重做)。
    """

    db_file = db.query(models.ModuleFile).filter(models.ModuleFile.id == file_id).first()
    if not db_file:
        raise HTTPException(status_code=404, detail="找不到这个上传记录。")

    module = db.query(models.Module).filter(models.Module.id == db_file.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="找不到对应的模块。")

    project = db.query(models.Project).filter(models.Project.id == module.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="找不到对应的项目。")

    if project.created_by != current_member_id:
        raise HTTPException(status_code=403, detail="只有项目经理才能审核交付。")

    normalized_action = action.lower()

    if normalized_action == "approve":
        db_file.status = "Approved"
        module.status = "已完成" # 连带模块状态变为完美收官！
        db.commit()
        return {"message": "审核通过！该模块正式完工。"}

    if normalized_action == "reject":
        db_file.status = "Rejected"
        module.status = "开发中" # 被打回去了，还得接着干
        db.commit()
        return {"message": "已打回，需组员重新修改。"}

    raise HTTPException(status_code=400, detail="未知的审核动作！只接受 approve 或 reject")


@router.put("/{file_id}/review")
def review_file(file_id: int, action: str, current_member_id: int, db: Session = Depends(get_db)):
    return _review_file(file_id=file_id, action=action, current_member_id=current_member_id, db=db)


@router.post("/review/{file_id}")
def review_file_legacy(file_id: int, action: str, current_member_id: int, db: Session = Depends(get_db)):
    return _review_file(file_id=file_id, action=action, current_member_id=current_member_id, db=db)

@router.post("/review_by_module/{module_id}")
def review_file_by_module(module_id: int, action: str, current_member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    前端专用的快捷审核接口。项目经理在画板上点击“审核”时，不需要知道繁琐的 file_id，
    只需要传过来模块 ID，系统会自动找到该模块最新上传的那份文件进行审核。
    """
    # 按照上传时间倒序查找该模块下最新的一个待审核文件
    db_file = db.query(models.ModuleFile).filter(
        models.ModuleFile.module_id == module_id,
        models.ModuleFile.status == "Pending"
    ).order_by(models.ModuleFile.uploaded_at.desc()).first()
    
    if not db_file:
        raise HTTPException(status_code=404, detail="该模块当前没有待审核的文件。")
        
    # 复用前面的审核逻辑
    return _review_file(file_id=int(db_file.id), action=action, current_member_id=current_member_id, db=db)
