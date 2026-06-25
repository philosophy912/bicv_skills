"""系统配置解析公共模块 — MySQL 专用精简版。

仅导出 mysql_query.py 用到的函数和数据类型：
  - ServiceError：通用服务错误
  - MySQLConnectionConfig：MySQL 连接参数 dataclass
  - load_systems_config / find_system / system_matches：配置加载与系统匹配
  - resolve_mysql_config：从 ~/.bicv/mysql.json 解析连接参数
  - print_error：错误输出辅助

⚠️ 此文件仅用于 mysql skill，不与其他 skill 共享。
mysql 脚本通过 import _mysql_config 导入，避免与其他 skill 的 system_config.py 路径冲突。
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


@dataclass
class MySQLConnectionConfig:
    """MySQL 连接参数。"""

    host: str
    port: int
    database: str | None
    username: str
    password: str
    system_name: str | None = None


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
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ServiceError(f"Config file is not valid JSON: {path}") from exc

    systems = data.get("systems")
    if not isinstance(systems, dict):
        raise ServiceError(f"Config file is missing a systems object: {path}")
    data["_config_path"] = str(path)
    return data


def system_matches(selector: str, system_name: str, system_config: dict[str, Any]) -> bool:
    """selector 是否匹配 system_name 或其别名 / host。"""
    needle = selector.strip().lower()
    if not needle:
        return False

    if system_name.lower() == needle:
        return True

    aliases = system_config.get("aliases", [])
    if isinstance(aliases, list):
        for alias in aliases:
            if str(alias).strip().lower() == needle:
                return True

    host = str(system_config.get("host", "")).strip()
    if host and host.lower() == needle:
        return True

    return False


def find_system(
    selector: str, systems: dict[str, Any], config_path: str
) -> tuple[str, dict[str, Any]]:
    """从 systems 中解析 selector，返回 (name, config)。"""
    exact = systems.get(selector)
    if isinstance(exact, dict):
        return selector, exact

    matches: list[tuple[str, dict[str, Any]]] = []
    for system_name, system_config in systems.items():
        if isinstance(system_config, dict) and system_matches(selector, system_name, system_config):
            matches.append((system_name, system_config))

    if not matches:
        raise ServiceError(f"System {selector!r} does not exist in {config_path}")
    if len(matches) > 1:
        names = ", ".join(name for name, _ in matches)
        raise ServiceError(f"System selector {selector!r} matches multiple configs: {names}")
    return matches[0]


def resolve_mysql_config(
    system: str | None = None,
    *,
    config_name: str = "mysql.json",
) -> MySQLConnectionConfig:
    """从 ~/.bicv/<config_name> 解析 MySQL 连接参数。"""
    config_data = load_systems_config(config_name)
    systems = config_data["systems"]

    configured_system = system or str(config_data.get("default_system", "")).strip()
    if not configured_system:
        raise ServiceError(f"No --system specified and no default_system in ~/.bicv/{config_name}")

    system_name, system_config = find_system(
        configured_system, systems, config_data["_config_path"]
    )

    host = str(system_config.get("host", "")).strip()
    if not host:
        raise ServiceError(
            f"System config is missing host field; set host in ~/.bicv/{config_name}"
            f" for system {system_name!r}"
        )

    username = str(system_config.get("username", "")).strip()
    password = str(system_config.get("password", "")).strip()

    port_raw = system_config.get("port")
    try:
        port = int(port_raw) if port_raw is not None else 3306
    except (TypeError, ValueError) as exc:
        raise ServiceError(
            f"Invalid port value {port_raw!r} in ~/.bicv/{config_name} for system {system_name!r}"
        ) from exc

    database = str(system_config.get("database", "")).strip() or None

    return MySQLConnectionConfig(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        system_name=system_name,
    )


def print_error(err: ServiceError) -> int:
    print(f"Error: {err}")
    if err.response_text:
        print(err.response_text.strip())
    return 1
