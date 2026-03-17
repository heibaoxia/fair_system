"""
【新手必看指北：贡献计算核心】
大家最关心的“钱怎么分”就在这里算出来了！
根据你的需求指南，我们做了一个简化但绝对公平的第一版：
1. 【工作量分】：模块本身的平均预估工时。
2. 【质量分】：所有审查通过的模块质量都统一按合格标准（3分）计算。
3. 【效率分】：如果按时做完，效率分是 1.0；做得快可以稍微有奖励（比如 1.2），这里我们为了演示先统一视为 1.0。

总贡献积分 = 预估工作量 * 效率分(1.0) * 质量分(3.0)
分配金额 = (个人总积分 / 全员总积分) * 项目总金额
"""

from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models import Project, Module, Member, ModuleAssessment

class ProjectContributionCalculator:
    
    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id
        
        # 1. 把这个项目以及它名下所有模块查出来
        self.project = self.db.query(Project).filter(Project.id == project_id).first()
        if not self.project:
            raise ValueError("查无此项目")
            
        self.modules = self.db.query(Module).filter(
            Module.project_id == project_id,
            Module.status == "已完成"  # 只有真正完成（并且通过了审核）的模块才算钱！
        ).all()

    def _get_module_avg_estimated_hours(self, module_id: int) -> float:
        """内部小工具：算出一个模块大家的平均预估工时"""
        assessments = self.db.query(ModuleAssessment).filter(ModuleAssessment.module_id == module_id).all()
        if not assessments:
            return 0.0 # 如果从头到尾没人打分，那就是0
            
        total_hours = sum(a.estimated_hours for a in assessments)
        return total_hours / len(assessments)
        
    def calculate_distribution(self) -> Dict[str, Any]:
        """核心计算方法：计算出每个人的应得份额和总榜单"""
        # 第一步：计算每个人赚了多少“积分”
        member_points_map = {} # {'小明': 15.5, '老王': 20.3}
        
        for module in self.modules:
            # 找到做这个任务的那个人 (如果是空的说明没分配好，正常来说已完成的任务都有人)
            if not module.assigned_to:
                continue
                
            actual_member = self.db.query(Member).filter(Member.id == module.assigned_to).first()
            if not actual_member:
                continue
                
            # 获取这个模块大家的平均预期时长
            avg_hours = self._get_module_avg_estimated_hours(module.id)
            
            # 【核心公式】：质量分固定3，效率固定1
            points = avg_hours * 1.0 * 3.0
            
            if actual_member.name in member_points_map:
                member_points_map[actual_member.name] += points
            else:
                member_points_map[actual_member.name] = points
                
        # 第二步：大家的总积分加在一起有多大？
        total_points = sum(member_points_map.values())
        
        # 第三步：分蛋糕！如果项目总金额是0，那大家分到的钱也是0
        total_money = self.project.total_revenue
        
        final_distribution = []
        for name, points in member_points_map.items():
            # 算出他占的百分比，比如 0.25 就是 25%
            percentage = (points / total_points) if total_points > 0 else 0
            # 算出他应该分多少钱 (保留两位小数)
            money_share = round(total_money * percentage, 2)
            
            final_distribution.append({
                "member_name": name,
                "points": round(points, 2), # 赚了多少分
                "percentage": round(percentage * 100, 2), # 占了百分之几
                "money_share": money_share # 分到多少块钱
            })
            
        # 根据谁分的钱多排个序，大哥在最上面！
        final_distribution.sort(key=lambda x: x['money_share'], reverse=True)
            
        return {
            "project_name": self.project.name,
            "total_revenue": total_money,
            "total_work_points": round(total_points, 2),
            "distribution": final_distribution
        }
