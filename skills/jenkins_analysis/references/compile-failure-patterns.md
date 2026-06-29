# 编译失败模式清单

当 scm 判定不命中时，对照本清单判定是否属于 **compile（编译/构建本身报错）**。命中任一
特征即归类 `compile`。本清单是最小可用集合，遇到新形态请往这里追加。

> 仅当拉代码阶段明显成功、失败发生在编译/构建步骤时才归此类。

## C/C++

- `error: ...`（gcc/g++/clang 行首的 `error:`，如 `error: expected ';'`）
- `make: *** [...] Error 1` / `make: *** [Makefile:...] Error 2`
- `ninja: build stopped: subcommand failed.`
- `undefined reference to ...`（链接错误）
- `fatal error: ...: No such file or directory`（头文件缺失——注意与 scm 区分：此处是编译
  阶段找不到头文件，而非拉代码失败）

## Java

- `BUILD FAILURE`（maven）
- `[ERROR] ...`（maven 编译错误）
- `error: ... `（javac）
- `javac: ...`
- `Compilation failure` / `Failed to execute goal org.apache.maven...:compile`

## JavaScript / TypeScript / 前端

- `npm ERR! ...`
- `SyntaxError: ...`（构建期）
- `error TS1234: ...`（tsc）
- `Failed to compile.`（webpack/vite）
- `Module not found: Error: Can't resolve '...'`（构建期模块缺失，非安装期）

## Python 打包/构建

- `error: ...`（setuptools/build）
- `error: command 'gcc' failed with exit status 1`（编译 C 扩展）
- `error: ... is not a valid Python ...`

## 通用特征

- 失败发生在 `mvn` / `make` / `gcc` / `g++` / `clang` / `npm run build` / `tsc` / `cargo
  build` / `cmake` 等构建命令之后。
- 构建跑了较长时间才失败（已过 scm 阶段，进入实际编译）。
- 日志含明确的「error」行和退出码 `Error N` / `exit code N`（N != 0），且位于编译步骤。
