"""
【新手必看指北：成员 API 路由】
这里我们将把针对“Member”的操作集中在一起。
FastAPI 通过 APIRouter 提供了像“插座”一样的机制，
我们在这里定义好关于成员的增加、查询接口，
最后只要在 main.py 里把这个路由器“插”到主应用上就可以了！
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.api.dependencies import get_db

# 创建一个专门处理 Member 业务的路由器
# 加上 prefix="/members" 意味着这里面所有的链接都会自动带上 /members 前缀
# tags=["成员管理"] 仅仅是为了让自动生成的 Swagger API 文档更好看、分类更清晰
router = APIRouter(prefix="/members", tags=["成员管理"])


def _normalize_tel(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


# ==========================================
# 1. 注册/创建新成员 (POST 请求)
# ==========================================
# response_model=schemas.Member 的意思是：
# "不论我们查询到了什么烂七八糟的数据，最后发给前端时，必须按照 schemas.py 里 Member 定义的格式进行清洗和打包！"
@router.post("/", response_model=schemas.Member)
def create_member(member: schemas.MemberCreate, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    前端发送一个 JSON 数据包含名字、手机号等。
    我们需要先查查：这个手机号是不是已经注册过了？如果注册过了就报错 400。
    没注册过，就往数据库里插入一条新记录。
    """
    
    payload = member.model_dump()
    payload["tel"] = _normalize_tel(payload.get("tel"))

    if payload["tel"] is not None:
        db_member = db.query(models.Member).filter(models.Member.tel == payload["tel"]).first()
        if db_member:
            # 如果找到了，说明重复注册！用 HTTPException 直接抛出错误给前端
            raise HTTPException(status_code=400, detail="该手机号码已被注册！")
        
    # 如果没找到，说明可以注册。
    # ** member.model_dump()：这是一个魔法，它可以把对象变成字典 {"name":"小明", "tel":"xxx"}
    # **前面的两个星星的意思是解包字典，相当于 name="小明", tel="xxx"
    new_member = models.Member(**payload)
    
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    
    return new_member


# ==========================================
# 2. 获取所有成员列表 (GET 请求)
# ==========================================
# 因为是列表，所以 response_model 用 List 包裹一下
@router.get("/", response_model=List[schemas.Member])
def read_members(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    用来在前端展示成员列表。
    这里演示了分页功能：如果你传 skip=10, limit=20，就会跳过前10条数据，然后取接下来的20条。
    默认就是从第0个开始，取最多100个(对于小团队够用了)。
    """
    members = db.query(models.Member).offset(skip).limit(limit).all()
    return members


# ==========================================
# 3. 获取单个成员详情 (GET 请求)
# ==========================================
# 这里的 {member_id} 会捕捉 URL 里的数字，比如访问 /members/5 ，那么 member_id 就是 5
@router.get("/{member_id}", response_model=schemas.Member)
def read_member(member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    比如小明点击了自己的个人主页，前端要拉取他的详情信息。
    """
    usr = db.query(models.Member).filter(models.Member.id == member_id).first()
    
    if usr is None:
        raise HTTPException(status_code=404, detail="未找到该成员！去查查是不是ID输错了？")
    
    return usr


# ==========================================
# 4. 更新成员信息 (PUT 请求)
# ==========================================
@router.put("/{member_id}", response_model=schemas.Member)
def update_member(member_id: int, member_in: schemas.MemberUpdate, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    只传你想改的字段就够了，没传的字段保持原样不变（局部更新/Partial Update）。
    比如只想改手机号，就只传 {"tel": "13800138000"} 即可。

    技术关键点：model_dump(exclude_unset=True) 只会序列化请求里"真正传了" 的字段，
    这样就不会误把 None 写入数据库覆盖原有数据。
    """
    db_member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if db_member is None:
        raise HTTPException(status_code=404, detail="未找到该成员，无法更新！")

    # exclude_unset=True：仅提取请求体里真正传入的字段，跳过那些仅为 None 默认值的字段
    update_data = member_in.model_dump(exclude_unset=True)

    # 如果改了手机号，要确保新手机号不和别人冲突
    if "tel" in update_data:
        update_data["tel"] = _normalize_tel(update_data["tel"])
        if update_data["tel"] is None:
            existing = None
        else:
            existing = db.query(models.Member).filter(
                models.Member.tel == update_data["tel"],
                models.Member.id != member_id
            ).first()
        if existing:
            raise HTTPException(status_code=400, detail="该手机号已被其他成员使用！")

    for field, value in update_data.items():
        setattr(db_member, field, value)

    db.commit()
    db.refresh(db_member)
    return db_member


# ==========================================
# 5. 删除成员 (DELETE 请求)
# ==========================================
@router.delete("/{member_id}", status_code=204)
def delete_member(member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    删除指定 ID 的成员记录。
    成功后返回 HTTP 204 No Content（惯例：删除成功不返回任何内容体）。
    """
    db_member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if db_member is None:
        raise HTTPException(status_code=404, detail="未找到该成员，无法删除！")

    db.delete(db_member)
    db.commit()
    return Response(status_code=204)
