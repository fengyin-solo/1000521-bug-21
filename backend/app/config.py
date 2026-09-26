"""运行配置：端口、跨域、运行环境。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_name: str = "轨道交通信号设备检修平台"
    env: str = "local"
    port: int = 8000
    # 数据落盘文件：状态流转结果写进 JSON，刷新或重启进程后不再回到种子数据。
    data_file: Path = BASE_DIR / "data" / "store.json"
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200


settings = Settings()
