# Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans or an equivalent disciplined execution workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不切换数据库、不引入新前端框架、不新增平台业务功能的前提下，完成 `fair-system` 的第一阶段基础改造：拆页面路由入口、抽离页面服务逻辑、拆分持久层模型边界，并保留现有行为与测试稳定性。

**Architecture:** 本阶段采用“兼容优先”的渐进改造方案。先用回归测试锁定现有前端页面行为，再把 `app/api/frontend.py` 中的页面路由按业务域拆到独立 router 文件；随后把会话解析、页面上下文拼装、工作区数据构建迁到 `services/`；最后将 `app/models.py` 迁移到新的 `app/persistence/models/` 目录中，并通过兼容导出保持旧导入路径继续可用。

**Tech Stack:** FastAPI、SQLAlchemy、Jinja2、Pytest、SQLite（过渡期）

---

## 一、范围边界

### 本阶段必须完成

- 页面路由按域拆分
- 页面 helper / 组装逻辑从 API 中抽出
- `app/models.py` 迁移为模块化持久层结构
- 为拆分动作补充和维护回归测试

### 本阶段明确不做

- 不切换到 `PostgreSQL`
- 不引入 `Alembic`
- 不创建 `Vue 3 + TypeScript` 前端工程
- 不重做页面视觉样式
- 不新增托管款、放款、争议、云盘等平台新业务

## 二、Phase 1 目标文件结构

```text
app/
├─ api/
│  ├─ frontend.py                  # 兼容层，逐步退化为聚合或弃用文件
│  ├─ public_pages.py              # /login /register
│  ├─ workspace_pages.py           # / /project/{id} /todo /timeline/{id} /scoring/{id}
│  ├─ profile_pages.py             # /social /members
│  ├─ guarantee_pages.py           # 预留 router，占位但先不承载实际页面
│  └─ org_pages.py                 # /overview
├─ services/
│  ├─ page_context_service.py      # session、next、登录跳转、安全路径
│  ├─ workspace_page_service.py    # 工作台 / 项目 / 待办 / 时间线 / 评分页数据拼装
│  └─ profile_page_service.py      # 社交页、成员页等轻量页面上下文
├─ persistence/
│  ├─ __init__.py
│  └─ models/
│     ├─ __init__.py
│     ├─ identity_models.py
│     ├─ project_models.py
│     ├─ delivery_models.py
│     └─ scoring_models.py
└─ models.py                       # 兼容导出层
```

## 三、现状与路由归属

### 当前 `frontend.py` 路由

- `/`
- `/project/{project_id}`
- `/members`
- `/social`
- `/overview`
- `/todo`
- `/login`
- `/register`
- `/timeline/{project_id}`
- `/scoring/{project_id}`

### 拆分后的归属

- `public_pages.py`
  - `/login`
  - `/register`
- `workspace_pages.py`
  - `/`
  - `/project/{project_id}`
  - `/todo`
  - `/timeline/{project_id}`
  - `/scoring/{project_id}`
- `profile_pages.py`
  - `/social`
  - `/members`
- `org_pages.py`
  - `/overview`
- `guarantee_pages.py`
  - 暂无实际页面，只保留空 router 和说明注释

## 四、测试基线

Phase 1 期间，以下页面行为视为“不可破坏契约”：

- 登录重定向与 `next` 安全处理：
  - `tests/test_frontend_next_redirects.py`
- 首页 / 工作台：
  - `tests/test_dashboard_project_creation_form.py`
- 项目页权限：
  - `tests/test_project_detail_route_auth.py`
- 社交页：
  - `tests/test_social_page_flows.py`
- 总览页：
  - `tests/test_overview_route_auth.py`
- 待办页：
  - `tests/test_todo_grouped_pending.py`
- 时间线页：
  - `tests/test_timeline_route_auth.py`
- 评分页：
  - `tests/test_scoring_page_route.py`

模型拆分后，还需要重点回归：

- `tests/test_auth_service.py`
- `tests/test_auth_api.py`
- `tests/test_project_invites_api.py`
- `tests/test_files_upload_dependency.py`
- `tests/test_custom_scoring_dimensions.py`
- `tests/test_schema_bootstrap_auth.py`
- `tests/test_social_api.py`

## 五、任务拆解

### Task 1: 锁定当前页面路由契约

**Files:**
- Create: `tests/test_platform_route_split_smoke.py`
- Test: `tests/test_frontend_next_redirects.py`
- Test: `tests/test_dashboard_project_creation_form.py`
- Test: `tests/test_project_detail_route_auth.py`
- Test: `tests/test_social_page_flows.py`
- Test: `tests/test_overview_route_auth.py`
- Test: `tests/test_todo_grouped_pending.py`
- Test: `tests/test_timeline_route_auth.py`
- Test: `tests/test_scoring_page_route.py`

- [ ] **Step 1: 写页面归属烟雾测试**

新增 `tests/test_platform_route_split_smoke.py`，至少覆盖以下断言：

```python
import importlib


def test_phase1_page_modules_exist():
    for module_name in [
        "app.api.public_pages",
        "app.api.workspace_pages",
        "app.api.profile_pages",
        "app.api.guarantee_pages",
        "app.api.org_pages",
    ]:
        module = importlib.import_module(module_name)
        assert getattr(module, "router", None) is not None
```

- [ ] **Step 2: 运行当前页面基线测试**

Run:

```bash
python -m pytest tests/test_frontend_next_redirects.py tests/test_dashboard_project_creation_form.py tests/test_project_detail_route_auth.py tests/test_social_page_flows.py tests/test_overview_route_auth.py tests/test_todo_grouped_pending.py tests/test_timeline_route_auth.py tests/test_scoring_page_route.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 3: 运行新烟雾测试，确认当前确实失败**

Run:

```bash
python -m pytest tests/test_platform_route_split_smoke.py -q
```

Expected:

```text
FAIL
```

- [ ] **Step 4: 提交基线测试**

```bash
git add tests/test_platform_route_split_smoke.py
git commit -m "test: lock phase1 page route baseline"
```

### Task 2: 抽取页面公共上下文服务

**Files:**
- Create: `app/services/page_context_service.py`
- Create: `tests/test_page_context_service.py`
- Modify: `app/api/frontend.py`
- Test: `tests/test_frontend_next_redirects.py`

- [ ] **Step 1: 为页面公共 helper 写单元测试**

新增 `tests/test_page_context_service.py`，至少覆盖：

```python
from app.services.page_context_service import sanitize_next_path


def test_sanitize_next_path_rejects_external_urls():
    assert sanitize_next_path("https://evil.example") == "/"
    assert sanitize_next_path("//evil.example") == "/"
```

- [ ] **Step 2: 运行新单元测试确认失败**

Run:

```bash
python -m pytest tests/test_page_context_service.py -q
```

Expected:

```text
FAIL
```

- [ ] **Step 3: 实现页面公共上下文服务**

将以下逻辑从 `app/api/frontend.py` 迁到 `app/services/page_context_service.py`：

- `sanitize_next_path`
- `build_login_redirect_url`
- `resolve_member_context`

建议导出形态：

```python
def sanitize_next_path(next_path: str | None) -> str: ...
def build_login_redirect_url(request: Request) -> str: ...
def resolve_member_context(request: Request, db: Session) -> CurrentMemberContext | None: ...
```

- [ ] **Step 4: 改造 `frontend.py` 使用新服务**

要求：

- `frontend.py` 不再保留这些 helper 的实现细节
- 暂时允许保留旧函数名作为轻量转发，避免一次性改太多调用点

- [ ] **Step 5: 回归运行上下文与重定向测试**

Run:

```bash
python -m pytest tests/test_page_context_service.py tests/test_frontend_next_redirects.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 6: 提交页面上下文服务**

```bash
git add app/services/page_context_service.py app/api/frontend.py tests/test_page_context_service.py
git commit -m "refactor: extract page context helpers"
```

### Task 3: 拆分页面 router，但保持页面行为不变

**Files:**
- Create: `app/api/public_pages.py`
- Create: `app/api/workspace_pages.py`
- Create: `app/api/profile_pages.py`
- Create: `app/api/guarantee_pages.py`
- Create: `app/api/org_pages.py`
- Modify: `app/api/frontend.py`
- Modify: `app/main.py`
- Test: `tests/test_platform_route_split_smoke.py`
- Test: `tests/test_dashboard_project_creation_form.py`
- Test: `tests/test_project_detail_route_auth.py`
- Test: `tests/test_social_page_flows.py`
- Test: `tests/test_overview_route_auth.py`
- Test: `tests/test_todo_grouped_pending.py`
- Test: `tests/test_timeline_route_auth.py`
- Test: `tests/test_scoring_page_route.py`

- [ ] **Step 1: 为 router 拆分准备兼容结构**

每个新 router 文件先创建最小骨架：

```python
from fastapi import APIRouter

router = APIRouter(tags=["页面"])
```

- [ ] **Step 2: 按归属迁移页面处理函数**

迁移规则：

- `public_pages.py`：`show_login_page`、`show_register_page`
- `workspace_pages.py`：`show_index`、`show_project_detail`、`show_todo_page`、`show_timeline`、`show_scoring_page`
- `profile_pages.py`：`show_social_page`、`show_members_page`
- `org_pages.py`：`show_overview_page`
- `guarantee_pages.py`：仅保留占位 router 与说明注释

- [ ] **Step 3: 将 `app/api/frontend.py` 降级为兼容聚合层**

建议结构：

```python
from fastapi import APIRouter
from app.api import public_pages, workspace_pages, profile_pages, guarantee_pages, org_pages

router = APIRouter(include_in_schema=False)
router.include_router(public_pages.router)
router.include_router(workspace_pages.router)
router.include_router(profile_pages.router)
router.include_router(guarantee_pages.router)
router.include_router(org_pages.router)
```

- [ ] **Step 4: 修改 `app/main.py` 直接注册新页面 router**

要求：

- `main.py` 直接 `include_router(public_pages.router)` 等新模块
- 暂停在 `main.py` 中注册 `frontend.router`
- 其他业务 API router 保持原顺序不动

- [ ] **Step 5: 跑页面路由回归**

Run:

```bash
python -m pytest tests/test_platform_route_split_smoke.py tests/test_dashboard_project_creation_form.py tests/test_project_detail_route_auth.py tests/test_social_page_flows.py tests/test_overview_route_auth.py tests/test_todo_grouped_pending.py tests/test_timeline_route_auth.py tests/test_scoring_page_route.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 6: 提交 router 拆分**

```bash
git add app/api/public_pages.py app/api/workspace_pages.py app/api/profile_pages.py app/api/guarantee_pages.py app/api/org_pages.py app/api/frontend.py app/main.py tests/test_platform_route_split_smoke.py
git commit -m "refactor: split page routers by domain"
```

### Task 4: 抽离工作区页面数据组装逻辑

**Files:**
- Create: `app/services/workspace_page_service.py`
- Create: `app/services/profile_page_service.py`
- Create: `tests/test_workspace_page_service.py`
- Modify: `app/api/workspace_pages.py`
- Modify: `app/api/profile_pages.py`
- Test: `tests/test_dashboard_project_creation_form.py`
- Test: `tests/test_todo_grouped_pending.py`
- Test: `tests/test_timeline_route_auth.py`
- Test: `tests/test_scoring_page_route.py`
- Test: `tests/test_social_page_flows.py`

- [ ] **Step 1: 为工作区页面服务写最小单元测试**

新增 `tests/test_workspace_page_service.py`，至少覆盖一个纯数据组装函数，例如：

```python
from app.services.workspace_page_service import group_pending_projects


def test_group_pending_projects_merges_same_project_items():
    grouped = group_pending_projects([
        {"project_id": 1, "project_name": "A", "assessment_end": "2026-01-01T10:00:00"},
        {"project_id": 1, "project_name": "A", "assessment_end": "2026-01-01T08:00:00"},
    ])
    assert grouped[0]["module_count"] == 2
```

- [ ] **Step 2: 运行服务单元测试确认失败**

Run:

```bash
python -m pytest tests/test_workspace_page_service.py -q
```

Expected:

```text
FAIL
```

- [ ] **Step 3: 实现工作区页面服务**

从 `workspace_pages.py` 中抽出以下逻辑：

- 首页项目卡片汇总
- 项目详情依赖关系组装
- 待办页 `grouped_pending` 和 `wallet_summary`
- 时间线页 `timeline_data` 和总进度
- 评分页维度 / 评审结果 payload

建议导出函数：

- `build_dashboard_context(...)`
- `build_project_detail_context(...)`
- `group_pending_projects(...)`
- `build_todo_context(...)`
- `build_timeline_context(...)`
- `build_scoring_page_context(...)`

- [ ] **Step 4: 实现轻量 profile 页面服务**

`profile_page_service.py` 先只承载简单上下文，避免 `profile_pages.py` 以后继续变胖。

- [ ] **Step 5: 回归运行页面与服务测试**

Run:

```bash
python -m pytest tests/test_workspace_page_service.py tests/test_dashboard_project_creation_form.py tests/test_todo_grouped_pending.py tests/test_timeline_route_auth.py tests/test_scoring_page_route.py tests/test_social_page_flows.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 6: 提交页面服务抽离**

```bash
git add app/services/workspace_page_service.py app/services/profile_page_service.py app/api/workspace_pages.py app/api/profile_pages.py tests/test_workspace_page_service.py
git commit -m "refactor: extract workspace page services"
```

### Task 5: 拆分持久层模型目录并保留兼容导出

**Files:**
- Create: `app/persistence/__init__.py`
- Create: `app/persistence/models/__init__.py`
- Create: `app/persistence/models/identity_models.py`
- Create: `app/persistence/models/project_models.py`
- Create: `app/persistence/models/delivery_models.py`
- Create: `app/persistence/models/scoring_models.py`
- Modify: `app/models.py`
- Test: `tests/test_auth_service.py`
- Test: `tests/test_auth_api.py`
- Test: `tests/test_project_invites_api.py`
- Test: `tests/test_files_upload_dependency.py`
- Test: `tests/test_custom_scoring_dimensions.py`
- Test: `tests/test_schema_bootstrap_auth.py`
- Test: `tests/test_social_api.py`

- [ ] **Step 1: 建立新的持久层包结构**

按下列归属拆模型：

- `identity_models.py`
  - `Member`
  - `Account`
  - `AccountFollow`
  - `EmailVerificationToken`
  - `AuthSession`
- `project_models.py`
  - `project_members_association`
  - `Project`
  - `ProjectInvite`
  - `Module`
- `delivery_models.py`
  - `FileDependency`
  - `ModuleFile`
  - `ModuleSwapRequest`
- `scoring_models.py`
  - `ModuleAssessment`
  - `ScoringDimension`
  - `DimensionScore`

- [ ] **Step 2: 先写兼容导出层**

将 `app/models.py` 改成只做聚合导出，例如：

```python
from app.persistence.models.identity_models import *
from app.persistence.models.project_models import *
from app.persistence.models.delivery_models import *
from app.persistence.models.scoring_models import *
```

- [ ] **Step 3: 运行模型相关测试确认拆分没有破坏导入**

Run:

```bash
python -m pytest tests/test_auth_service.py tests/test_auth_api.py tests/test_project_invites_api.py tests/test_files_upload_dependency.py tests/test_custom_scoring_dimensions.py tests/test_schema_bootstrap_auth.py tests/test_social_api.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 4: 补充 `__all__` 或显式导出，避免星号导入失控**

要求：

- `app/persistence/models/__init__.py` 显式列出可导出的模型名
- `app/models.py` 的兼容层只暴露当前项目实际依赖的公共名称

- [ ] **Step 5: 提交模型边界拆分**

```bash
git add app/persistence/__init__.py app/persistence/models/__init__.py app/persistence/models/identity_models.py app/persistence/models/project_models.py app/persistence/models/delivery_models.py app/persistence/models/scoring_models.py app/models.py
git commit -m "refactor: split persistence models with compatibility exports"
```

### Task 6: 完成 Phase 1 回归与交接说明

**Files:**
- Modify: `docs/superpowers/plans/2026-03-23-phase1-foundation-plan.md`
- Test: `tests/test_frontend_next_redirects.py`
- Test: `tests/test_dashboard_project_creation_form.py`
- Test: `tests/test_project_detail_route_auth.py`
- Test: `tests/test_social_page_flows.py`
- Test: `tests/test_overview_route_auth.py`
- Test: `tests/test_todo_grouped_pending.py`
- Test: `tests/test_timeline_route_auth.py`
- Test: `tests/test_scoring_page_route.py`
- Test: `tests/test_auth_service.py`
- Test: `tests/test_auth_api.py`
- Test: `tests/test_project_invites_api.py`
- Test: `tests/test_files_upload_dependency.py`
- Test: `tests/test_custom_scoring_dimensions.py`
- Test: `tests/test_schema_bootstrap_auth.py`
- Test: `tests/test_social_api.py`

- [ ] **Step 1: 运行 Phase 1 汇总回归集**

Run:

```bash
python -m pytest tests/test_platform_route_split_smoke.py tests/test_page_context_service.py tests/test_workspace_page_service.py tests/test_frontend_next_redirects.py tests/test_dashboard_project_creation_form.py tests/test_project_detail_route_auth.py tests/test_social_page_flows.py tests/test_overview_route_auth.py tests/test_todo_grouped_pending.py tests/test_timeline_route_auth.py tests/test_scoring_page_route.py tests/test_auth_service.py tests/test_auth_api.py tests/test_project_invites_api.py tests/test_files_upload_dependency.py tests/test_custom_scoring_dimensions.py tests/test_schema_bootstrap_auth.py tests/test_social_api.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 2: 记录 Phase 1 结果**

在交接说明中至少写清楚：

- 页面路由拆分到哪些文件
- `frontend.py` 还剩什么兼容职责
- `app/models.py` 现在只是兼容入口
- 哪些新目录是为 `Phase 2` 和 `Phase 3` 预留的

- [ ] **Step 3: 提交 Phase 1 完成态**

```bash
git add app docs/superpowers/plans/2026-03-23-phase1-foundation-plan.md tests
git commit -m "refactor: complete phase1 foundation split"
```

## 六、Phase 1 完成定义

当且仅当以下条件全部满足时，Phase 1 才算完成：

- `app/main.py` 不再依赖单一 `frontend.router`
- 页面路由已经按业务域拆开
- 页面 handler 不再承载主要数据组装逻辑
- `app/models.py` 已降级为兼容导出层
- 页面与模型回归测试通过
- 项目仍然使用当前 SQLite 基线正常运行

## 七、Phase 2 入口条件

只有在以下条件满足后，才进入 `PostgreSQL + Alembic`：

- Phase 1 页面与模型边界稳定
- 当前基线测试保持通过
- 新目录结构已经可承接数据库迁移
- 不再继续向旧巨型文件叠加新平台功能
