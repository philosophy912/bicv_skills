"""系统配置解析公共模块 — email 专用精简版。

仅导出 email_api.py 用到的函数和数据类型：
  - ServiceError：通用服务错误
  - load_systems_config：从 ~/.bicv/<skill>.json 加载多实例配置

⚠️ 此文件仅用于 email skill，不与其他 skill 共享。
email 脚本通过 import _email_config 导入，避免与其他 skill 的 system_config.py 路径冲突。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ServiceError(Exception):
    """通用服务错误。"""

    message: str
    status_code: int | None = None
    response_text: str = ""

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"{self.message} (HTTP {self.status_code})"


def load_systems_config(config_name: str) -> dict[str, Any]:
    """从 ~/.bicv/<config_name> 加载多实例配置，校验结构并返回 dict。

    Raise ServiceError: 文件不存在、非法 JSON、缺少 systems 键、路径穿越。
    """
    path = (Path.home() / ".bicv" / config_name).resolve()
    home = Path.home().resolve()

    if path.name != config_name:
        raise ServiceError(f"Config file must be named {config_name}: {path}")

    try:
        path.relative_to(home)
    except ValueError as exc:
        raise ServiceError(f"Config file must live under the user home directory: {path}") from exc

    if not path.exists():
        raise ServiceError(f"Cannot find config file: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ServiceError(f"Config file is not valid JSON: {path}") from exc

    systems = data.get("systems")
    if not isinstance(systems, dict):
        raise ServiceError(f"Config file is missing a systems object: {path}")
    data["_config_path"] = str(path)
    return data
