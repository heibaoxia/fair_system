"""
【新手必看指北：应用总入口】
main.py 是我们这个服务器软件的“大门”。
原先的代码里，所有路由（比如 /books）都挤在这个门卫室里。
现在我们把它重构成真正的“微服务”形态：
大门只负责把不同的人（请求），指引给专门接待他们的办公室（比如 api/members.py）。
"""

"""
Fair-System 主机入口
FastAPI 挂载主文件。负责组装全部 API 路由（包括 projects, members, files, assignments, assessments, frontend 等），配置 CORS，并挂载静态资源和模板引擎。
运行此文件即可启动 Web 服务。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from app.database import Base, engine
from app import models

# 引入我们在 api 文件夹里写好的各种专门的处理路由！
from app.api import members, projects, assessments, assignments, files, frontend, modules, project_dependencies, scoring, notifications, swaps

# 1. 创建 FastAPI 实例（建造大门）
app = FastAPI(
    title="超级工评系统 API",
    description="专门为 AI Agent 协作与工时评估打造的后端系统",
    version="1.0.0"
)

# 2. 【新手避坑指南：CORS 跨域】
# 如果以后你要用 VUE 或者是普通的 HTML/JS 通过浏览器连这个 API，
# 浏览器会因为安全原因“拒绝不同网址之间的对话”。加上这段配置就是让大门放行所有浏览器的请求！
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 允许所有人来访问，开发时为了方便填 "*"
    allow_credentials=True,
    allow_methods=["*"], # 允许所有的请求方式 GET/POST/PUT/DELETE
    allow_headers=["*"], # 允许所有的特殊请求头
)

# 2.5 【新手必看：静态文件挂载】
# 当写在 HTML 里的 <link href="/static/style.css"> 请求到达时，
# FastAPI 一看不认识这个网址（因为你没写 @app.get("/static/...")）就会报错 404。
# 所以这里我们需要告诉它："只要是以 /static 开头的链接，你就去我们真实的 app/static 硬盘文件夹里找！"
app.mount("/static", StaticFiles(directory="app/static"), name="static")

Base.metadata.create_all(bind=engine)

with engine.begin() as connection:
    member_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(members)"))}
    if "total_earnings" not in member_columns:
        connection.execute(text("ALTER TABLE members ADD COLUMN total_earnings FLOAT DEFAULT 0.0"))

    project_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(projects)"))}
    if "use_custom_dimensions" not in project_columns:
        connection.execute(text("ALTER TABLE projects ADD COLUMN use_custom_dimensions BOOLEAN DEFAULT 0"))


# 3. 将各个业务模块的路由“挂载”到主程序上！
# 相当于把这些写好的办公室告诉总前台门卫
app.include_router(members.router)
app.include_router(projects.router)
app.include_router(modules.router)
app.include_router(project_dependencies.router)
app.include_router(assessments.router)
app.include_router(assignments.router)
app.include_router(swaps.router)
app.include_router(scoring.router)
app.include_router(notifications.router)
app.include_router(files.router)
app.include_router(frontend.router)

# 要想运行它进行测试，在终端输入：
# uvicorn app.main:app --reload
