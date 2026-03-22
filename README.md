# Fair-System

Fair-System 是一个面向团队协作的公平分工系统，使用 FastAPI + SQLite + 原生前端页面实现了项目创建、成员协作、多维度评分、批量公平分配、成果提交流转，以及账号/身份/社交邀请等完整流程。

这个项目更像是一个可直接跑起来的业务原型，而不是只提供接口的后端 Demo：

- 有完整网页入口：工作台、项目画板、评分页、社交中心、待办页、全局进度页
- 有完整业务链路：创建项目 -> 配置评分维度 -> 模块评分 -> 公平分配 -> 上传成果 -> 审核推进
- 有完整身份体系：公开注册、邮箱验证、登录会话、超级号切换业务身份
- 有完整协作机制：关注关系、项目邀请、评分提醒、换人申请、依赖解锁

## 适合拿它做什么

- 课程作业 / 毕设 / 团队协作系统原型
- 研究公平分配、评分驱动协作、任务看板交互
- 学习 FastAPI + SQLAlchemy + Jinja2 + 原生 JavaScript 的全栈组合
- 作为后续重构到 Vue / React / 更复杂权限模型的基础底座

## 核心能力

### 1. 项目与模块管理

- 创建项目时由 PM 一次性配置评分维度和权重
- 项目详情页支持新增模块、管理成员、维护依赖关系
- 模块支持状态流转：待分配 / 开发中 / 待审核 / 已完成
- 模块可限制允许上传的文件类型

### 2. 多维度评分

- 每个项目拥有独立的 `scoring_dimensions`
- 评分页按项目维度动态渲染，不是写死的固定字段
- 打分页只负责填分，不允许现场改权重
- 汇总页会按维度展示平均分、权重和综合贡献

### 3. 公平分配

- 支持一键公平分配待分配模块
- 分配时会结合模块综合分和成员历史负载
- 提供预览弹窗，可先看公平指数再确认
- 支持先生成预分配结果，再手动微调后开工
- 评分期进行中时，禁止直接分配和拖拽改派

### 4. 交付与依赖解锁

- 模块负责人可以上传成果文件
- PM 可审核文件，控制通过 / 驳回
- 模块之间可建立前置依赖
- 前置模块未通过时，后置模块不会解锁推进

### 5. 账号、身份与社交

- 公开注册后需要邮箱验证才能登录
- 登录后通过 session cookie 维持会话
- 超级账号可切换业务身份，用不同成员视角验收整个系统
- 普通账号可关注其他用户、查看好友关系
- 已验证普通账号之间支持项目邀请、接受/拒绝邀请

### 6. 配套页面

- `/` 工作台
- `/project/{id}` 项目画板
- `/scoring/{id}` 项目评分页
- `/todo` 我的待办与钱袋子
- `/overview` 全局项目概览
- `/timeline/{id}` 项目全局进度追踪
- `/social` 社交中心
- `/login` / `/register` 认证页面

## 技术栈

- 后端：Python、FastAPI、SQLAlchemy、Pydantic
- 数据库：SQLite
- 前端：Jinja2 模板、原生 JavaScript、HTML、CSS
- 服务启动：Uvicorn
- 测试：Pytest

## 项目结构

```text
fair-system/
├─ app/
│  ├─ api/                 # 各业务路由：auth、projects、assignments、social...
│  ├─ services/            # 业务服务：认证、邮箱、计算、公平分配、邀请
│  ├─ templates/           # 页面模板
│  ├─ static/              # 静态资源
│  ├─ database.py          # SQLAlchemy 引擎与会话
│  ├─ models.py            # 数据模型
│  └─ main.py              # FastAPI 入口
├─ tests/                  # 自动化测试
├─ docs/                   # 历史记录、说明文档、验收文档
├─ uploads/                # 上传文件目录
├─ init_db.py              # 初始化数据库结构
├─ seed_demo_data.py       # 重建演示数据
├─ acceptance_helper.py    # 打印验收用项目/成员/模块 ID
├─ .env.example            # 环境变量示例
├─ fair_system.db          # 本地 SQLite 数据库
└─ README.md
```

## 快速开始

### 方式一：直接跑演示环境（推荐）

1. 创建虚拟环境并安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. 如需启用公开注册和邮箱验证，先复制环境变量示例文件

```bash
copy .env.example .env
```

然后按你的 SMTP 信息修改 `.env` 中的值。

3. 重建演示数据

```bash
python seed_demo_data.py
```

4. 启动服务

```bash
uvicorn app.main:app --reload
```

5. 打开页面

- 系统首页：[http://127.0.0.1:8000](http://127.0.0.1:8000)
- Swagger 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 方式二：只初始化空库

如果你不想导入演示项目，只想先把数据库结构建好：

```bash
python init_db.py
uvicorn app.main:app --reload
```

## 演示账号与演示数据

执行 `python seed_demo_data.py` 后，会自动创建：

- 5 个真实业务成员
- 3 个测试用虚拟身份
- 1 个测试超级账号
- 3 个演示项目（覆盖评分期进行中、评分期结束、公平负载历史等场景）

默认超级账号：

```text
login_id: god
password: 888888
```

建议的演示体验路径：

1. 用 `god / 888888` 登录
2. 在页面左下角切换业务身份
3. 进入不同项目体验评分、分配、待办、时间线和社交功能

## 重要说明

### `seed_demo_data.py` 会重建项目数据

这个脚本不是“增量插入演示数据”，而是会先清空当前数据库里的项目、模块、评分、依赖、成果文件记录等业务数据，再重新生成一套演示场景。

如果你已经在本地录入了自己的项目数据，请先备份 `fair_system.db`。

### 超级号与普通账号的区别

- 超级号主要用于测试和验收，可切换全局业务身份
- 普通账号需要完成邮箱验证后才能登录
- 社交搜索、项目邀请等能力只面向已验证、已激活、非超级账号的普通用户开放

## 邮箱验证配置

如果你要启用“公开注册 + 邮箱验证”这条链路，需要提供下面这些环境变量。

项目现在同时支持两种方式：

- 方式 A：直接在当前 PowerShell 终端里设置环境变量
- 方式 B：复制 `.env.example` 为 `.env`，项目启动时自动读取 `.env`

推荐直接从仓库里的 `.env.example` 复制一份：

```bash
copy .env.example .env
```

再把 `.env` 里的示例值改成你的真实配置。`.env.example` 可以提交到 GitHub，`.env` 不要提交。

### QQ 邮箱（推荐本地测试先用）

```powershell
$env:FAIR_AUTH_VERIFY_URL_BASE="http://127.0.0.1:8000/login"
$env:FAIR_SMTP_HOST="smtp.qq.com"
$env:FAIR_SMTP_PORT="465"
$env:FAIR_EMAIL_FROM="your_qq_mail@qq.com"
$env:FAIR_SMTP_USERNAME="your_qq_mail@qq.com"
$env:FAIR_SMTP_PASSWORD="your_qq_smtp_authorization_code"
$env:FAIR_SMTP_USE_TLS="false"
$env:FAIR_SMTP_USE_SSL="true"
$env:FAIR_SMTP_TIMEOUT_SECONDS="10"
```

注意：

- `FAIR_SMTP_PASSWORD` 需要填写 QQ 邮箱 SMTP 授权码，不是邮箱登录密码
- 如果你更习惯 `.env` 文件，就把上面的值填进 `.env`

### 163 邮箱

```powershell
$env:FAIR_AUTH_VERIFY_URL_BASE="http://127.0.0.1:8000/login"
$env:FAIR_SMTP_HOST="smtp.163.com"
$env:FAIR_SMTP_PORT="465"
$env:FAIR_EMAIL_FROM="your_163_mail@163.com"
$env:FAIR_SMTP_USERNAME="your_163_mail@163.com"
$env:FAIR_SMTP_PASSWORD="your_163_smtp_authorization_code"
$env:FAIR_SMTP_USE_TLS="false"
$env:FAIR_SMTP_USE_SSL="true"
$env:FAIR_SMTP_TIMEOUT_SECONDS="10"
```

### Gmail

```powershell
$env:FAIR_AUTH_VERIFY_URL_BASE="http://127.0.0.1:8000/login"
$env:FAIR_SMTP_HOST="smtp.gmail.com"
$env:FAIR_SMTP_PORT="587"
$env:FAIR_EMAIL_FROM="your_gmail@gmail.com"
$env:FAIR_SMTP_USERNAME="your_gmail@gmail.com"
$env:FAIR_SMTP_PASSWORD="your_google_app_password"
$env:FAIR_SMTP_USE_TLS="true"
$env:FAIR_SMTP_USE_SSL="false"
$env:FAIR_SMTP_TIMEOUT_SECONDS="10"
```

注意：

- Gmail 这里需要使用 Google App Password
- 当前项目不支持 OAuth，只支持 SMTP 用户名 + 授权码 / App Password

可选项：

- `FAIR_SMTP_USE_SSL`
- `FAIR_SMTP_TIMEOUT_SECONDS`

如果没有配置这些变量：

- 页面仍然可以访问
- 超级账号演示模式仍然可用
- 但公开注册接口会因为无法发送验证邮件而不可用

## 常用入口

### 页面入口

- `GET /` 工作台
- `GET /project/{project_id}` 项目详情画板
- `GET /scoring/{project_id}` 评分页
- `GET /todo` 待办页
- `GET /overview` 全局大盘
- `GET /timeline/{project_id}` 时间线
- `GET /social` 社交中心
- `GET /login` 登录页
- `GET /register` 注册页

### 主要 API 分组

- `/auth` 认证、登录、邮箱验证、身份切换
- `/projects` 项目、项目成员、模块创建、评分期设置
- `/modules` 模块查询与更新
- `/assessments` 模块评分
- `/scoring` 综合分与进度汇总
- `/assignments` 公平分配与确认开工
- `/files` 成果上传与审核
- `/project-invites` 项目邀请
- `/social` 搜索、关注、好友关系
- `/swaps` 模块换人申请

## 测试与验收

运行自动化测试：

```bash
python -m pytest
```

如果你的环境里还没有 `pytest`，请先自行安装：

```bash
pip install pytest
```

演示验收常用命令：

```bash
python seed_demo_data.py
python acceptance_helper.py
```

相关文档：

- `docs/t9-acceptance-guide.md`
- `docs/FairSystem_历史开发记录汇总.md`
- `docs/TODO.md`

## 开发提示

- 数据库文件默认是根目录下的 `fair_system.db`
- 上传文件默认写入 `uploads/`
- 启动应用时会自动执行 schema bootstrap
- 前端是模板直出 + 原生 JS，没有额外前端构建步骤
- 如果你只是想理解业务流，优先从 `app/main.py`、`app/models.py`、`app/api/frontend.py` 开始看

## 后续可以继续扩展的方向

- 补充 `.env.example` 和正式部署配置
- 将前端拆分到独立 SPA
- 为公平分配算法加入更多约束项
- 增加更完整的权限分层与操作审计
- 为文件审核、评分提醒、项目邀请补充异步通知机制
