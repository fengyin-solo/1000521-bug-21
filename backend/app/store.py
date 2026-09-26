"""数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

数据落在进程内存里方便读写，所有写操作都会顺手落一份 JSON 快照到 data/store.json：
页面刷新天然不丢，后端重启后也能接着用。真实项目里这里会换成数据库访问层。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from app.seed import SEED_ROWS

# 快照结构升级时把版本号抬高，旧文件会被忽略并重新播种，避免新旧字段打架。
SNAPSHOT_VERSION = 1
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_SNAPSHOT_PATH = os.path.join(_DATA_DIR, "store.json")


class Store:
    def __init__(self) -> None:
        snapshot = self._load_snapshot()
        if snapshot is None:
            self._tables: dict[str, list[dict[str, Any]]] = {
                name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
            }
        else:
            self._tables = {
                name: [dict(row) for row in rows]
                for name, rows in snapshot.items()
                if isinstance(rows, list)
            }
            # 新版本里新增的模块也要补齐，老快照里不会有它们。
            for name, rows in SEED_ROWS.items():
                self._tables.setdefault(name, [dict(row) for row in rows])

    def _load_snapshot(self) -> dict[str, Any] | None:
        """读取磁盘快照；文件缺失、损坏或版本过旧时返回 None 走播种。"""
        try:
            with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
            return None
        tables = payload.get("tables")
        return tables if isinstance(tables, dict) else None

    def save(self) -> None:
        """把当前全量数据原子写回磁盘，避免半截文件把下次启动搞挂。"""
        os.makedirs(_DATA_DIR, exist_ok=True)
        payload = {"version": SNAPSHOT_VERSION, "tables": self._tables}
        fd, tmp_path = tempfile.mkstemp(prefix=".store-", suffix=".json", dir=_DATA_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp_path, _SNAPSHOT_PATH)
        except OSError:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
