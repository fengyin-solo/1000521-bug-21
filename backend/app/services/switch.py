"""转辙机业务规则：状态流转、字段校验与筛选口径都收在这里。

工作流状态（status）是唯一事实源，档案字段「设备状态」只负责对外展示，
每次状态变更都会同步过去，保证列表、详情、导出看到的口径一致。

状态机（每次只允许执行当前状态支持的动作）：
    待检修   --确认检修-->      运用正常
    运用正常 --登记动作异常-->  动作异常
    动作异常 --更换设备-->      已更换
已更换是终态，不再接受任何动作；同一台转辙机在「动作异常」下重复登记
异常会被幂等拒绝，不会产生第二条记录。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "switch"
REQUIRED_FIELDS = ["设备编号", "设备型号", "安装道岔"]
DISPLAY_STATUS_FIELD = "设备状态"
STATUS_ORDER = ["待检修", "运用正常", "动作异常", "已更换"]

# 各状态下允许执行的动作；不在表里的状态即为终态。
ACTION_RULES: dict[str, dict[str, str]] = {
    "待检修": {"确认检修": "运用正常"},
    "运用正常": {"登记动作异常": "动作异常"},
    "动作异常": {"更换设备": "已更换"},
}
# 仍需后续跟进的状态：待检修与动作异常计入待处理，运用正常、已更换不计入。
PENDING_STATUSES = {"待检修", "动作异常"}
ABNORMAL_STATUSES = {"动作异常"}
# 统计卡片口径：在运＝尚未更换，异常＝动作异常，待检修＝待检修。
ACTIVE_STATUSES = set(STATUS_ORDER) - {"已更换"}

ALL_ACTIONS = ["确认检修", "登记动作异常", "更换设备"]


class SwitchService:
    def __init__(self) -> None:
        # 播种数据的标志位和展示字段可能与工作流状态不一致，启动时先校正一次。
        for row in store.rows(MODULE):
            self._sync_flags(row)

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设备编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def stats(self) -> list[dict[str, Any]]:
        """统计卡片按全量数据计算，不受当前筛选条件影响。"""
        rows = store.rows(MODULE)
        active = sum(1 for row in rows if row.get("status") in ACTIVE_STATUSES)
        abnormal = sum(1 for row in rows if row.get("status") in ABNORMAL_STATUSES)
        waiting = sum(1 for row in rows if row.get("status") == "待检修")
        return [
            {"label": "在运转辙机", "value": active},
            {"label": "动作异常台数", "value": abnormal},
            {"label": "待检修台数", "value": waiting},
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        # 老档案字段照旧保留，新增记录的其余字段留空，由列表统一兜底成 —。
        self._sync_flags(entry)
        rows.append(entry)
        store.save()
        return self._present(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"转辙机 {entry_id} 不存在或已归档"
        if not action:
            return None, "未指定要执行的动作"
        if action not in ALL_ACTIONS:
            return None, f"动作「{action}」不属于转辙机可执行范围"

        current = str(entry.get("status") or "")
        allowed = ACTION_RULES.get(current, {})
        if not allowed:
            # 已更换等终态：任何动作都不再开放。
            return None, f"转辙机当前为「{current}」状态，{action}已不再允许执行"
        # 幂等：同一台转辙机在动作异常状态下重复登记，直接拦下而不是再造一条记录。
        if action == "登记动作异常" and current == "动作异常":
            return None, "该转辙机已处于「动作异常」状态，无需重复登记"
        target = allowed.get(action)
        if target is None:
            return None, f"转辙机当前为「{current}」状态，不允许执行{action}；当前可执行：{self._next_action_hint(current)}"

        entry["status"] = target
        self._sync_flags(entry)
        store.save()
        return self._present(entry), f"转辙机已{action}"

    def _next_action_hint(self, status: str) -> str:
        """被拦下时告诉用户当前状态真正能做的动作。"""
        allowed = ACTION_RULES.get(status, {})
        return "、".join(allowed.keys()) if allowed else "（无可用动作）"

    def _sync_flags(self, entry: dict[str, Any]) -> dict[str, Any]:
        """让档案展示字段与待处理/异常标志始终跟随工作流状态。"""
        status = str(entry.get("status") or STATUS_ORDER[0])
        entry["status"] = status
        entry[DISPLAY_STATUS_FIELD] = status
        entry["pending"] = status in PENDING_STATUSES
        entry["abnormal"] = status in ABNORMAL_STATUSES
        return entry

    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """对外读取前再校正一次，兼容内存里遗留的旧数据。"""
        return dict(self._sync_flags(entry))
