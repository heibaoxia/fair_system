"""
Fair-System 分配机制的数据结构
定义了智能分配算法所需的输入输出模型，例如前端传来的各类维度权重。
"""
from typing import Dict, List

from pydantic import BaseModel

class MemberLoad(BaseModel):
    member_id: int
    member_name: str
    existing_30day_score: float
    new_assigned_score: float
    total_30day_score: float
    assigned_modules: List[int]


class BatchAssignmentResult(BaseModel):
    member_loads: List[MemberLoad]
    fairness_index: float


class BatchAssignmentConfirmRequest(BaseModel):
    assignments: Dict[int, List[int]]
