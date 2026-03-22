# Platform Canvas Redraw Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复制现有工评系统网页结构画布，并按“轻广场 + 强协作区”的平台化架构重画一版，同时保留原图例与颜色语义。

**Architecture:** 先解析原 `.canvas` 的图例、颜色、布局密度与页面级节点，再在复制版中重新组织为公开平台区、协作工作区、保障中心、平台运营区四层结构。新版画布强调页面主路径、文件协作与正式交付分层，以及验收-锁定-放款链路，服务后续代码模块化拆分。

**Tech Stack:** JSON Canvas、PowerShell、Python、Obsidian Vault 文件结构

---

### Task 1: 固化输入与原画布约束

**Files:**
- Read: `F:\BaiduSyncdisk\obsidian\01_项目\01_工评系统\修改归档\2006-03-22 网页结构(副本).canvas`
- Read: `docs/superpowers/specs/2026-03-23-platform-canvas-design.md`

- [ ] **Step 1: 读取原画布 JSON**

Run: `python - <<'PY' ... PY` 或 PowerShell 等价命令读取 `nodes` / `edges`

Expected: 能拿到节点、连线、颜色与分组信息

- [ ] **Step 2: 提炼图例规则**

确认红/绿/蓝/黄/紫/橙/灰节点的语义，以及默认/橙色/紫色连线语义

- [ ] **Step 3: 标记页面级节点**

识别原画布中的完整页面、详情页、弹窗、状态节点与信息块

### Task 2: 设计新版页面与模块边界

**Files:**
- Modify: `docs/superpowers/specs/2026-03-23-platform-canvas-design.md`

- [ ] **Step 1: 归纳四大区域**

整理 `公开平台区`、`协作工作区`、`保障中心`、`平台运营区`

- [ ] **Step 2: 明确页面主链路**

定义公开匹配、协作执行、保障结算、组织监控四条主流程

- [ ] **Step 3: 明确模块化映射**

确保页面分区可映射到 `public_market`、`workspace_project`、`project_drive`、`escrow_payout` 等代码模块

### Task 3: 生成复制版新版画布

**Files:**
- Create: `F:\BaiduSyncdisk\obsidian\01_项目\01_工评系统\修改归档\2006-03-23 网页结构(平台化重画版).canvas`

- [ ] **Step 1: 复制原画布为新文件**

Run: PowerShell `Copy-Item`

Expected: 新文件存在，原文件不被修改

- [ ] **Step 2: 用脚本重建节点与连线**

用 Python 读取原文件，生成新版 `nodes` / `edges`

Expected: 保留图例规则，页面结构切换为平台化架构

- [ ] **Step 3: 写回新 canvas**

输出格式化 JSON，编码为 UTF-8

Expected: Obsidian 可直接打开

### Task 4: 校验新版画布

**Files:**
- Test: `F:\BaiduSyncdisk\obsidian\01_项目\01_工评系统\修改归档\2006-03-23 网页结构(平台化重画版).canvas`

- [ ] **Step 1: 校验 JSON 可解析**

Run: `python - <<'PY' ... json.loads(...) ... PY`

Expected: 无 JSON 错误

- [ ] **Step 2: 校验节点与边引用**

确认所有 `fromNode` / `toNode` 都存在，ID 无重复

- [ ] **Step 3: 校验新版主线完整**

确认至少包含：平台首页、项目广场、个人工作台、项目工作台、项目共享文件区、正式交付区、资金保障中心、放款详情页

### Task 5: 交付说明

**Files:**
- Reference: `F:\BaiduSyncdisk\obsidian\01_项目\01_工评系统\修改归档\2006-03-23 网页结构(平台化重画版).canvas`
- Reference: `docs/superpowers/specs/2026-03-23-platform-canvas-design.md`

- [ ] **Step 1: 总结新版结构**

说明四大区域与主流程

- [ ] **Step 2: 说明与旧画布差异**

突出页面拆分、文件协作分层、放款保障链路

- [ ] **Step 3: 说明后续代码模块化方向**

把画布区域与建议代码模块对应起来
