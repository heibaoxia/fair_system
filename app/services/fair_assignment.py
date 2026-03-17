from statistics import pstdev
from typing import Any, Dict, Iterable, List, Sequence


class FairBatchAssignmentRule:
    def assign(self, modules: Sequence[Any], members: Sequence[Any], member_loads: Dict[int, float]) -> Dict[str, Any]:
        member_ids = [int(getattr(member, "id")) for member in members]
        assignments = {member_id: [] for member_id in member_ids}
        total_loads = {member_id: float(member_loads.get(member_id, 0.0) or 0.0) for member_id in member_ids}

        sorted_modules = sorted(modules, key=self._module_score, reverse=True)
        if not member_ids or not sorted_modules:
            return {
                "assignments": assignments,
                "member_total_loads": total_loads,
                "fairness_index": 0.0,
            }

        remaining_modules = list(sorted_modules)
        if len(remaining_modules) >= len(member_ids):
            unassigned_members = set(member_ids)
            while unassigned_members and remaining_modules:
                module = remaining_modules.pop(0)
                member_id = min(unassigned_members, key=lambda item: (total_loads[item], item))
                self._assign_module(module, member_id, assignments, total_loads)
                unassigned_members.remove(member_id)

        for module in remaining_modules:
            member_id = min(member_ids, key=lambda item: (total_loads[item], item))
            self._assign_module(module, member_id, assignments, total_loads)

        fairness_index = self._fairness_index(total_loads.values())
        return {
            "assignments": assignments,
            "member_total_loads": {member_id: round(load, 2) for member_id, load in total_loads.items()},
            "fairness_index": fairness_index,
        }

    def _assign_module(self, module: Any, member_id: int, assignments: Dict[int, List[int]], total_loads: Dict[int, float]) -> None:
        assignments[member_id].append(self._module_id(module))
        total_loads[member_id] += self._module_score(module)

    def _module_id(self, module: Any) -> int:
        if isinstance(module, dict):
            return int(module["module_id"] if "module_id" in module else module["id"])
        return int(getattr(module, "module_id", getattr(module, "id")))

    def _module_score(self, module: Any) -> float:
        if isinstance(module, dict):
            return float(module.get("composite_score", 0.0) or 0.0)
        return float(getattr(module, "composite_score", 0.0) or 0.0)

    def _fairness_index(self, loads: Iterable[float]) -> float:
        values = [float(load) for load in loads]
        if not values:
            return 0.0

        average = sum(values) / len(values)
        if average <= 0:
            return 0.0

        return round(pstdev(values) / average, 4)
