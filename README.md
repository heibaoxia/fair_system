# Fair-System

Fair-System 是一个面向团队协作的项目分配系统，当前版本的核心规则是：

- 项目的评分维度和权重只能在创建项目时由 PM 设置
- 打分页只负责填分，不再允许现场改权重
- 项目详情、汇总页和公平分配都读取同一套项目评分配置

## 当前评分模型

- 每个项目都有自己独立的 `scoring_dimensions`
- 至少需要 1 个评分维度
- 权重总和必须等于 `1`
- 项目创建后，本轮不提供编辑评分维度和权重的入口

## 主要能力

- 工作台：查看项目池，并以当前成员身份创建项目
- 项目画板：管理模块、成员、依赖关系和评分期
- 独立打分：成员按项目既定维度提交模块评分
- 综合分汇总：按动态维度展示平均分、权重和加权贡献
- 公平分配：基于评分结果辅助分配模块

## 技术栈

- 后端：Python + FastAPI
- 数据库：SQLite + SQLAlchemy
- 前端：原生 JavaScript + HTML + CSS

## 快速启动

1. 创建虚拟环境并安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. 初始化数据库并写入演示数据

```bash
python init_db.py
python seed_demo_data.py
```

3. 启动服务

```bash
uvicorn app.main:app --reload
```

然后打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

## 演示数据说明

`python seed_demo_data.py` 会清理旧的项目演示数据，并重新生成一批基于自定义评分维度的项目、模块和评分记录。
