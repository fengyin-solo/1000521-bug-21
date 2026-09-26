"""数据仓库：种子数据打底，所有变更落盘到本地 JSON，刷新与重启后结果不丢。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
落盘文件在首次启动时由种子数据生成，之后以文件为准；写盘采用临时文件 + 原子替换，
避免半写文件把数据弄坏。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any

from app.config import settings
from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tables: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        path = settings.data_file
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    self._tables = {
                        name: [dict(row) for row in rows]
                        for name, rows in payload.items()
                        if isinstance(rows, list)
                    }
            except (json.JSONDecodeError, OSError):
                # 落盘文件损坏时回退到种子数据，并在下面立即重写一份干净的。
                self._tables = {
                    name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
                }
        else:
            self._tables = {
                name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
            }
        # 新模块上线或种子扩表时，旧落盘文件里没有的模块用种子数据补齐。
        changed = False
        for name, rows in SEED_ROWS.items():
            if name not in self._tables:
                self._tables[name] = [dict(row) for row in rows]
                changed = True
        if changed or not path.exists():
            self._persist()

    def _persist(self) -> None:
        """把当前全量数据原子写回落盘文件；调用方需已持有锁。"""
        path = settings.data_file
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._tables, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def persist(self) -> None:
        """业务层完成一次变更后调用，保证刷新页面后结果还在。"""
        with self._lock:
            self._persist()

    def module_names(self) -> list[str]:
        with self._lock:
            return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            for row in self.rows(module):
                if int(row.get("id", 0)) == entry_id:
                    return row
        return None

    def overview(self) -> dict[str, object]:
        with self._lock:
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
