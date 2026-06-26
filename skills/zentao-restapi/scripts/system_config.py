"""系统配置解析公共模块 — HTTP 服务专用精简版。

仅导出 Gerrit / Jenkins / ZenTao 脚本用到的组件：ServiceError、ServiceTarget、
配置加载与系统匹配查找、HTTP 连接目标解析、输出辅助函数。
每个 skill 按需携带一份 system_config.py，互不依赖、运行时独立。

⚠️ 此文件在 gerrit-restapi / jenkins-restapi / zentao-restapi 间完全相同，
修改任一处必须同步另外两处。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import parse


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
class ServiceTarget:
    """HTTP 服务连接目标。"""

    url: str
    auth: tuple[str, str] | None
    system_name: str | None = None


def parse_auth(auth_value: str) -> tuple[str, str]:
    username, sep, password = auth_value.partition(":")
    if not sep:
        raise ServiceError("Auth must use username:token or username:password format")
    return username, password


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


def auth_from_system(
    system_config: dict[str, Any] | None,
    password_key: str = "password",
) -> tuple[str, str] | None:
    """从 system config 中提取 (username, password)。"""
    if not system_config:
        return None

    username = str(system_config.get("username", "")).strip()
    password = str(system_config.get(password_key, "")).strip()

    if username and password:
        return username, password
    return None


def system_matches(selector: str, system_name: str, system_config: dict[str, Any]) -> bool:
    """selector 是否匹配 system_name 或其别名 / URL。"""
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

    url = str(system_config.get("url", "")).strip()
    if url:
        parsed = parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        netloc = (parsed.netloc or "").lower()
        if hostname == needle or netloc == needle or url.lower() == needle:
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


def resolve_target(
    url_override: str | None,
    user: str | None,
    system: str | None,
    *,
    config_name: str,
    password_key: str = "password",
) -> ServiceTarget:
    """从配置 + CLI 覆盖参数解析 HTTP 连接目标。"""
    config_data = load_systems_config(config_name)
    systems = config_data["systems"]

    configured_system = system or str(config_data.get("default_system", "")).strip()
    if not configured_system:
        raise ServiceError(f"No --system specified and no default_system in ~/.bicv/{config_name}")

    _, system_config = find_system(configured_system, systems, config_data["_config_path"])

    url = ((url_override or "").strip() or str(system_config.get("url", "")).strip()).rstrip("/")
    if not url:
        raise ServiceError(
            f"System config is missing url field; set url in ~/.bicv/{config_name} for this system"
        )

    auth = parse_auth(user) if user else auth_from_system(system_config, password_key)
    if auth is None:
        raise ServiceError(
            f"This operation requires auth; use --user or set "
            f"username/{password_key} in ~/.bicv/{config_name} for this system"
        )
    return ServiceTarget(url=url, auth=auth, system_name=configured_system)


def print_error(err: ServiceError) -> int:
    """以 JSON 结构把错误输出到 stderr，退出码 1。

    stdout 保持空，便于调用方 / AI 直接 json.loads(stdout) 解析成功结果；
    失败时读 stderr 取 ``{"error": {...}}``。
    """
    print(
        json.dumps(
            {
                "error": {
                    "message": err.message,
                    "status_code": err.status_code,
                    "details": err.response_text or None,
                }
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 1


def print_system(target: ServiceTarget) -> None:
    """人类可读的 System 行，仅供 --format human 等场景使用。

    正常的 JSON 输出路径不再调用它（system 字段已并入 JSON 信封）。
    """
    if target.system_name:
        print(f"System: {target.system_name}")


def print_json_result(target: ServiceTarget, data: Any, heading: str | None = None) -> int:
    """输出统一信封 ``{"system", "data"}`` 到 stdout。

    ``heading`` 入参保留以兼容历史调用点，但不再打印（JSON 输出无需人类标题）。
    stdout 仅含一个可直接 json.loads 的 JSON 值。
    """
    print(json.dumps({"system": target.system_name, "data": data}, ensure_ascii=False, indent=2))
    return 0
