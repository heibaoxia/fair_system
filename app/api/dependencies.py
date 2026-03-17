"""
Fair-System FastAPI 依赖注入
提供供各个请求路由使用的公共依赖函数，如数据库会话工厂 get_db()。
"""
from app.database import SessionLocal

# FastAPI 特有的一种写法，叫“依赖注入 (Dependency Injection)”。
# 我们在每次接口被人请求时，都需要去连一次数据库；请求结束后，又必须关掉数据库。
# 如果每次都手动写，代码会很长。把这个封装成一个函数：
def get_db():
    db = SessionLocal()
    try:
        # yield 是一个神奇的词：它说“给你数据库钥匙，你先用着，用完了再回来找我”
        yield db
    finally:
        # 只要你用完了（请求结束了），这里就负责强制关门，不会因为报错而一直占用数据库！
        db.close()
