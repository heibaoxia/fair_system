# 工评系统 - 第一个API接口使用说明

## 🎯 我们刚刚创建了什么？

我们成功创建了"工评系统"的**前3个API接口**：

1. **`POST /projects`** - 创建新项目 ✅
2. **`GET /projects`** - 获取项目列表 ✅
3. **`GET /projects/{id}`** - 获取项目详情 ✅

这对应项目需求文档中的前3个API接口！

## 📁 文件结构

```
fair-system/
├── main.py              # 主应用，包含所有API接口
├── models.py            # 数据模型定义
├── test_api.py          # API测试脚本
├── test_env.py          # 环境验证脚本
├── learn_fastapi.md     # FastAPI学习笔记
├── API使用说明.md       # 本文档
├── requirements.txt     # 依赖包列表
├── .gitignore          # Git忽略配置
└── .venv/              # 虚拟环境
```

## 🚀 如何运行

### 步骤1：启动服务器
在PyCharm终端中运行：
```bash
uvicorn main:app --reload
```

### 步骤2：访问API文档
打开浏览器访问：
- **交互式文档**: http://127.0.0.1:8000/docs
- **替代文档**: http://127.0.0.1:8000/redoc

### 步骤3：测试API
#### 方法A：使用API文档（推荐）
1. 访问 http://127.0.0.1:8000/docs
2. 点击 `POST /projects` → "Try it out"
3. 输入项目数据，点击 "Execute"
4. 查看响应结果

#### 方法B：使用测试脚本
在新终端中运行：
```bash
python test_api.py
```

#### 方法C：使用curl命令
```bash
# 创建项目
curl -X POST "http://127.0.0.1:8000/projects" \
  -H "Content-Type: application/json" \
  -d '{"name":"测试项目","description":"这是一个测试"}'

# 获取项目列表
curl "http://127.0.0.1:8000/projects"

# 获取特定项目
curl "http://127.0.0.1:8000/projects/1"
```

## 🔧 API接口详情

### 1. 根路径 `GET /`
**功能**: 欢迎页面，显示可用接口
**响应示例**:
```json
{
  "message": "欢迎使用工评系统 API",
  "version": "1.0.0",
  "description": "公平协作分工平台",
  "available_endpoints": [...]
}
```

### 2. 创建项目 `POST /projects`
**功能**: 创建新项目（对应需求文档第1个API）
**请求体**:
```json
{
  "name": "项目名称",
  "description": "项目描述",
  "start_date": "2026-01-30T10:00:00",
  "end_date": "2026-02-28T18:00:00"
}
```

**响应示例**:
```json
{
  "id": 1,
  "name": "项目名称",
  "description": "项目描述",
  "start_date": "2026-01-30T10:00:00",
  "end_date": "2026-02-28T18:00:00",
  "status": "planning",
  "created_at": "2026-01-30T14:30:00",
  "updated_at": "2026-01-30T14:30:00"
}
```

### 3. 获取项目列表 `GET /projects`
**功能**: 获取所有项目（对应需求文档第2个API）
**响应**: 项目列表数组

### 4. 获取项目详情 `GET /projects/{id}`
**功能**: 获取特定项目（对应需求文档第3个API）
**路径参数**: `id` - 项目ID

### 5. 健康检查 `GET /health`
**功能**: 检查API服务状态

## 📚 代码学习要点

### 1. 数据模型（models.py）
```python
# 请求数据模型
class ProjectCreate(BaseModel):
    name: str
    description: str

# 响应数据模型
class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
```

### 2. API路由（main.py）
```python
@app.post("/projects", response_model=ProjectResponse)
async def create_project(project: ProjectCreate):
    # 1. 接收请求数据
    # 2. 处理业务逻辑
    # 3. 返回响应
```

### 3. 错误处理
```python
raise HTTPException(
    status_code=404,
    detail="项目不存在"
)
```

## 🎯 这一步在项目中的意义

### 1. **实现了需求文档的前3个API**
- ✅ `POST /projects` - 创建项目
- ✅ `GET /projects` - 获取项目列表
- ✅ `GET /projects/{id}` - 获取项目详情

### 2. **建立了项目的基础架构**
- 数据模型定义
- API路由结构
- 错误处理机制
- 测试框架

### 3. **为后续39个API提供了模板**
- 其他API可以参照这个模式开发
- 统一的代码风格和结构

### 4. **验证了技术栈可行性**
- Python + FastAPI 可以满足项目需求
- 虚拟环境配置正确
- 开发流程可行

## 🔄 开发流程总结

1. **需求分析** → 查看项目简介文档
2. **设计API** → 定义接口和数据模型
3. **编写代码** → 实现业务逻辑
4. **测试验证** → 确保功能正常
5. **文档记录** → 编写使用说明

## 🚀 下一步建议

### 短期（接下来1-2天）：
1. **运行测试**：确保API正常工作
2. **添加更多字段**：根据需求文档完善项目模型
3. **创建成员API**：实现 `POST /projects/{id}/members`

### 中期（1周内）：
1. **添加数据库**：从内存列表切换到SQLite
2. **实现更多API**：完成项目管理模块的所有API
3. **添加前端界面**：简单的HTML表单

### 长期（1个月内）：
1. **实现分配算法**：工作量平衡、技能匹配等
2. **完善所有42个API**
3. **部署上线**

## 💡 学习收获

通过这一步，你学会了：
1. 如何设计RESTful API接口
2. 如何使用FastAPI创建Web服务
3. 如何使用Pydantic进行数据验证
4. 如何编写API测试代码
5. 如何阅读和实现需求文档

## 📞 遇到问题？

1. **API无法访问**：检查服务器是否启动 `uvicorn main:app --reload`
2. **导入错误**：确保在虚拟环境中运行
3. **数据验证失败**：检查请求体格式是否正确
4. **其他问题**：查看终端错误信息，或询问AI助手

---
*恭喜！你已经成功创建了"工评系统"的第一个API接口！这是从0到1的关键一步！* 🎉

**下一步**：运行服务器，测试API，然后我们可以继续实现更多功能！