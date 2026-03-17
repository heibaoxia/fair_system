from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. 定义数据库文件的存放位置
# 这里我们将数据库文件统一命名为 fair_system.db (放在当前运行的根目录)
SQLALCHEMY_DATABASE_URL = "sqlite:///./fair_system.db"

# 2. 创建数据库引擎 (Engine)
# 引擎就像是一个“连接池经理”，它负责把 Python 代码翻译成 SQLite 能听懂的 SQL 指令。
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    # check_same_thread=False 是 SQLite 在 FastAPI 中使用的特殊设定
    # FastAPI 处理请求是多线程并发的，而 SQLite 默认单线程。加上这个，允许多个请求同时排队访问。
    connect_args={"check_same_thread": False}
)

# 3. 创建本地数据库会话工厂 (SessionLocal)
# 这里的 Session 代表“一次数据库的连接过程”。我们配置它不要自动提交(autocommit=False)，
# 这样在出现错误时，我们可以手动回滚。
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. 创建模型基类 (Base)
# 接下来我们在 app/models.py 里写的所有数据表模型，都要继承这个 Base，
# 这样 SQLAlchemy 才知道：“哦！原来这些类都是要放到数据库里的表”。
Base = declarative_base()