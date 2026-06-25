# scm 失败模式清单

判定一个失败构建是否属于 **scm（拉代码）** 问题时，对照本清单。日志命中任一特征即归类
`scm`。本清单是**最小可用集合**，遇到新的 scm 失败形态请往这里追加，无需改代码。

> **口径**：scm 类只覆盖**拉源码环节本身失败**——即 git fetch / clone / checkout、svn
> update 等取源码动作报错。代码托管系统的 **API 鉴权失败**（如 `Gerrit response:
> Unauthorized`，发生在 code style 检查、调 Gerrit REST API 等非拉源码环节）**不算** scm，
> 归 `other`（见 other-failure-patterns.md 的「代码托管 API 认证失败」）。判定时注意结合
> 错误出现的上下文阶段，区分「拉不到代码」与「调 scm 系统的某个 API 鉴权没过」。

> scm 优先于 compile/other 判定。若一个构建同时有 scm 失败和编译失败，按本清单先命中
> scm 即归 `scm`（取第一个命中的分类）。

## git —— 认证失败（拉源码阶段）

- `fatal: could not read Username for 'http(s)://...'`：终端无交互凭据，CI 凭据未配置。
- `fatal: Authentication failed for 'http(s)://...'`
- `remote: Invalid username or token` / `remote: Support for password authentication was removed`
- `fatal: Access denied` / `403 Forbidden`（拉取阶段）
- `Permission denied (publickey)` / `Permission denied (publickey,gssapi-keyex,...)`
- `Host key verification failed.`

## git —— fetch / clone / checkout 异常

- `ERROR: Error fetching remote repo 'origin'`
- `hudson.plugins.git.GitException: ...`
- `Caused by: hudson.plugins.git.GitException`
- `fatal: unable to access 'http(s)://...': Could not resolve host` / `Failed to connect`
- `fatal: repository '...' not found`
- `fatal: ref refs/heads/... is not a symbolic ref` / `pathspec '...' did not match any file(s)`
- `error: Your local changes to the following files would be overwritten by checkout`（workspace 脏）
- `fatal: git fetch-pack: expected shallow list`（git 版本过低与服务端不兼容）

## repo sync —— 多仓库 fetch 失败（Android 源码 tree）

- `error: Cannot fetch <project>`：repo sync 拉某个子仓库失败。
- `error: Exited sync due to fetch errors`：repo sync 因 fetch 错误中止。
- `error: refs/... does not point to a valid object!`：本地引用损坏，fetch/unshallow 失败。
- `fatal: error in object: unshallow <sha>`：浅克隆展开失败。
- `fatal: needed single revision`：repo init/sync 找不到所需 revision。
- `.repo/manifest.xml: No such file or directory` / `IOError ... '.repo/...'`：repo 工作树损坏或
  manifest 缺失（repo init 未成功/数据被破坏），需删除 `.repo` 重新拉取。日志常伴
  「建议选择 DEL_REPO 删除 repo 进行拉取代码编译」。归 scm。
- 这类是真正的「拉源码失败」，归 scm。常见于 Android 整包编译 job（CHANGAN/JMC/BESTUNE/BAIC 等 main_compile）。

## SCM 工具链 / 节点环境缺失（构建依赖的 devops 工具链）

- `python3: can't open file '.../devops/scm/<x>.py': [Errno 2] No such file or directory`：job 依赖的
  SCM 工具脚本（devops/scm/app.py 等）在节点上缺失，编译/打包 job 一启动就因找不到 SCM 工具
  而失败。
- `failed to locate pyvenv.cfg`：节点上 Python 虚拟环境（venv）配置缺失——SCM/构建工具链依赖的
  venv 没装好，job 在第一步（Windows batch）就失败，常与 devops/scm 脚本缺失同源、同节点。
- 这类归 scm（SCM 工具链问题），常见于 Windows 节点的 `MCU_COMPILE_*` 等 job。
- 注意：`SCM 'hudson.scm.NullSCM' is not of type GitSCM` 单独出现**不算** scm——很多 job 正常用
  COCSCM/repo 脚本拉码，Jenkins 层面配 NullSCM 是正常配置；只有当伴随 devops/scm 脚本缺失、
  pyvenv.cfg 缺失或 repo/git fetch 错误时才归 scm。

## SCM 流程项目匹配失败（SCM 打包/分发 job）

- `执行失败: 未匹配到 qa_projects 条目: host=..., project=..., branch=...`：SCM_PACKAGE 等
  SCM 流程 job 在处理 Gerrit 触发的 patchset 时，找不到 qa_projects 的匹配配置，打包/分发
  流程失败。这类是 SCM 流程配置问题，归 scm。
- 此类常伴随 `ERROR Gerrit response: Unauthorized`（调 Gerrit API 拉项目信息时鉴权失败），
  但根因是项目匹配/SCM 流程，归 scm；区别于纯 Gerrit API 鉴权失败（见 other-failure-patterns.md
  的「代码托管 API 认证失败」）。
- 匹配提示：Windows 节点日志里的中文（「未匹配到」「项目」等）常是 GBK 字节、被容错解码成
  乱码，判定时以 ASCII 关键字 `qa_projects` 为准。

## SCM 维护 job 访问发布产物库失败（SCM_CLEAN_BINARY 等）

- `执行失败: [WinError 3] 系统找不到指定的路径: '\\<host>\SWRelease\...'` / `\\<host>\COCRelease\...`：
  `SCM_CLEAN_BINARY` 等 SCM 维护 job 在清理发布产物（SWRelease/COCRelease 目录）时，访问
  SCM 管理的发布库 NAS 路径失败。这类 job 是 SCM 维护流程的一部分，归 scm（scm 需排查发布库
  可达性/清理逻辑）。
- 限定：仅当 job 属 SCM 维护类（如 `SCM_CLEAN_BINARY`）且访问的是 `SWRelease`/`COCRelease`
  等 SCM 发布产物路径时归 scm；普通编译 job 访问 NAS 失败不在此列。

## git —— submodule / lfs

- `fatal: clone of '...' into submodule path '...' failed`
- `No submodule mapping found in .gitmodules for path '...'`
- `git submodule update failed`
- `Encountered N file(s) that should have been pointers, but weren't`（git-lfs 未安装/未初始化）
- `batch response: ... LFS ...`

## svn

- `svn: E170001: Authentication required`（认证失败）
- `svn: E170013: ... authorization failed`
- `svn: E175002: ... connection timed out` / `svn: E175002: Server sent unexpected return value`
- `svn: E160013: ... path not found`（URL/revision 不存在）
- `svn: E155036: ...`（working copy 锁/冲突）

## 通用特征

- 失败发生在 `Cloning the remote Git repository` / `Fetching upstream changes` /
  `Checking out Revision ...` / `> git fetch` / `> git checkout` 等 scm 步骤之后、
  编译步骤之前。
- 构建在数秒内失败（duration 很短，往往 < 30s），且日志末尾停在 scm 相关行——典型「根本
  没拉到代码」。

## 不是 scm（应归别的类）

- 拉代码成功，失败出现在 `mvn` / `make` / `gcc` / `npm` / `javac` 等编译命令 → `compile`。
- 拉代码成功，失败是 `No space left on device` / `Cannot allocate memory` / 磁盘满 /
  依赖下载超时 → `other`。
- `Gerrit response: Unauthorized` / Gerrit REST API 鉴权失败、但发生在 code style 检查、
  webhook 回调、调 Gerrit API 做合规检查等**非拉源码环节** → `other`（代码托管 API 认证
  失败）。这类是 scm 系统的 API 凭据问题，不是「拉不到代码」，不算 scm。
