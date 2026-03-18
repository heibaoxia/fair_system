"""
【新手必看指北：数据验证大本营】
在 FastAPI 里，schemas (Pydantic 模型) 主要用来做两件事：
1. 请求验证：当前端传来 JSON 数据时，确保它符合我们预期的格式。比如邮箱必填，预估时间必须是数字。不符合的话直接给前端报 422 错误。
2. 响应过滤：我们要把数据库对象 (SQLAlchemy 返回的类) 发给前端时，过滤掉敏感信息(比如密码)，并按照下面的格式打包成 JSON 给他们。
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


# ==========================================
# 0. 通用配置类
# 因为 SQLAlchemy查回来的数据是一个类似"对象"(有id, name等属性) 不是一个纯字典(key-value)，
# FastAPI 默认看不懂对象，只懂字典。如果你加了 `from_attributes = True`，
# Pydantic 就会变聪明，能读取： object.name 并转成字典给你发到前端。
# 这里我创建一个基础ORM响应类，复用这个配置。
# ==========================================
class ConfiguredModel(BaseModel):
    class Config:
        from_attributes = True


# ==========================================
# 1. 成员 (Member)
# ==========================================

# Base是基础字段，读取和创建时都有的
class MemberBase(BaseModel):
    name: str # 姓名
    tel: str # 手机号
    is_active: bool = True
    skills: Optional[str] = "" # 用户的技能标签（前端可以传空字符串）
    available_hours: Optional[float] = 0.0 # 空闲可用时长

class MemberCreate(MemberBase):
    pass  # 创建会员时不需要传额外信息，直接用基础字段即可

class MemberUpdate(BaseModel):
    """用于 PUT /members/{id} 的局部更新请求体，所有字段均为 Optional。
    前端只需传想修改的字段，未传的字段保持数据库原值不变。"""
    name: Optional[str] = None
    tel: Optional[str] = None
    is_active: Optional[bool] = None
    skills: Optional[str] = None
    available_hours: Optional[float] = None

class Member(MemberBase, ConfiguredModel):
    id: int # 虽然创建时不需要id(数据库自动生成)，但是返给前端时它必须有id。
    created_at: datetime


# ==========================================
# 2. 模块评估 (ModuleAssessment)
# 在任务分配前，大家进行的盲打分。
# ==========================================
class ScoringDimensionCreate(BaseModel):
    name: str
    weight: float = Field(..., ge=0, le=1)


class ScoringDimension(ScoringDimensionCreate, ConfiguredModel):
    id: int
    sort_order: int
    max_score: float = 10.0


class DimensionScoreCreate(BaseModel):
    dimension_id: int
    score: float = Field(..., ge=0, le=10)


class DimensionScore(DimensionScoreCreate, ConfiguredModel):
    id: int


class AssessmentBase(BaseModel):
    difficulty_score: Optional[float] = Field(default=None, ge=0, le=10)
    estimated_hours: Optional[float] = Field(default=None, ge=0)
    boredom_score: Optional[float] = Field(default=None, ge=0, le=10)
    intensity_score: Optional[float] = Field(default=None, ge=0, le=10)

class AssessmentCreate(AssessmentBase):
    member_id: int # 谁提交的评估
    module_id: int # 在给别人打分时，必须要告诉系统这是对哪个模块打的分
    dimension_scores: Optional[List[DimensionScoreCreate]] = []

class ModuleAssessment(AssessmentBase, ConfiguredModel):
    id: int
    member_id: int
    module_id: int
    created_at: datetime
    dimension_scores: List[DimensionScore] = []


# ==========================================
# 3. 模块文件成果 (ModuleFile)
# ==========================================
class ModuleFileBase(BaseModel):
    file_name: str

class ModuleFileCreate(ModuleFileBase):
    pass # 真实场景下，FastAPI 上传文件用的通常是 `UploadFile` 特殊类，而不是普通的 JSON 请求。
         # 所以这个Create的Pydantic模型通常用在“更新记录”，而非直接上传那一步。

class ModuleFile(ModuleFileBase, ConfiguredModel):
    id: int
    module_id: int
    uploaded_by: int
    file_path: str
    uploaded_at: datetime
    status: str # "Pending"(待审) "Approved"(通过) "Rejected"(拒绝)


# ==========================================
# 4. 模块 (Module)
# ==========================================
class ModuleBase(BaseModel):
    name: str
    description: Optional[str] = ""
    estimated_hours: float = 0.0
    allowed_file_types: Optional[str] = "" # 比如 ".zip,.pdf"

class ModuleCreate(ModuleBase):
    pass


class ModuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    estimated_hours: Optional[float] = None
    allowed_file_types: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[int] = None


class ModuleDependencyBase(BaseModel):
    preceding_module_id: int
    dependent_module_id: int


class ModuleDependencyCreate(ModuleDependencyBase):
    pass


class ModuleDependencyBatchCreate(BaseModel):
    dependencies: List[ModuleDependencyCreate]


class ModuleDependency(ModuleDependencyBase, ConfiguredModel):
    id: int

class Module(ModuleBase, ConfiguredModel):
    id: int
    project_id: int
    status: str
    assigned_to: Optional[int] = None # 可能还没有被分配出去

    # 返给前端的时候，顺带把这模块底下的评估和文件也发过去！
    assessments: List[ModuleAssessment] = []
    files: List[ModuleFile] = []


class ModuleDetail(Module):
    is_unlocked: bool = True
    incoming_dependencies: List[ModuleDependency] = []
    outgoing_dependencies: List[ModuleDependency] = []


# ==========================================
# 5. 项目 (Project)
# ==========================================
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectCreate(ProjectBase):
    # 当 PM 点击"创建项目"按钮时，他可以一次性创建一个项目 + 好多个模块，
    # 只要在传进来的 JSON 里面写入这个 new_modules 列表即可。
    new_modules: List[ModuleCreate] = []
    
    # 接收前端传来的模块依赖关系，比如：[{"preceding": 0, "dependent": 1}]
    # 这里的 0, 1 是 new_modules 列表里的索引号。
    dependencies: List[dict] = []
    scoring_dimensions: Optional[List[ScoringDimensionCreate]] = []

class AssessmentPeriodSet(BaseModel):
    start_mode: str
    start_at: Optional[datetime] = None
    duration_hours: float

class ProjectWeightsUpdate(BaseModel):
    """管理员设置四维评分权重，四个权重之和应等于 1.0"""
    weight_difficulty: float = 0.25
    weight_hours: float = 0.25
    weight_boredom: float = 0.25
    weight_intensity: float = 0.25

class Project(ProjectBase, ConfiguredModel):
    id: int
    created_by: int
    status: str
    total_revenue: float
    assessment_start: Optional[datetime] = None
    assessment_end: Optional[datetime] = None
    # 四维权重（所有成员可见）
    weight_difficulty: float = 0.25
    weight_hours: float = 0.25
    weight_boredom: float = 0.25
    weight_intensity: float = 0.25
    use_custom_dimensions: bool = False
    created_at: datetime
    
    # 获取这个项目所有的模块
    modules: List[Module] = []
    scoring_dimensions: List[ScoringDimension] = []
