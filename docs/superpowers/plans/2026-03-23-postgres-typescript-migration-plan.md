# PostgreSQL + TypeScript Migration Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 `fair-system` 从 `FastAPI + SQLite + Jinja2 + 原生 JS` 的内部协作原型，迁移为 `FastAPI + PostgreSQL + Vue 3 + TypeScript` 的平台化产品底座，同时保留已有认证、项目、评分、分配、上传验收等可用业务能力。

**Architecture:** 采用“后端渐进改造 + 前端渐进替换 + 数据库尽早升级”的迁移路线。后端保留 Python/FastAPI 与现有核心业务逻辑，先拆边界、再补服务层与 API；数据库先切换到 PostgreSQL + Alembic；前端新建独立 `frontend/` 工程，用 Vue 3 + TypeScript 承接新增页面和新交互，再逐步替换旧模板。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、Alembic、Vue 3、TypeScript、Vite、Pinia、Vue Router、Pytest

---

## 一、需求总结

### 产品目标

平台要同时服务三类场景：

- 有需求的人找到有对应技能的人做项目
- 有能力的人在平台接项目、参与协作
- 圈子 / 公司内部监控项目进展、验收与放款

### 核心价值

- 平台撮合项目与人才
- 平台支持协作、监控、验收、成果沉淀
- 平台保障款项不被拖欠
- 平台主要按劳分配，但兼容多种合作关系

### 已确认的关键功能

- 平台首页、项目广场、项目招募详情、个人主页
- 登录后仍回平台首页，再通过入口进入个人工作台
- 好友之间支持私聊
- 项目成员之间支持项目会话
- 项目提供共享云端文件夹
- 项目文件按模块分文件夹
- 成员只能修改自己模块文件夹内容
- 成员可以预览 / 下载其他模块的阶段成果
- 模块验收通过后，模块文件夹锁定为只读
- 存在正式交付成果区，与协作文件区分开
- 存在提醒、资金保障、放款、争议、组织监控能力
- 后续代码要模块化，便于 AI 分阶段持续开发

## 二、当前代码现状判断

### 值得保留的部分

- 认证与会话：`app/api/auth.py`、`app/services/auth_service.py`
- 项目与成员权限：`app/api/projects.py`、`app/api/project_access.py`
- 评分与公平分配：`app/api/scoring.py`、`app/api/assignments.py`、`app/services/fair_assignment.py`
- 项目邀请与社交基础：`app/api/project_invites.py`、`app/api/social.py`
- 文件验收与依赖关系：`app/api/files.py`、`app/api/project_dependencies.py`
- 自动化测试基线：`tests/` 下现有认证、社交、邀请、分配、上传相关测试

### 需要重点改造的部分

- 页面入口路由混在一个文件：`app/api/frontend.py`
- ORM 模型过于集中：`app/models.py`
- 运行时 schema 修补过重：`app/services/schema_bootstrap.py`
- 大模板耦合严重：
  - `app/templates/index.html`
  - `app/templates/project_detail.html`
  - `app/templates/social.html`
  - `app/templates/base.html`

### 更适合新建替换的部分

- 平台首页 / 项目广场 / 个人主页
- 聊天系统
- 项目共享文件夹
- 资金保障 / 放款 / 争议
- 组织空间 / 运营后台
- 全新的前端工程

## 三、迁移总策略

### 总体结论

- **不建议整个项目写完再换**
- **也不建议现在直接全量重写**
- **推荐：现在就开始切换目标栈，但采用渐进迁移**

### 原因

- 如果等全写完再换：
  - 旧模板和 SQLite 约束会越来越深
  - 到后面切换成本会更高
- 如果现在全重写：
  - 会丢掉当前可用业务逻辑
  - 会失去已有测试保护
  - 风险过高

### 推荐路线

- 后端：保留 FastAPI，渐进式拆模块
- 数据库：尽早切到 PostgreSQL
- 迁移工具：尽早引入 Alembic
- 前端：立即新建 Vue 3 + TypeScript 工程，但与旧页面并行一段时间

## 四、目标技术架构

### 后端

- `FastAPI + SQLAlchemy`
- 继续保留 Python 业务逻辑
- 新增服务层与 repository 边界

### 数据库

- 目标数据库：`PostgreSQL`
- 迁移管理：`Alembic`
- 过渡期支持本地 SQLite 演示，但新能力按 PostgreSQL 设计

### 前端

- `Vue 3 + TypeScript + Vite`
- 状态管理：`Pinia`
- 路由：`Vue Router`
- UI 初期可不引大型组件库，先保证边界清晰

### 前后端边界

- 旧 Jinja 页面继续服务过渡期
- 新功能与新页面优先走 Vue
- 新前端优先消费新的 API / 服务层

## 五、目标代码结构

### 后端目录目标

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
├─ persistence/
│  ├─ models/
│  ├─ repositories/
│  └─ migrations/
└─ main.py
```

### 前端目录目标

```text
frontend/
├─ src/
│  ├─ apps/
│  │  ├─ public/
│  │  ├─ workspace/
│  │  ├─ guarantee/
│  │  └─ org/
│  ├─ components/
│  ├─ stores/
│  ├─ router/
│  ├─ api/
│  ├─ types/
│  └─ views/
├─ package.json
├─ tsconfig.json
└─ vite.config.ts
```

## 六、分阶段迁移计划

### Phase 0：冻结目标边界

**目标：** 先统一目标栈和模块边界，不再继续向旧模板堆功能。

**输出：**

- 确认目标栈为 `FastAPI + PostgreSQL + Vue 3 + TypeScript`
- 以本次平台化画布作为产品结构基线
- 以模块化计划文档作为 AI 执行基线

**动作：**

- [ ] 禁止继续在 `app/templates/project_detail.html` 大幅加新功能
- [ ] 禁止继续直接往 `app/models.py` 里无规划地堆新表
- [ ] 所有新增功能必须先落到新的服务 / API / 前端模块计划里

### Phase 1：先拆后端边界，不改数据库

**目标：** 让旧系统能被“平稳接管”。

**优先修改文件：**

- `app/main.py`
- `app/api/frontend.py`
- `app/models.py`
- `app/templates/base.html`

**动作：**

- [ ] 把页面路由拆成 `public_pages / workspace_pages / profile_pages / guarantee_pages / org_pages`
- [ ] 把服务逻辑从 API 中搬到 `services/`
- [ ] 把 `app/models.py` 拆成持久层子文件，但保留兼容导出
- [ ] 为拆分动作补回归测试

**完成标准：**

- 原有业务仍然可跑
- 测试仍然通过
- 新功能可以不再依赖一个巨型路由文件或模板

### Phase 2：尽早引入 PostgreSQL + Alembic

**目标：** 在新功能大面积落地前，把数据库底座换对。

**优先修改文件：**

- `app/database.py`
- `app/environment.py`
- `.env.example`
- `requirements.txt`
- `README.md`

**新增文件：**

- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/`

**动作：**

- [ ] 抽象 `DATABASE_URL`
- [ ] 本地允许 SQLite，目标环境走 PostgreSQL
- [ ] 用 Alembic 管理新增表，不再只靠运行时 bootstrap 修补
- [ ] 为 PostgreSQL 连接和迁移写 smoke tests

**为什么放这么早：**

- 共享文件夹、聊天、放款、争议都更依赖 PostgreSQL
- 如果等这些功能都写完再迁库，风险更大

### Phase 3：搭建新的 Vue 3 + TypeScript 前端骨架

**目标：** 不再继续依赖 Jinja 巨型页面承接平台化新功能。

**新增目录：**

- `frontend/`

**动作：**

- [ ] 初始化 `Vite + Vue 3 + TypeScript`
- [ ] 配置 `Vue Router`
- [ ] 配置 `Pinia`
- [ ] 建立统一 API Client
- [ ] 建立统一类型目录 `src/types`
- [ ] 先接入登录态查询与基础导航

**输出页面（先做壳子）：**

- [ ] 平台首页
- [ ] 个人工作台
- [ ] 项目广场
- [ ] 项目工作台

### Phase 4：优先迁移公开域页面

**目标：** 先把平台感做出来，同时避免影响旧工作区主链。

**先迁这些页面：**

- [ ] 平台首页
- [ ] 项目广场
- [ ] 项目招募详情页
- [ ] 个人主页

**后端新增：**

- [ ] `market.py`
- [ ] `profile.py`
- [ ] `market_service.py`
- [ ] `profile_service.py`

**数据库新增：**

- [ ] 技能库
- [ ] 用户技能映射
- [ ] 主页公开设置
- [ ] 项目公开招募信息
- [ ] 项目申请记录

**原因：**

- 这些功能适合平台化展示
- 对旧协作链影响最小

### Phase 5：迁移工作区核心页面

**目标：** 让新前端开始承接项目协作主流程。

**先迁这些页面：**

- [ ] 个人工作台
- [ ] 我的项目
- [ ] 项目工作台
- [ ] 评分页
- [ ] 待办 / 提醒入口

**保留旧能力：**

- 评分
- 分配
- 项目成员权限
- 模块依赖
- 上传验收

**需要做的事：**

- [ ] 将旧页面的大量内嵌 JS 收束到 API + Vue 组件
- [ ] 把“项目工作台”拆成模块看板、成员区、监控区
- [ ] 为现有行为补接口类型定义

### Phase 6：实现聊天与项目共享文件夹

**目标：** 正式实现平台协作层，而不是继续用临时上传逻辑凑合。

**新增域：**

- [ ] `chat`
- [ ] `project_drive`

**数据库新增：**

- [ ] 会话
- [ ] 消息
- [ ] 消息附件
- [ ] 项目文件夹
- [ ] 项目文件
- [ ] 文件版本
- [ ] 模块锁定状态

**规则要求：**

- [ ] 好友私聊
- [ ] 项目会话
- [ ] 模块文件夹按负责人写入
- [ ] 他人目录只读预览 / 下载
- [ ] 验收通过后自动锁定模块目录

**注意：**

- `共享文件` 和 `正式交付成果` 必须是两套逻辑
- 不要把聊天附件、协作文档、验收交付混成一个接口

### Phase 7：实现资金保障、放款与争议

**目标：** 建立平台最关键的信任机制。

**新增域：**

- [ ] `guarantee`
- [ ] `disputes`
- [ ] `escrow_service`
- [ ] `payout_service`

**数据库新增：**

- [ ] 托管流水
- [ ] 放款请求
- [ ] 放款条目
- [ ] 账单流水
- [ ] 争议单

**页面：**

- [ ] 资金保障中心
- [ ] 放款详情页
- [ ] 账单记录页
- [ ] 争议申诉页

**迁移原则：**

- 现有 `settle` 逻辑只保留作内部结算雏形
- 正式平台放款必须走新的服务和表

### Phase 8：实现组织空间与运营台

**目标：** 支持圈子 / 公司内部使用，以及平台自身治理。

**新增域：**

- [ ] `orgs`
- [ ] `ops`

**功能：**

- [ ] 公司 / 圈子空间
- [ ] 组织项目总览
- [ ] 风险工单池
- [ ] 运营审核后台

### Phase 9：逐步淘汰旧模板

**目标：** 从“并行双系统”收敛到“新前端主系统”。

**顺序：**

- [ ] 先淘汰公开域旧模板
- [ ] 再淘汰社交/个人页旧模板
- [ ] 再淘汰工作台与项目详情旧模板
- [ ] 最后保留极少数兼容路由或彻底清理

## 七、AI 执行建议

后续让 AI 干活时，建议永远按下面方式下任务：

- 一次只做一个 Phase 或一个 Task
- 优先做“拆边界”和“迁移准备”，不要直接做最终态全功能
- 每次任务都明确：
  - 要改哪些文件
  - 要补哪些测试
  - 要保留哪些旧行为
- 对 AI 的一句典型指令应该像这样：

> 先执行 Phase 1，只做后端路由和服务边界拆分，不做新功能，不改数据库结构，确保现有测试继续通过。

## 八、最终建议

### 是否采用 PostgreSQL + TypeScript

- **建议采用**

### 是否整个项目写完再换

- **不建议**

### 是否现在直接重写

- **也不建议**

### 最佳方案

- **现在就切换目标栈**
- **但用渐进迁移的方式推进**

一句话总结：

> 后端保留、数据库尽早升级、前端新建并逐步替换，这是你当前项目最稳、最适合持续交给 AI 实现的路线。
