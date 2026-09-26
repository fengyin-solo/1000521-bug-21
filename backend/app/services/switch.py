"""转辙机业务规则：状态流转、字段校验与筛选口径都收在这里。

状态机（每次只能执行当前状态允许的动作）：

    待检修 ──确认检修──▶ 运用正常
    运用正常 ──登记动作异常──▶ 动作异常
    动作异常 ──确认检修──▶ 运用正常        （处理完恢复运用）
    动作异常 ──更换设备──▶ 已更换        （终态）

其余动作一律拒绝并说明原因；终态「已更换」不再接受任何动作。
同一台转辙机已经处于「动作异常」时再次登记，按重复登记拒绝，不会产生第二条记录。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "switch"
REQUIRED_FIELDS = ["设备编号", "设备型号", "安装道岔"]
STATUS_ORDER = ["待检修", "运用正常", "动作异常", "已更换"]
DISPLAY_STATUS_FIELD = "设备状态"
ABNORMAL_STATUS = "动作异常"
TERMINAL_STATUS = "已更换"
PENDING_STATUSES = {"待检修", "动作异常"}

# 每个状态当前允许执行的动作；不在表里的动作点击后会被拒绝并给出原因。
ALLOWED_ACTIONS: dict[str, dict[str, str]] = {
    "待检修": {"确认检修": "待检修的转辙机需先确认检修后才能运用"},
    "运用正常": {"登记动作异常": "只有运用中的转辙机才需要登记动作异常"},
    "动作异常": {"确认检修": "动作异常的转辙机经处理后确认检修即可恢复运用",
              "更换设备": "动作异常的转辙机无法修复时方可更换设备"},
    "已更换": {},
}
ACTION_TARGET = {
    "确认检修": "运用正常",
    "登记动作异常": "动作异常",
    "更换设备": "已更换",
}


class SwitchService:
    def __init__(self) -> None:
        # 载入旧数据（含种子、历史落盘）后先把标志位与状态列对齐，
        # 已更换设备不再留在待处理队列，异常量也与「动作异常」台数一致。
        changed = False
        for row in store.rows(MODULE):
            if self._sync_row_flags(row):
                changed = True
        if changed:
            store.persist()

    def _sync_row_flags(self, row: dict[str, Any]) -> bool:
        """把 pending / abnormal / 设备状态列与真实 status 对齐，返回是否发生过修改。"""
        status = str(row.get("status") or "")
        changed = False
        expected_pending = status in PENDING_STATUSES
        expected_abnormal = status == ABNORMAL_STATUS
        if bool(row.get("pending")) != expected_pending:
            row["pending"] = expected_pending
            changed = True
        if bool(row.get("abnormal")) != expected_abnormal:
            row["abnormal"] = expected_abnormal
            changed = True
        if row.get(DISPLAY_STATUS_FIELD) != status and status in STATUS_ORDER:
            row[DISPLAY_STATUS_FIELD] = status
            changed = True
        return changed

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        """出参前再对齐一次，保证列表与明细里的「设备状态」列反映真实状态。"""
        self._sync_row_flags(row)
        return row

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._view(dict(row)) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设备编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._view(row) if row is not None else None

    def stats(self) -> dict[str, int]:
        """转辙机统计卡片：在运、动作异常、待检修台数，口径与列表状态一致。"""
        rows = store.rows(MODULE)
        return {
            "running": sum(1 for row in rows if row.get("status") == "运用正常"),
            "abnormal": sum(1 for row in rows if row.get("status") == ABNORMAL_STATUS),
            "pending_repair": sum(1 for row in rows if row.get("status") == "待检修"),
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 列表「设备状态」列与真实状态保持一致，其余档案字段照旧。
        entry[DISPLAY_STATUS_FIELD] = STATUS_ORDER[0]
        rows.append(entry)
        store.persist()
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"转辙机 {entry_id} 不存在或已归档"
        action = action.strip()
        if action not in ACTION_TARGET:
            return None, f"动作「{action}」不属于转辙机可执行范围"

        status = str(entry.get("status") or "")
        allowed = ALLOWED_ACTIONS.get(status, {})
        if action not in allowed:
            return None, self._reject_reason(action, status)

        target = ACTION_TARGET[action]
        entry["status"] = target
        entry["pending"] = target in PENDING_STATUSES
        entry["abnormal"] = target == ABNORMAL_STATUS
        entry[DISPLAY_STATUS_FIELD] = target
        store.persist()
        return entry, f"转辙机已{action}，当前状态：{target}"

    def _reject_reason(self, action: str, status: str) -> str:
        """给出为什么当前状态不能执行该动作的可读说明。"""
        if status == TERMINAL_STATUS:
            return f"转辙机已更换并归档，终态不再执行「{action}」"
        if status == "待检修":
            if action == "登记动作异常":
                return "转辙机尚在待检修，未投入运用，不能登记动作异常，请先确认检修"
            if action == "更换设备":
                return "转辙机尚在待检修，未投入运用，不能直接更换，请先确认检修"
        if status == "运用正常":
            if action == "确认检修":
                return "转辙机已处于运用正常，无需重复确认检修"
            if action == "更换设备":
                return "运用正常的转辙机不允许直接更换，需先登记动作异常并确认无法修复"
        if status == ABNORMAL_STATUS:
            if action == "登记动作异常":
                # 幂等：同一台连续登记两次不能再产生记录。
                return "该转辙机已处于动作异常状态，重复登记不会重复记录，请先确认检修或更换设备"
        return f"当前状态「{status}」不允许执行「{action}」"
