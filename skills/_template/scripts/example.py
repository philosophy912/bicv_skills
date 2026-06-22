#!/usr/bin/env python3
"""Skill 脚本模板：演示如何通过 shared.system_config 读取配置。

shared.system_config.load_systems_config() 会从 ~/.bicv/<config_name>.json
读取配置，路径解析交给它，plugin 安装后仍能正常工作。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.system_config import ServiceError, load_systems_config  # noqa: E402

CONFIG_NAME = "<skill-name>.json"  # 与 skill 目录名一致


def get_system(system_name: str | None = None) -> dict:
    """读取 ~/.bicv/<CONFIG_NAME>，返回指定 system 的配置 dict。

    不传 system_name 时返回整个 systems 字典（让调用方选择）。
    """
    try:
        config = load_systems_config(CONFIG_NAME)
    except ServiceError as exc:
        sys.exit(
            f"[{CONFIG_NAME}] 无法加载配置：{exc}\n"
            f"请创建 ~/.bicv/{CONFIG_NAME}，结构见 docs/specs/config-spec.md"
        )

    systems = config["systems"]
    if system_name is None:
        return systems
    if system_name not in systems:
        names = ", ".join(systems.keys())
        sys.exit(
            f"[{CONFIG_NAME}] system {system_name!r} 不存在。可选：{names}"
        )
    return systems[system_name]


def main() -> None:
    cfg = get_system("<system-name>")
    base_url = cfg["url"]
    username = cfg["username"]
    # password 是敏感字段，避免直接打印或写入日志
    print(f"[{CONFIG_NAME}] connecting to {base_url} as {username}")


if __name__ == "__main__":
    main()