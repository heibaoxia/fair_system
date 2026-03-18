"""
【新手必看指北：数据库大本营】
这里是我们系统的核心中的核心：数据表模型定义。
通过 SQLAlchemy，我们不需要去写枯燥的 SQL 语句（比如 CREATE TABLE xxx）。
我们只需要在这个文件里写 Python 类 (Class)，SQLAlchemy 就会在运行初始化脚本时，自动帮我们在数据库里把这些相关的表格建立起来。
"""

from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Float, Table
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

# ==========================================
# 0. 多对多关联表
# ==========================================
project_members_association = Table(
    "project_members",
    Base.metadata,
    Column("project_id", Integer, ForeignKey("projects.id")),
    Column("member_id", Integer, ForeignKey("members.id"))
)

# ==========================================
# 1. 成员表 (Member)
# 也就是系统的用户，你的团队成员们。
# ==========================================
class Member(Base):
    __tablename__ = "members" # 这个就是真正在 SQLite 数据库里的表名字

    id = Column(Integer, primary_key=True, index=True) # 每个成员的唯一编号 (1, 2, 3...)
    name = Column(String, index=True) # 成员的名字
    tel = Column(String, unique=True, index=True) # 手机号，加了 unique=True 代表手机号不能重复注册
    is_active = Column(Boolean, default=True) # 账号是不是白名单/激活状态

    # [新增] 技能、可用时间和评价数据
    skills = Column(String, default="") # 成员的标签或技能描述，比如 "Python,前端设计,测试"
    available_hours = Column(Float, default=0.0) # 这个成员这周/这月一共有几小时空闲可用？
    total_earnings = Column(Float, default=0.0) # 累计收入
    created_at = Column(DateTime, default=datetime.now) # 自动记录是什么时候进系统的

    # ---------------- 魔法关联区 ----------------
    # relationship 就像在不同表之间牵线搭桥。它并不会实际产生数据库里的“列(Column)”！
    # 但在 Python 中，当你拿到了一个 Member 对象(叫 m) 时，
    # 你可以直接写 m.projects (获取他创建的所有项目), m.assessments (获取他做的所有打分)。
    projects = relationship("Project", back_populates="owner")
    assessments = relationship("ModuleAssessment", back_populates="member")


# ==========================================
# 2. 项目表 (Project)
# 整个项目的概要信息
# ==========================================
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String) 
    description = Column(String)
    
    # [新增] 项目状态: "筹备中" -> "进行中" -> "已完成"
    status = Column(String, default="筹备中")
    
    # ====== 以下是“大改版”新增的字段 ======
    # [新增] 项目的总花销/总收入(分配用)，可由PM随时录入
    total_revenue = Column(Float, default=0.0)
    assessment_start = Column(DateTime, nullable=True)
    assessment_end = Column(DateTime, nullable=True)

    # 这是一个外键 (ForeignKey)，意味着这一列存着另一个表的 ID。
    # 比如这里填了 1，说明是 members 表里 ID 为 1 的用户创建了这个项目。
    created_by = Column(Integer, ForeignKey("members.id"))
    created_at = Column(DateTime, default=datetime.now)

    # ---------------- 魔法关联区 ----------------
    owner = relationship("Member", back_populates="projects")
    modules = relationship("Module", back_populates="project")
    # 项目包含哪些参与成员
    members = relationship("Member", secondary=project_members_association, backref="joined_projects")
    scoring_dimensions = relationship("ScoringDimension", back_populates="project", cascade="all, delete-orphan", order_by="ScoringDimension.sort_order")


# ==========================================
# 3. 模块表 (Module)
# 项目被拆解成的一个个具体的任务模块
# ==========================================
class Module(Base):
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String) # 模块名字，比如 "登录界面设计"
    description = Column(String, default="") # 具体要干啥
    
    # [新增] 模块状态: 待分配, 开发中, 待审核, 已完成
    status = Column(String, default="待分配")

    # [新增] 分配给谁做了？存这个人的 Member ID。如果是未分配，它就是空(NULL)
    assigned_to = Column(Integer, ForeignKey("members.id"), nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    # 这个模块预估要多少时间？这个预估是为了兜底使用，最终还是依靠大家打分平均。
    estimated_hours = Column(Float, default=0.0) 
    
    # [新增] 规定这个模块最终需要上传什么样的文件扩展名，比如 ".zip,.pdf,.docx"
    allowed_file_types = Column(String, default="") 

    # 外键：这个模块属于哪个项目？
    project_id = Column(Integer, ForeignKey("projects.id"))

    # ---------------- 魔法关联区 ----------------
    project = relationship("Project", back_populates="modules")
    
    # 一个模块可能会有多個人给它打分评估
    assessments = relationship("ModuleAssessment", back_populates="module")

    # 本模块被分配给了谁 (可以方便地查到负责人名字了)
    assignee = relationship("Member", foreign_keys=[assigned_to])

    # 本任务上传了哪些成果文件
    files = relationship("ModuleFile", back_populates="module")

    # [重点]: 声明自己作为"前置模块"的从属关系表，也就是它解锁了哪些模块？
    # 我们这里使用下面定义的 FileDependency 表
    unlocked_dependencies = relationship("FileDependency", foreign_keys="[FileDependency.preceding_module_id]")
    # 声明自己作为"后置模块"的从属关系表，也就是它依赖哪些模块？
    required_dependencies = relationship("FileDependency", foreign_keys="[FileDependency.dependent_module_id]")


# ==========================================
# 4. [全新] 模块依赖表 (FileDependency)
# 解决硬骨头问题：“前端设计(后面)”必须等“原型图绘制(前面)”审核文件通过后才能进行！
# ==========================================
class FileDependency(Base):
    __tablename__ = "file_dependencies"

    id = Column(Integer, primary_key=True, index=True)
    
    # 前置模块ID (也就是必须先做完的那个)
    preceding_module_id = Column(Integer, ForeignKey("modules.id"))
    
    # 后置模块ID (也就是等着前置做完才能开始的那个)
    dependent_module_id = Column(Integer, ForeignKey("modules.id"))

    # 简单的说，记录了一句话：“dependent必须等preceding”。


# ==========================================
# 5. [全新] 模块文件成果表 (ModuleFile)
# 任何一个模块要想变成"已完成"，必须由负责人上传文件给项目经理（PM）审核。
# ==========================================
class ModuleFile(Base):
    __tablename__ = "module_files"

    id = Column(Integer, primary_key=True, index=True)
    
    # 外键：这是哪个模块的文件？
    module_id = Column(Integer, ForeignKey("modules.id"))
    
    # 外键：谁传的？
    uploaded_by = Column(Integer, ForeignKey("members.id"))
    
    # 文件的物理存放路径，比如 "./uploads/project_1/module_5/design.pdf"
    file_path = Column(String) 
    file_name = Column(String) # 原文件名，如 "设计稿终版.pdf"
    uploaded_at = Column(DateTime, default=datetime.now)

    # 审核状态 (待审核 Pending, 已通过 Approved, 拒绝 Rejected)
    status = Column(String, default="Pending")

    # ---------------- 魔法关联区 ----------------
    module = relationship("Module", back_populates="files")
    uploader = relationship("Member", foreign_keys=[uploaded_by])


# ==========================================
# 6. [全新] 模块工时与难度评估表 (ModuleAssessment)
# 在分配任务之前，大家都要进来对每个待分配模块盲打分。
# == 这里采用的是 1 到 5 分的整数制（像给电影打星一样直观） ==
# ==========================================
class ModuleAssessment(Base):
    __tablename__ = "module_assessments"

    id = Column(Integer, primary_key=True, index=True)
    
    # 谁打的分？
    member_id = Column(Integer, ForeignKey("members.id"))
    # 打的哪个模块？
    module_id = Column(Integer, ForeignKey("modules.id"))

    created_at = Column(DateTime, default=datetime.now)

    # ---------------- 魔法关联区 ----------------
    member = relationship("Member", back_populates="assessments")
    module = relationship("Module", back_populates="assessments")
    # 自定义维度评分明细
    dimension_scores = relationship("DimensionScore", back_populates="assessment", cascade="all, delete-orphan")


class ModuleSwapRequest(Base):
    __tablename__ = "module_swap_requests"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    initiated_by = Column(Integer, ForeignKey("members.id"))

    swap_type = Column(String, default="reassign")

    module_id = Column(Integer, ForeignKey("modules.id"))
    swap_module_id = Column(Integer, ForeignKey("modules.id"), nullable=True)

    from_member_id = Column(Integer, ForeignKey("members.id"))
    to_member_id = Column(Integer, ForeignKey("members.id"))

    status = Column(String, default="待确认")
    reason = Column(String, default="")

    created_at = Column(DateTime, default=datetime.now)
    resolved_at = Column(DateTime, nullable=True)


# ==========================================
# 8. [全新] 打分维度定义表 (ScoringDimension)
# PM在创建项目时可自定义打分维度及权重
# ==========================================
class ScoringDimension(Base):
    __tablename__ = "scoring_dimensions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String)              # 维度名称，如 "难度"、"创意度"
    weight = Column(Float, default=0.25)  # 该维度权重
    max_score = Column(Float, default=10.0) # 满分（固定10）
    sort_order = Column(Integer, default=0) # 显示排序

    project = relationship("Project", back_populates="scoring_dimensions")


# ==========================================
# 9. [全新] 维度评分明细表 (DimensionScore)
# 每次评估中，每个维度的具体分数
# ==========================================
class DimensionScore(Base):
    __tablename__ = "dimension_scores"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("module_assessments.id"))
    dimension_id = Column(Integer, ForeignKey("scoring_dimensions.id"))
    score = Column(Float, default=0.0)  # 0~10 浮点

    assessment = relationship("ModuleAssessment", back_populates="dimension_scores")
    dimension = relationship("ScoringDimension")
