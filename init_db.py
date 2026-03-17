"""
这段代码是我们的“一键建表神器”！
当你修改了 app/models.py 里的表结构，或者第一次拿到代码时，
只需要在终端运行 `python init_db.py`。
它会自动扫描 models.py 里继承了 Base 的类，
然后把它们在 fair_system.db (或者是你刚才在 database.py 指定的数据库里) 变成真实的表格。
"""

from app.database import engine, Base

# 为了让 SQLAlchemy 知道有哪些表，必须把包含表的模块 import 进来！
# 否则即使模型写了，建表时也会因为“我没看到”而被忽略。
from app import models

def init_database():
    print("🚀 正在连接数据库准备建库...")
    # Base.metadata.create_all 是 SQLAlchemy 的一个超级指令。
    # 它的逻辑是：“看一眼当前引擎绑定的数据库，如果哪个表还没建，我就给你建出来！”
    # 如果表已经存在，它默认不会删掉重建，而是直接忽略。
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表结构初始化成功！数据库文件已生成。")

if __name__ == "__main__":
    init_database()
