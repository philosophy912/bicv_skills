# 其它失败模式清单

当 scm 与 compile 均不命中时，对照本清单判定是否属于 **other**（环境/资源/依赖/超时等）。
命中任一即归类 `other`。本清单是最小可用集合，遇到新形态请往这里追加。

## 资源耗尽

- `No space left on device`
- `Cannot allocate memory` / `Out of memory` / `OOMKilled` / `std::bad_alloc`
- `fatal: Out of memory, calloc failed`
- `Cannot create ... Disk quota exceeded`
- `Inode ... : No space left on device`

## 网络与依赖下载（构建期，非 scm）

- `Could not transfer artifact ... from/to ...`（maven 仓库拉依赖失败，区分于拉源码）
- `Failed to execute goal ...: Could not resolve dependencies`
- `npm ERR! network ...` / `npm ERR! ... ECONNREFUSED` / `npm ERR! ... ETIMEDOUT`
- `pip._vendor.urllib3...: ... timed out` / `WARNING: Retrying ... after connection broken`
- `curl: (6) Could not resolve host`（发生在依赖下载步骤，非 git fetch）

## 超时 / 中断

- 构建状态 `ABORTED`（被人为停止或超时插件中断）
- `Build timed out` / `Timeout exceeded`
- `Finished: ABORTED`

## 代码托管 API 认证失败（非拉源码环节，且非 SCM 流程匹配失败）

- `Gerrit response: Unauthorized` / Gerrit REST API 返回 401：调用代码托管系统的 API 做合规
  检查、code style 校验、webhook 回调等时鉴权未通过（token/凭据失效或权限不足）。
- 此类发生在**非拉源码环节**（不是 git fetch/checkout），不算 scm，归 `other`。常见于
  `SCM_GERRIT_*` 等 job。
- **例外**：若同一日志里还出现 `未匹配到 qa_projects 条目`（SCM_PACKAGE 等 SCM 流程 job 的
  项目匹配失败），则整体归 `scm`（见 scm-failure-patterns.md 的「SCM 流程项目匹配失败」）——
  根因是 SCM 流程配置，不是单纯 API 鉴权。

## 环境与配置

- `command not found: ...`（构建工具链缺失）
- `env: ...: No such file or directory`
- `java: command not found` / `python: command not found`
- `ERROR: Tool ... not found`（Jenkins tool 未配置）
- `java.lang.UnsupportedClassVersionError`（JDK 版本不符）
- `Agent ... was marked offline` / `node ... offline`

## 测试失败（非编译失败）

- 单测断言失败、`Tests run: X, Failures: Y`（maven surefire）
- `pytest ... failed` / `AssertionError`（在测试阶段，非编译阶段）
- 此类通常构建状态为 `UNSTABLE` 或 `FAILURE`，但代码已编译通过——归 `other`，不归
  `compile`。

## 通用特征

- 拉代码成功、编译也成功（或根本没到编译），失败在测试/部署/资源/环境环节。
- 日志末尾的错误不属于 scm 也无明显编译错误。
