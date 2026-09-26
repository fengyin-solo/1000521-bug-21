"""转辙机接口：维护转辙机，覆盖确认检修、登记动作异常、更换设备等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.switch import SwitchService

router = APIRouter(prefix="/api/switch", tags=["转辙机"])

service = SwitchService()

LIST_FIELDS = ["设备编号", "设备型号", "安装道岔", "动作电流", "转换时间", "所属区段", "上次检修日", "设备状态"]
STATUSES = ["待检修", "运用正常", "动作异常", "已更换"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按设备编号检索"),
    status: str | None = Query(default=None, description="待检修、运用正常、动作异常、已更换"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按设备编号与状态过滤转辙机列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """顶部统计卡片：在运、动作异常、待检修台数，动作执行后随列表一起刷新。"""
    return {"items": service.stats()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出转辙机清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "switch", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条转辙机明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"转辙机 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条转辙机，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="转辙机已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条转辙机执行确认检修、登记动作异常、更换设备；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
