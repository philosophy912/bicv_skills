"""Shared system-config resolution for Gerrit / Jenkins API scripts.

Extracts ~200 lines duplicated between gerrit_api.py and jenkins_api.py into a
single module. Each script keeps its own service-specific subclass of ServiceError
and ServiceTarget, plus its own HTTP/API logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import parse


# ---------------------------------------------------------------------------
# Base error / target
# ---------------------------------------------------------------------------


@dataclass
class ServiceError(Exception):
    message: str
    status_code: int | None = None
    response_text: str = ""

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"{self.message} (HTTP {self.status_code})"


@dataclass
class ServiceTarget:
    url: str
    auth: tuple[str, str] | None
    system_name: str | None = None


@dataclass
class MySQLConnectionConfig:
    """Resolved MySQL connection parameters."""

    host: str
    port: int
    database: str | None
    username: str
    password: str
    system_name: str | None = None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def parse_auth(auth_value: str) -> tuple[str, str]:
    username, sep, password = auth_value.partition(":")
    if not sep:
        raise ServiceError("Auth must use username:token or username:password format")
    return username, password


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_systems_config(config_name: str) -> dict[str, Any]:
    """Load ``~/<config_name>``, validate structure, return dict.

    Raises ``ServiceError`` on any problem (missing file, bad JSON, missing
    ``systems`` key, path traversal).
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


# ---------------------------------------------------------------------------
# Auth from system config
# ---------------------------------------------------------------------------


def auth_from_system(
    system_config: dict[str, Any] | None,
    password_key: str = "password",
) -> tuple[str, str] | None:
    """Extract (username, password) from a system config dict.

    *password_key* lets callers choose between ``"password"`` (Jenkins) and
    ``"http_password"`` (Gerrit).
    """
    if not system_config:
        return None

    username = str(system_config.get("username", "")).strip()
    password = str(system_config.get(password_key, "")).strip()

    if username and password:
        return username, password
    return None


# ---------------------------------------------------------------------------
# System matching & lookup
# ---------------------------------------------------------------------------


def system_matches(
    selector: str, system_name: str, system_config: dict[str, Any]
) -> bool:
    """Check whether *selector* matches *system_name* or its aliases / url."""
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

    # MySQL-style configs use ``host`` instead of ``url``.
    host = str(system_config.get("host", "")).strip()
    if host and host.lower() == needle:
        return True

    return False


def find_system(
    selector: str, systems: dict[str, Any], config_path: str
) -> tuple[str, dict[str, Any]]:
    """Resolve *selector* to a ``(name, config)`` pair in *systems*.

    Tries exact key match first, then falls back to alias / url matching.
    """
    exact = systems.get(selector)
    if isinstance(exact, dict):
        return selector, exact

    matches: list[tuple[str, dict[str, Any]]] = []
    for system_name, system_config in systems.items():
        if isinstance(system_config, dict) and system_matches(
            selector, system_name, system_config
        ):
            matches.append((system_name, system_config))

    if not matches:
        raise ServiceError(f"System {selector!r} does not exist in {config_path}")
    if len(matches) > 1:
        names = ", ".join(name for name, _ in matches)
        raise ServiceError(
            f"System selector {selector!r} matches multiple configs: {names}"
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Target resolution (the big one)
# ---------------------------------------------------------------------------


def resolve_target(
    url_override: str | None,
    user: str | None,
    system: str | None,
    *,
    config_name: str,
    password_key: str = "password",
) -> ServiceTarget:
    """Resolve connection target from config file + CLI overrides.

    Parameters
    ----------
    url_override:
        Explicit URL from ``--gerrit`` / ``--jenkins`` CLI flag.
    user:
        Explicit ``username:password`` from ``--user`` CLI flag.
    system:
        Named system from ``--system`` CLI flag.
    config_name:
        Config filename, e.g. ``"gerrit.json"`` or ``"jenkins.json"``.
    password_key:
        Config key for the password field (``"http_password"`` for Gerrit,
        ``"password"`` for Jenkins).
    """
    config_data = load_systems_config(config_name)
    systems = config_data["systems"]

    configured_system = system or str(config_data.get("default_system", "")).strip()
    if not configured_system:
        raise ServiceError(
            f"No --system specified and no default_system in ~/.bicv/{config_name}"
        )

    _, system_config = find_system(
        configured_system, systems, config_data["_config_path"]
    )

    url = (
        (url_override or "").strip()
        or str(system_config.get("url", "")).strip()
    ).rstrip("/")
    if not url:
        raise ServiceError(
            f"System config is missing url field; set url in ~/.bicv/{config_name} for this system"
        )

    auth = (
        parse_auth(user) if user else auth_from_system(system_config, password_key)
    )
    if auth is None:
        raise ServiceError(
            f"This operation requires auth; use --user or set "
            f"username/{password_key} in ~/.bicv/{config_name} for this system"
        )
    return ServiceTarget(url=url, auth=auth, system_name=configured_system)


# ---------------------------------------------------------------------------
# MySQL config resolution
# ---------------------------------------------------------------------------


def resolve_mysql_config(
    system: str | None = None,
    *,
    config_name: str = "mysql.json",
) -> MySQLConnectionConfig:
    """Resolve MySQL connection parameters from ``~/.bicv/<config_name>``.

    Reuses ``load_systems_config`` and ``find_system`` so MySQL configs get the
    same path-traversal protection, system-matching (name / alias / host), and
    error-reporting as Gerrit / Jenkins.
    """
    config_data = load_systems_config(config_name)
    systems = config_data["systems"]

    configured_system = system or str(config_data.get("default_system", "")).strip()
    if not configured_system:
        raise ServiceError(
            f"No --system specified and no default_system in ~/.bicv/{config_name}"
        )

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
    except (TypeError, ValueError):
        raise ServiceError(
            f"Invalid port value {port_raw!r} in ~/.bicv/{config_name}"
            f" for system {system_name!r}"
        )

    database = str(system_config.get("database", "")).strip() or None

    return MySQLConnectionConfig(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        system_name=system_name,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def print_error(err: ServiceError) -> int:
    print(f"Error: {err}")
    if err.response_text:
        print(err.response_text.strip())
    return 1


def print_system(target: ServiceTarget) -> None:
    if target.system_name:
        print(f"System: {target.system_name}")


def print_json_result(
    target: ServiceTarget, data: Any, heading: str | None = None
) -> int:
    print_system(target)
    if heading:
        print(heading)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0
