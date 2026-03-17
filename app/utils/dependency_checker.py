"""
【小贴士：依赖解决工具包】
什么是“工具包” (Utils)？
像判断一个模块能否被解锁这种功能，不属于增加数据库，也不属于直接修改，
而是一种复杂的组合拳查询。而且它可能被很多地方用到（比如前端分配、审核通过后）。
所以我们单独写在工具包里供大家调用。
"""

from typing import cast

from sqlalchemy.orm import Session
from app.models import Module, FileDependency, ModuleFile
from fastapi import HTTPException

def check_module_unlocked(module_id: int, db: Session) -> bool:
    """
    用来给整个后端的保安函数：
    "喂！这个模块可以开始做了吗？上面给它布置的前置老大哥们的数据都审批过了没？"
    它返回 True（可以）或者 False（不行）
    """
    
    # 1. 这个模块有没有“必须等别人做完才能解锁”的前置任务？
    dependencies = db.query(FileDependency).filter(
        FileDependency.dependent_module_id == module_id
    ).all()
    
    if not dependencies:
        # 连依赖都没有设定，那当然直接开大招：随便接！
        return True 

    # 2. 如果他有需要等待的大哥，我们就一个个查大哥是不是真的上传过了！
    for dep in dependencies:
        preceding_module_id = dep.preceding_module_id
        
        # 拿着前置老大的 ID 去模块文件表（ModuleFile）里找
        # 我们看看老大有没有在这个表里留下一份状态是 "Approved" （通过审核）的文件记录
        approved_files = db.query(ModuleFile).filter(
            ModuleFile.module_id == preceding_module_id,
            ModuleFile.status == "Approved"
        ).first()

        # 只要有一个老大哥在摸鱼，没有哪怕一份批准过的成果文件
        if not approved_files:
            return False 
            
    # 如果上面的 for 循环全部扛住了，没走 False，说明所有前置条件全部达标了。
    return True


def would_create_cycle(preceding_module_id: int, dependent_module_id: int, db: Session, extra_edges=None) -> bool:
    """
    如果新增一条 preceding -> dependent 之后，会让依赖图出现回路，就返回 True。
    实现方法很直接：检查 dependent 这边能不能顺着现有依赖再走回 preceding。
    """

    extra_edges = extra_edges or set()
    stack = [dependent_module_id]
    visited = set()

    while stack:
        current = stack.pop()
        if current == preceding_module_id:
            return True
        if current in visited:
            continue
        visited.add(current)

        next_dependencies = db.query(FileDependency).filter(
            FileDependency.preceding_module_id == current
        ).all()
        for dependency in next_dependencies:
            stack.append(cast(int, getattr(dependency, "dependent_module_id")))

        for extra_preceding, extra_dependent in extra_edges:
            if extra_preceding == current:
                stack.append(extra_dependent)

    return False
