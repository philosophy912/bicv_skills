# 测试指南

每个 skill 的脚本必须有单元测试，**行覆盖率 ≥ 90%** 是硬性要求。新增/修改脚本时必须同步补测试，覆盖率不达标视为未完成。

## 硬性指标

| 对象 | 指标 |
|---|---|
| 每个 skill 的主脚本（`scripts/<xxx>_api.py` 等） | 行覆盖率 **≥ 90%**，含分支覆盖 |
| `system_config.py`（各 skill 各持一份） | 由全量测试合并覆盖，不单独考核单个 skill |

`system_config.py` 是公共依赖底座，每个 skill 只用到其中一部分功能。因此不把它计入单个 skill 的覆盖率指标——否则会被未用到的分支拉低。它的整体覆盖率由跑全部 skill 测试合并保证。

## 运行测试

### 单个 skill（开发时最常用）

```bash
cd skills/<skill-name>
python3 -m pytest --cov=<module> --cov-report=term-missing -q
```

`<module>` 是该 skill 主脚本的模块名（不含 `.py`）：

| skill | 命令 |
|---|---|
| gerrit-restapi | `python3 -m pytest --cov=gerrit_api --cov-report=term-missing -q` |
| jenkins-restapi | `python3 -m pytest --cov=jenkins_api --cov-report=term-missing -q` |
| zentao-restapi | `python3 -m pytest --cov=zentao_api --cov-report=term-missing -q` |
| mysql | `python3 -m pytest --cov=mysql_query --cov-report=term-missing -q` |

> **只加 `--cov=<module>`，不要加 `--cov=system_config`**，否则 system_config 未用分支会拉低指标。

### 全量（提交前 / CI）

```bash
python3 -m pytest
```

`pyproject.toml` 已配置 `testpaths = ["skills"]`，会自动发现所有 skill 的 `tests/`。`fail_under = 90` 保证合并覆盖率低于 90% 时命令以非零退出码失败。

### 看未覆盖行

```bash
cd skills/<skill-name>
python3 -m pytest --cov=<module> --cov-report=term-missing
# Missing 列就是未覆盖的行号
```

## 测试目录结构

```
skills/<skill-name>/
├── scripts/
│   ├── <xxx>_api.py        # 被测脚本
│   └── system_config.py    # 同目录依赖，运行时自动可 import
├── conftest.py             # 把 scripts/ 加入 sys.path（放 skill 根目录）
└── tests/
    └── test_<xxx>_api.py   # 测试
```

每个 skill 的 `conftest.py` 固定写法（放在 **skill 根目录**，即 `skills/<skill-name>/conftest.py`）：

```python
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent

# scripts/ directory for <module> + system_config modules
sys.path.insert(0, str(_root / "scripts"))
```

这样测试里可以直接 `import <xxx>_api` 和 `from system_config import ...`。

> conftest 放在 skill 根目录而非 `tests/` 下：因为 `sys.path` 注入的是 `_root / "scripts"`，放在 `tests/` 里 `_root` 会指向 `tests/` 而找不到 `scripts/`。pytest 会自动发现 skill 根目录的 conftest。

## 测试风格规范

参考 `skills/zentao-restapi/tests/test_zentao_api.py`（最完整的样例）。

### 1. 永远 mock，不碰真实环境

- **HTTP**：`mock.patch("urllib.request.urlopen")`，构造 context manager：
  ```python
  with mock.patch("urllib.request.urlopen") as m:
      cm = mock.MagicMock()
      cm.read.return_value = b'{"status": "success"}'
      cm.__enter__.return_value = cm
      m.return_value = cm
      result = xxx_api.request_json("GET", "http://mock", "/path")
  ```
- **数据库**：mock `mysql.connector.connect`，绝不连真实 MySQL。
- **配置文件**：cmd_* 内部调 `_target(args)` 会读 `~/.bicv/<skill>.json`，用
  `mock.patch("<module>._target", return_value=Target(...))` 绕过。
- **交互确认**：危险操作的 `input()` 用 `mock.patch("builtins.input", return_value="y"/"n")`。

### 2. 直接构造 args 调 cmd_*

```python
import argparse
from unittest import mock

def test_query_changes(cmd_mock):
    args = argparse.Namespace(query="status:open", limit=10)
    with mock.patch("gerrit_api._target", return_value=MOCK_TARGET), \
         mock.patch("gerrit_api.request_json", return_value=[{"_number": 1, "subject": "x"}]):
        rc = gerrit_api.cmd_query_changes(args)
    assert rc == 0
```

### 3. 用 capsys 断言输出

```python
def test_list_jobs(capsys):
    ...
    captured = capsys.readouterr()
    assert "Found 2 jobs" in captured.out
```

### 4. 分组用 class

```python
class TestRequestJson:
    def test_get_returns_parsed_json(self): ...
    def test_http_error_raises(self): ...
```

### 5. 每个分支都要有用例

有 `if/else` 的函数，两条路径都要测。`--cov-report=term-missing` 报出来的 Missing 行就是欠的用例。

## 覆盖率达标技巧

1. **先跑基线**，看 Missing 行号，针对性补用例，别盲目堆。
2. **helper 函数全测**：`build_url`/`request_json`/`validate_sql` 等是所有 cmd_* 的基础，先 100% 覆盖。
3. **cmd_* 测主路径 + 异常路径**：正常返回、空结果、抛 ServiceError。
4. **build_parser 只验注册**：`parse_args` 不报错即可，handler 逻辑由 cmd_* 测试覆盖，避免重复。
5. **main() 测两条**：成功返回 0、捕获 ServiceError 返回非零。
6. **不要为凑覆盖率写空断言**——每个用例必须有明确断言。`assert True` 这类会被 review 打回。

## 跑测试前确认环境

```bash
python3 -m pytest --version        # 需要 pytest
python3 -c "import pytest_cov"     # 需要 pytest-cov
python3 -c "import mysql.connector"  # mysql skill 需要 mysql-connector-python
```

缺失则 `pip install pytest pytest-cov mysql-connector-python`。
