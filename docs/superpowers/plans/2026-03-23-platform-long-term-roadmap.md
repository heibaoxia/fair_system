# Platform Long-Term Roadmap Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans or an equivalent disciplined execution workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 `fair-system` 从内部协作原型，渐进改造成可平台化运营的项目协作与保障系统，并保留已有认证、项目、分配、评分、邀请、上传验收等可复用业务能力。

**Architecture:** 采用“保留核心业务规则、先拆边界、尽早升级数据库、渐进替换前端”的路线。后端继续以 `FastAPI` 为主，先完成 Phase 1 的路由/服务/模型边界拆分；随后尽早切换到 `PostgreSQL + Alembic`；再引入独立 `Vue 3 + TypeScript` 前端，逐步承接平台公开区、协作工作区、保障中心和组织空间。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、Alembic、Vue 3、TypeScript、Vite、Pinia、Vue Router、Pytest、GitHub

---

## 一、总原则

- [ ] `main` 始终保持可回退、可对比、可部署的稳定基线
- [ ] 不继续向 `app/templates/project_detail.html` 这类巨型模板硬塞新平台功能
- [ ] 不继续无规划地向 `app/models.py` 叠加新表和跨域字段
- [ ] 新功能优先以“新模块 / 新 API / 新前端域”的方式落地
- [ ] 先保留已被测试保护的业务逻辑，再逐步替换旧页面壳层

## 二、现有代码处理原则

### 优先保留

- `app/api/auth.py`
- `app/services/auth_service.py`
- `app/api/projects.py`
- `app/api/assignments.py`
- `app/services/fair_assignment.py`
- `app/api/scoring.py`
- `app/api/project_invites.py`
- `app/api/social.py`
- `app/api/project_dependencies.py`
- 当前 `tests/` 中认证、社交、邀请、分配、上传相关测试

### 优先重构

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

### 适合逐步替换

- 公开平台首页 / 项目广场 / 招募详情页
- 个人主页 / 技能展示页
- 好友私聊与项目会话
- 项目共享文件夹与正式交付区
- 保障中心（托管、放款、争议）
- 组织空间 / 运营后台

## 三、阶段总路线图

### Phase 0：冻结边界与执行规则

**目标：** 统一产品结构、技术栈和开发纪律，避免旧代码继续失控扩张。

**核心输出：**

- 平台化结构图基线
- 模块化方向说明
- 长期路线图与阶段计划文档
- 分支与提交规则

**完成标准：**

- 团队不再往旧模板和旧巨型模型里硬塞新功能
- 后续 AI 执行有清晰参考文档

### Phase 1：拆后端边界，稳定接管旧系统

**目标：** 不改核心业务规则，先把旧系统拆成可维护边界。

**核心输出：**

- 页面路由拆分为 `public_pages / workspace_pages / profile_pages / guarantee_pages / org_pages`
- API 与服务层职责更清楚
- 持久层开始从 `app/models.py` 过渡到模块化结构
- 补足回归测试保护

**完成标准：**

- 原有业务可跑
- 基线测试继续通过
- 后续新前端、新数据库可以平稳接入

### Phase 2：升级数据库底座为 PostgreSQL + Alembic

**目标：** 在复杂协作和保障功能落地前，把数据库地基换对。

**核心输出：**

- `DATABASE_URL` 环境配置
- `PostgreSQL` 连接能力
- `Alembic` 迁移体系
- SQLite 仅保留本地演示兼容位

**完成标准：**

- 新增表结构不再依赖运行时修补
- 本地和目标环境的数据库差异可控

### Phase 3：搭建 Vue 3 + TypeScript 前端骨架

**目标：** 为平台化页面和复杂交互准备独立前端容器。

**核心输出：**

- `frontend/` 工程
- `Vue Router + Pinia + API Client + TypeScript types`
- 登录态、导航壳层、基础布局

**完成标准：**

- 新页面不再依赖旧 `Jinja` 巨型模板
- 前后端边界开始清晰稳定

### Phase 4：先做公开平台区

**目标：** 先把“找项目 / 找人 / 建联系”的平台公开面做出来。

**核心输出：**

- 平台首页
- 项目广场
- 项目招募详情页
- 个人主页 / 技能页
- 平台入口与注册转化链路

**完成标准：**

- 未登录用户也能理解平台价值
- 登录后仍回平台首页，再从入口进入工作台

### Phase 5：做协作工作区

**目标：** 把项目执行与协作链条做完整。

**核心输出：**

- 个人工作台
- 我的项目 / 项目工作台
- 项目成员会话
- 好友私聊
- 项目共享云端文件夹
- 模块文件夹权限、预览下载、阶段成果、正式交付、验收锁定

**完成标准：**

- 一个项目从立项、分工、协作、上传、验收到交付能走通主链路

### Phase 6：做保障中心

**目标：** 解决平台可信协作和不拖欠的核心问题。

**核心输出：**

- 托管款 / 保障金基础模型
- 验收节点与放款条件
- 放款申请与执行记录
- 争议冻结 / 申诉 / 审核记录

**完成标准：**

- 资金状态可追踪
- 验收与放款链条有记录、有状态、有约束

### Phase 7：做组织空间与运营能力

**目标：** 让公司 / 圈子内部能用，让平台也能运营。

**核心输出：**

- 组织空间 / 公司项目监控
- 风险提醒 / 进展看板 / 验收状态 / 放款状态
- 运营后台的项目审核、身份审核、纠纷处理

**完成标准：**

- 平台既能服务公开撮合，也能服务组织内协作和监管

## 四、分支策略

## 结论

**不是 8 个阶段就一定要 8 个固定分支。**

阶段是产品与工程里程碑，分支只是代码隔离工具。对你现在这个项目，最稳妥的做法是：

- 保留 1 个稳定主干：`main`
- 保留 1 个历史备份：`codex/backup-20260323-current`
- 当前只维护 1 个主开发分支：`codex/platform-phase1-foundation`
- 后面按“实际任务”开短期工作分支，而不是一次性开 8 个长期分支

### 推荐规则

- 小任务直接在当前阶段开发分支完成
- 中等任务按功能开短分支，做完即合并
- 大阶段只在真正开始时再开新分支，不提前把 8 个全建出来

### 推荐命名

- 当前阶段主线：`codex/platform-phase1-foundation`
- Phase 1 子任务：
  - `codex/p1-route-split`
  - `codex/p1-service-extraction`
  - `codex/p1-model-boundary`
- Phase 2 子任务：
  - `codex/p2-postgres-bootstrap`
  - `codex/p2-alembic-migrations`
- Phase 3 子任务：
  - `codex/p3-vue-scaffold`

### 适合你的实际做法

你是单人主导、且还在梳理需求，当前不建议同时维护很多活跃分支。最适合的是：

- `main`：只放稳定版本
- `codex/platform-phase1-foundation`：当前阶段主工作分支
- 必要时再从它切一个更小的子分支

## 五、当前建议执行顺序

- [ ] 先完成 Phase 1 的页面路由拆分
- [ ] 再完成服务边界拆分
- [ ] 再完成模型边界拆分
- [ ] Phase 1 稳定后，再启动 PostgreSQL + Alembic
- [ ] 数据库方向确定后，再搭建 `Vue 3 + TypeScript`
- [ ] 之后按“公开平台区 → 协作工作区 → 保障中心 → 组织空间”推进

## 六、当前第一刀

**现在立刻要做的不是再规划，而是开始 Phase 1 的第一个可执行任务：**

- [ ] 拆页面入口路由
- [ ] 让 `app/main.py` 只负责注册路由
- [ ] 把页面入口从 `app/api/frontend.py` 中逐步拆到新模块
- [ ] 保持旧行为不变，先做兼容迁移

---

**备注：** 本文件是总路线图。后续每个 Phase 都可以再拆成更细的执行计划和短期分支，不需要一开始就把所有阶段分支全部创建出来。
