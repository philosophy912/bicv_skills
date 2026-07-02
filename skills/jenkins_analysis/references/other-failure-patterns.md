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

## ⚠️ Gerrit Trigger 噪声（忽略，不参与分类）

- `ERROR Gerrit response: Unauthorized`：Jenkins Gerrit Trigger 插件在**每次构建**（无论成功
  还是失败）结束后回写 Gerrit 时都会打印此行，是固定噪声。**一律忽略**——既不归 `other`，也
  不当作任何分类信号。判定时跳过这行，按日志中其余真实错误特征归类（git/mvn/资源/环境等）。
- 若忽略该行后日志再无其它可判错误、构建却失败：归 `unknown`，evidence 注明「仅剩 Gerrit
  Trigger 噪声行，未见真实失败原因，需人工复核日志」。
- **不要**因为本行出现在 `SCM_GERRIT_*` 等 job 里就判 `other`——job 名不改变这行的噪声性质。

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

## 代码规范检查不合规（code style / 提交规范）

- `提交不符合规范无需codeview` / `commit message does not match pattern`：`SCM_GERRIT_CODE_STYLE_CHECK`
  等 code style 检查 job **主动拒绝**了不合规提交（提交信息/代码风格不符规范），是检查机制的预期
  结果而非故障。Jenkins 标 FAILURE（Text Finder 命中模式），归 `other`。
- **区别于 SCM 工具脚本崩溃**：若同一 job 日志里出现 `main.py |FUNC: run` + `执行失败: <Python 异常>`
  （`not enough values to unpack` 等），那是 SCM 工具脚本自身崩了，归 `scm`（见
  scm-failure-patterns.md 的「SCM 工具脚本运行时异常」）。两者根因不同，判定时**先查 main.py 运行
  时异常 → scm，再查 code style 不合规 → other**。
- `ERROR Gerrit response: Unauthorized` 是 trigger 噪声，忽略（见上节）。

## 通用特征

- 拉代码成功、编译也成功（或根本没到编译），失败在测试/部署/资源/环境环节。
- 日志末尾的错误不属于 scm 也无明显编译错误。
