# Platform Modularization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留现有认证、项目协作、评分、分配、上传验收基础能力的前提下，把 `fair-system` 从“内部协作软件”改造成“公开平台 + 协作工作区 + 保障中心 + 组织空间”的模块化平台。

**Architecture:** 采用“先拆边界、后加能力”的渐进式改造路线。先拆页面路由、模板、服务边界并保持现有行为稳定，再逐步新增公开广场、个人主页、聊天、项目共享文件夹、资金保障、放款与组织空间。数据库层先兼容现有 `app/models.py`，等服务边界稳定后再拆 ORM 模块并迁移到 PostgreSQL + Alembic。

**Tech Stack:** FastAPI、SQLAlchemy、Jinja2、原生 JavaScript、Pytest、SQLite（过渡期）、PostgreSQL（目标）、Alembic（目标）

---

## 当前代码判断

### 直接保留

这些文件已经有稳定业务价值，优先保留并做兼容式扩展：

- `app/database.py`
- `app/environment.py`
- `app/api/auth.py`
- `app/services/auth_service.py`
- `app/api/projects.py`
- `app/api/assignments.py`
- `app/services/fair_assignment.py`
- `app/api/scoring.py`
- `app/api/project_invites.py`
- `app/api/social.py`
- `app/api/project_dependencies.py`
- `app/utils/dependency_checker.py`
- `app/utils/load_tracker.py`
- `tests/test_auth_api.py`
- `tests/test_auth_page_flows.py`
- `tests/test_project_invites_api.py`
- `tests/test_social_api.py`
- `tests/test_project_detail_batch_assignment_progress_gate.py`
- `tests/test_files_upload_dependency.py`

### 重点改造

这些文件有用，但已经过大或职责混杂，适合逐步拆分：

- `app/main.py`
- `app/api/frontend.py`
- `app/models.py`
- `app/api/files.py`
- `app/api/notifications.py`
- `app/templates/base.html`
- `app/templates/index.html`
- `app/templates/project_detail.html`
- `app/templates/social.html`
- `app/templates/todo.html`
- `seed_demo_data.py`
- `app/services/schema_bootstrap.py`

### 建议重写或替换

这些能力不适合直接延用到平台化阶段，建议重写：

- `app/templates/members.html` → 替换为正式个人主页 / 管理后台
- `app/templates/overview.html` → 替换为组织空间 / 运营总览
- `app/api/frontend.py` 中时间线“实际工时”演示逻辑 → 改成真实事件 / 文件 / 验收驱动
- 巨型模板中的内嵌页面脚本 → 分拆为域内脚本或静态模块
- 当前“临时计算型提醒” → 改成持久化通知中心

## 重写 vs 渐进改造结论

- **不建议现在直接全量重写**
- 原因：
  - 当前项目已有一条可运行的主链路
  - 本地已有 `168` 个自动化测试通过，说明已有不少稳定行为
  - 认证、项目权限、评分、分配、上传验收、邀请、社交这些底层能力已经成型
  - 如果全重写，你会同时失去“现有可用业务逻辑”和“已有测试保护”

### 推荐策略

- **推荐：在现有基础上渐进改造**
- 但不是“继续往大文件里堆代码”，而是：
  - 先拆边界
  - 再新增模块
  - 最后替换旧实现

### 唯一适合直接重写的部分

- 页面模板结构
- 通知中心
- 聊天与共享文件夹
- 资金保障 / 放款 / 争议
- 组织空间与运营后台

这些部分可以作为“新模块”直接新建，而不是硬塞进旧模板。

## 目标代码结构

第一阶段先按业务域建边界，后续再把持久层拆开：

```text
app/
├─ api/
│  ├─ auth.py
│  ├─ public_pages.py
│  ├─ workspace_pages.py
│  ├─ profile_pages.py
│  ├─ guarantee_pages.py
│  ├─ org_pages.py
│  ├─ market.py
│  ├─ profile.py
│  ├─ chat.py
│  ├─ project_drive.py
│  ├─ guarantee.py
│  ├─ disputes.py
│  ├─ orgs.py
│  └─ ops.py
├─ services/
│  ├─ auth_service.py
│  ├─ workspace_service.py
│  ├─ market_service.py
│  ├─ profile_service.py
│  ├─ chat_service.py
│  ├─ project_drive_service.py
│  ├─ delivery_service.py
│  ├─ notification_center_service.py
│  ├─ escrow_service.py
│  ├─ payout_service.py
│  ├─ dispute_service.py
│  └─ org_space_service.py
├─ persistence/
│  ├─ models/
│  ├─ repositories/
│  └─ migrations/
├─ templates/
│  ├─ layouts/
│  ├─ public/
│  ├─ workspace/
│  ├─ profile/
│  ├─ guarantee/
│  └─ ops/
└─ static/
   ├─ js/
   └─ css/
```

## Task 1: 拆页面路由边界，不改现有行为

**Files:**
- Modify: `app/main.py`
- Modify: `app/api/frontend.py`
- Create: `app/api/public_pages.py`
- Create: `app/api/workspace_pages.py`
- Create: `app/api/profile_pages.py`
- Create: `app/api/guarantee_pages.py`
- Create: `app/api/org_pages.py`
- Test: `tests/test_dashboard_project_creation_form.py`
- Test: `tests/test_project_detail_route_auth.py`
- Test: `tests/test_social_page_flows.py`
- Test: `tests/test_todo_grouped_pending.py`

- [ ] **Step 1: 为现有页面路由写路由分层烟雾测试**

新增测试：

- `tests/test_platform_route_split_smoke.py`

测试目标：

- `/` 属于公开平台入口
- `/todo` 属于工作区
- `/social` 与后续个人主页/聊天可并入 profile / social 域
- `/project/{id}` 属于工作区

- [ ] **Step 2: 运行基线路由测试**

Run:

```bash
python -m pytest tests/test_dashboard_project_creation_form.py tests/test_project_detail_route_auth.py tests/test_social_page_flows.py tests/test_todo_grouped_pending.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 3: 创建新页面路由文件并先代理旧逻辑**

在以下文件中先“导入旧 handler 或复制轻量包装”，不要立刻改业务：

- `app/api/public_pages.py`
- `app/api/workspace_pages.py`
- `app/api/profile_pages.py`
- `app/api/guarantee_pages.py`
- `app/api/org_pages.py`

- [ ] **Step 4: 在 `app/main.py` 中改为挂载新路由文件**

保留 `app/api/frontend.py` 作为兼容层，直到新路由稳定后再削减。

- [ ] **Step 5: 回归运行页面路由测试**

Run:

```bash
python -m pytest tests/test_platform_route_split_smoke.py tests/test_dashboard_project_creation_form.py tests/test_project_detail_route_auth.py tests/test_social_page_flows.py tests/test_todo_grouped_pending.py -q
```

Expected:

```text
PASS
```

## Task 2: 拆模板和前端脚本边界

**Files:**
- Modify: `app/templates/base.html`
- Modify: `app/templates/index.html`
- Modify: `app/templates/project_detail.html`
- Modify: `app/templates/social.html`
- Modify: `app/templates/todo.html`
- Create: `app/templates/layouts/base.html`
- Create: `app/templates/public/platform_home.html`
- Create: `app/templates/workspace/dashboard.html`
- Create: `app/templates/workspace/project_workspace.html`
- Create: `app/templates/workspace/project_chat.html`
- Create: `app/templates/workspace/project_drive.html`
- Create: `app/templates/workspace/formal_delivery.html`
- Create: `app/templates/guarantee/fund_center.html`
- Create: `app/templates/profile/profile_home.html`
- Create: `app/static/js/public/`
- Create: `app/static/js/workspace/`
- Create: `app/static/js/guarantee/`
- Test: `tests/test_project_invite_ui.py`
- Test: `tests/test_social_invite_page_flows.py`
- Test: `tests/test_project_detail_shift_multiselect.py`

- [ ] **Step 1: 把公共布局抽到 `app/templates/layouts/base.html`**

保留当前侧边栏和会话信息，但不要再让业务页面直接承载全部布局逻辑。

- [ ] **Step 2: 把现有模板重命名并拆出域模板**

推荐映射：

- `index.html` → `public/platform_home.html` + `workspace/dashboard.html`
- `project_detail.html` → `workspace/project_workspace.html`
- `social.html` → `profile/profile_home.html` 的过渡版
- `todo.html` → `workspace/todo.html`

- [ ] **Step 3: 把大模板里的内嵌 JS 分拆到静态脚本**

至少先把：

- 项目工作区脚本
- 社交 / 主页脚本
- 待办 / 提醒脚本

移到 `app/static/js/...`

- [ ] **Step 4: 回归运行模板行为测试**

Run:

```bash
python -m pytest tests/test_project_invite_ui.py tests/test_social_invite_page_flows.py tests/test_project_detail_shift_multiselect.py -q
```

Expected:

```text
PASS
```

## Task 3: 引入服务层，减少路由直接查库

**Files:**
- Create: `app/services/workspace_service.py`
- Create: `app/services/market_service.py`
- Create: `app/services/profile_service.py`
- Create: `app/services/notification_center_service.py`
- Create: `app/services/guarantee_service.py`
- Modify: `app/api/projects.py`
- Modify: `app/api/social.py`
- Modify: `app/api/project_invites.py`
- Modify: `app/api/files.py`
- Modify: `app/api/notifications.py`
- Modify: `app/api/workspace_pages.py`
- Test: `tests/test_social_api.py`
- Test: `tests/test_project_invites_api.py`
- Test: `tests/test_files_upload_dependency.py`

- [ ] **Step 1: 为现有核心查询写服务层适配函数**

先不要改数据库表，目标只是把“查什么”“怎么算”搬出 route handler。

- [ ] **Step 2: 让页面路由和 API 路由调用服务层**

避免模板页里继续直接拼装复杂查询。

- [ ] **Step 3: 把当前 `notifications.py` 改造成通知中心服务的薄路由**

先兼容现有待评分提醒，后续再加私信、邀请、验收、放款提醒。

- [ ] **Step 4: 回归服务相关测试**

Run:

```bash
python -m pytest tests/test_social_api.py tests/test_project_invites_api.py tests/test_files_upload_dependency.py -q
```

Expected:

```text
PASS
```

## Task 4: 拆持久层模型文件，但保留 `app/models.py` 兼容门面

**Files:**
- Create: `app/persistence/models/__init__.py`
- Create: `app/persistence/models/accounts.py`
- Create: `app/persistence/models/projects.py`
- Create: `app/persistence/models/social.py`
- Create: `app/persistence/models/collaboration.py`
- Create: `app/persistence/models/files.py`
- Create: `app/persistence/models/finance.py`
- Modify: `app/models.py`
- Modify: `app/services/schema_bootstrap.py`
- Test: `tests/test_schema_bootstrap_auth.py`
- Test: `tests/test_member_profile_api.py`

- [ ] **Step 1: 复制现有 ORM 类到新持久层文件**

按域拆：

- 账号认证
- 项目与成员关系
- 社交与邀请
- 文件与协作
- 财务与结算

- [ ] **Step 2: 让 `app/models.py` 只做 re-export**

这样可以兼容旧导入路径，避免一次性改全仓库。

- [ ] **Step 3: 校验 bootstrap 和现有导入不被破坏**

Run:

```bash
python -m pytest tests/test_schema_bootstrap_auth.py tests/test_member_profile_api.py -q
```

Expected:

```text
PASS
```

## Task 5: 实现公开广场与正式个人主页

**Files:**
- Create: `app/api/market.py`
- Create: `app/api/profile.py`
- Create: `app/services/market_service.py`
- Create: `app/services/profile_service.py`
- Modify: `app/persistence/models/projects.py`
- Modify: `app/persistence/models/accounts.py`
- Create: `app/persistence/models/public_market.py`
- Modify: `app/services/schema_bootstrap.py`
- Modify: `seed_demo_data.py`
- Create: `app/templates/public/project_market.html`
- Create: `app/templates/public/project_recruit_detail.html`
- Create: `app/templates/profile/profile_home.html`
- Test: `tests/test_public_market_pages.py`
- Test: `tests/test_profile_pages.py`

- [ ] **Step 1: 新增平台化公开数据表**

至少新增：

- 技能库
- 用户技能映射
- 主页公开设置
- 项目公开招募信息
- 项目申请记录

- [ ] **Step 2: 让“项目广场”和“人物主页”走新 API**

不要继续复用旧 `members.html` 语义。

- [ ] **Step 3: 在 `seed_demo_data.py` 中补平台公开数据**

保证 demo 环境能展示广场、主页、申请链路。

- [ ] **Step 4: 运行公开域测试**

Run:

```bash
python -m pytest tests/test_public_market_pages.py tests/test_profile_pages.py -q
```

Expected:

```text
PASS
```

## Task 6: 实现聊天与项目共享文件夹，明确区分正式交付

**Files:**
- Create: `app/api/chat.py`
- Create: `app/api/project_drive.py`
- Create: `app/services/chat_service.py`
- Create: `app/services/project_drive_service.py`
- Create: `app/persistence/models/chat.py`
- Modify: `app/persistence/models/files.py`
- Create: `app/templates/workspace/project_chat.html`
- Create: `app/templates/workspace/project_drive.html`
- Modify: `app/api/files.py`
- Test: `tests/test_chat_api.py`
- Test: `tests/test_project_drive_permissions.py`
- Test: `tests/test_project_drive_locking.py`

- [ ] **Step 1: 增加聊天与共享文件夹表**

建议至少包含：

- 私聊 / 项目会话
- 消息
- 聊天附件
- 项目文件夹
- 项目文件
- 文件版本
- 模块锁定状态

- [ ] **Step 2: 把 `app/api/files.py` 收缩为“正式交付成果”接口**

不要再让它兼任共享资料文件逻辑。

- [ ] **Step 3: 在 `project_drive_service.py` 中实现权限规则**

规则必须支持：

- 负责人可写自己模块文件夹
- 其他成员只读可预览/下载
- 模块验收通过后自动锁定目录

- [ ] **Step 4: 运行共享文件和聊天测试**

Run:

```bash
python -m pytest tests/test_chat_api.py tests/test_project_drive_permissions.py tests/test_project_drive_locking.py -q
```

Expected:

```text
PASS
```

## Task 7: 实现保障中心、放款与争议

**Files:**
- Create: `app/api/guarantee.py`
- Create: `app/api/disputes.py`
- Create: `app/services/escrow_service.py`
- Create: `app/services/payout_service.py`
- Create: `app/services/dispute_service.py`
- Create: `app/persistence/models/finance.py`
- Create: `app/templates/guarantee/fund_center.html`
- Create: `app/templates/guarantee/payout_detail.html`
- Modify: `app/api/projects.py`
- Modify: `app/templates/todo.html`
- Test: `tests/test_guarantee_center.py`
- Test: `tests/test_payout_flow.py`
- Test: `tests/test_dispute_flow.py`

- [ ] **Step 1: 新增资金保障相关模型**

至少新增：

- 托管流水
- 放款请求
- 放款条目
- 账单流水
- 争议单

- [ ] **Step 2: 把当前简单 `settle` 逻辑迁到 `payout_service.py`**

现有 `project/{id}/settle` 只适合作为内部结算雏形，需要升级成平台放款流程。

- [ ] **Step 3: 在提醒页和资金中心打通待处理事项**

包括：

- 待放款
- 待验收
- 争议冻结

- [ ] **Step 4: 运行保障中心测试**

Run:

```bash
python -m pytest tests/test_guarantee_center.py tests/test_payout_flow.py tests/test_dispute_flow.py -q
```

Expected:

```text
PASS
```

## Task 8: 实现组织空间与运营台

**Files:**
- Create: `app/api/orgs.py`
- Create: `app/api/ops.py`
- Create: `app/services/org_space_service.py`
- Create: `app/services/ops_service.py`
- Create: `app/persistence/models/orgs.py`
- Create: `app/templates/ops/org_space.html`
- Create: `app/templates/ops/ops_console.html`
- Test: `tests/test_org_space.py`
- Test: `tests/test_ops_console.py`

- [ ] **Step 1: 增加组织与组织成员关系表**

支持公司 / 圈子内部查看项目与成员。

- [ ] **Step 2: 增加组织项目概览与风险看板 API**

组织空间不应该直接复用普通用户工作台。

- [ ] **Step 3: 增加运营台风控 / 纠纷处理入口**

这部分可以先做轻量后台，不要求漂亮。

- [ ] **Step 4: 运行组织域测试**

Run:

```bash
python -m pytest tests/test_org_space.py tests/test_ops_console.py -q
```

Expected:

```text
PASS
```

## Task 9: 从 SQLite 迁移到 PostgreSQL，并引入 Alembic

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `app/environment.py`
- Modify: `app/database.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/`
- Modify: `README.md`
- Test: `tests/test_postgres_config_smoke.py`

- [ ] **Step 1: 先把连接配置抽象成数据库 URL**

不要再默认绑定单一本地 SQLite 文件。

- [ ] **Step 2: 引入 Alembic 管理迁移**

`schema_bootstrap` 继续保留一段时间，但新增表以后不应继续靠运行时修补完成所有升级。

- [ ] **Step 3: 提供本地 SQLite 与生产 PostgreSQL 双模式**

开发环境先兼容当前演示方式，部署时切到 PostgreSQL。

- [ ] **Step 4: 运行数据库配置烟雾测试**

Run:

```bash
python -m pytest tests/test_postgres_config_smoke.py -q
```

Expected:

```text
PASS
```

## 交付顺序建议

不要试图一次性实现整个计划。建议按下面顺序一阶段一阶段做：

1. `Task 1-3`：只做拆边界，不改业务
2. `Task 4`：拆持久层文件结构
3. `Task 5`：公开广场 + 个人主页
4. `Task 6`：聊天 + 项目共享文件夹
5. `Task 7`：保障中心 + 放款 + 争议
6. `Task 8`：组织空间 + 运营台
7. `Task 9`：PostgreSQL + Alembic

## 给后续 AI 的执行要求

- 只能按任务顺序推进，不要跨阶段同时乱改
- 每次只做一个 Task，最多带一个紧邻子任务
- 每完成一个 Task 都必须先跑对应测试
- 若改动 `app/models.py` 或 `app/services/schema_bootstrap.py`，必须优先补测试
- 若要替换模板，先保留旧模板或兼容路由，避免直接断链
- 若新增数据库表，必须同步更新：
  - `seed_demo_data.py`
  - `README.md`
  - 对应测试
