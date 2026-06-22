# bicv_skills 跨平台 Skill 插件系统 — 设计与实施计划

> ⚠️ **本文档为历史决策记录**。当前状态：v0.7 计划中设想的「setup 部署工具」已砍掉，项目仅以 plugin marketplace 形式分发，用户直接通过 `~/.bicv/<skill>.json` 手动配置凭据。最新规范见 [config 规范](../specs/config-spec.md)。
>
> 状态：v0.7 已定稿 · 日期：2026-06-22
> v0.2 变更：存储统一到 `~/.bicv/` 根目录（原 per-skill `config.local.json` 方案废弃）。
> v0.3 变更：凭据明文存储（自用环境），不再预留 keychain/env，简化实现。
> v0.4 变更：部署范围（scope）改为安装时让用户选 user / project（参考 superpowers）。
> v0.5 变更：确认 Codex 也有官方 plugin marketplace；新增「部署机制」决策（G）；一键安装补 Windows 方案。
> v0.6 变更：修正 Claude 结论——Claude Code 提供 `claude plugin marketplace` 等非交互 CLI + `settings.json` 直写，两端 marketplace 均可全自动；G 定为 G1。
> v0.7 变更：C（Python）/ E（bicv_skills）/ F（砍掉）敲定，计划定稿，进入 Phase 0。

---

## 一、项目目标

做一套**固定的 skill 能力包**，能够**一键安装到 Claude Code 和 Codex 两个平台**，并在安装时**交互式完成各 skill 所需的凭据配置**（gerrit / jenkins / zentao / mysql 等的用户名、密码、token、地址）。

一句话概括：

> **一个工具，跑一次 → 把 skill 部署到 Claude + Codex，并引导填好每个 skill 的凭据，统一存到 `~/.bicv/`。**

---

## 二、核心定位与参考

### 参考对象：[obra/superpowers](https://github.com/obra/Superpowers)

借鉴它的三层思想：

| 层 | 职责 | 说明 |
|---|---|---|
| **能力核心** | `skills/` 目录 | 与平台无关的 skill 本体，每个 skill 一个目录，入口 `SKILL.md` |
| **平台适配** | 部署到 Claude / Codex 的差异处理 | Claude 走 skill 目录发现；Codex 走 `~/.agents/skills/` 目录扫描 |
| **安装工具** | `setup` 命令 | **部署 + 配置一体化**（相对 superpowers 的增量：自动部署 + 凭据向导 + 统一家目录） |

### 关键差异（我们的增量）

- superpowers 不涉及凭据；**我们要解决 skill 需要账号密码的问题**
- superpowers 的 Codex 安装靠用户手动 clone+软链；**我们用工具自动完成两端部署**
- superpowers 没有「家目录」概念；**我们用 `~/.bicv/` 统一收口所有持久化数据**

---

## 三、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                      setup CLI（入口）                         │
│          bicv-setup install / deploy / config / list          │
└──────────┬───────────────────────────────────┬───────────────┘
           │                                   │
   ┌───────▼────────┐                 ┌────────▼────────┐
   │  部署适配层     │                 │  配置向导层      │
   │  (deployer)    │                 │  (wizard)       │
   │                │                 │                 │
   │ • Claude 适配  │                 │ • 扫描 config   │
   │ • Codex 适配   │                 │   .spec         │
   │ • 软链到平台    │                 │ • 交互收集凭据   │
   └───────┬────────┘                 │ • 写凭据到 ~/.bicv│
           │                          └────────┬────────┘
           │                                   │
           │      ┌────────────────────────────┘
           │      │  读写
           ▼      ▼
   ┌──────────────────────────────────────────┐
   │      ~/.bicv/（统一存储根目录）           │
   │                                          │
   │  repo/          ← skill 仓库 clone（源）  │
   │  credentials/   ← 各 skill 凭据           │
   │  config.toml    ← 全局配置                │
   │  state.json     ← 部署状态                │
   └──────────────────────────────────────────┘
           │
           │ 从 repo/ 软链
           ▼
   ┌──────────────────────────────────────────┐
   │  ~/.claude/skills/<name>  （Claude 发现）  │
   │  ~/.agents/skills/<name>  （Codex 发现）   │
   └──────────────────────────────────────────┘
```

---

## 四、关键设计

### 4.1 `~/.bicv/` 统一存储根目录

**这是整个系统的家目录**，所有持久化数据都在这里（仓库本身保持纯净，不含任何本地凭据）：

```
~/.bicv/
├── repo/                       # skill 仓库的本地 clone（唯一源）
│   ├── skills/
│   ├── setup/
│   └── ...
├── credentials/                # 各 skill 的凭据（一个 skill 一个文件）
│   ├── gerrit.json
│   ├── jenkins.json
│   └── zentao.json
├── config.toml                 # 全局配置（部署目标、偏好等）
├── state.json                  # 部署状态（哪些 skill 装到了哪个平台、版本）
└── logs/                       # 运行日志（可选）
```

**定位约定**：通过环境变量 `BICV_HOME`（默认 `~/.bicv`）定位。

- setup 工具读写 `$BICV_HOME`
- skill 内的脚本（如 `gerrit_api.py`）通过 `$BICV_HOME/credentials/<skill>.json` 读取自己的凭据
- 这样 skill 被软链到各平台后，脚本仍能凭约定找到凭据（不依赖相对路径）

### 4.2 能力核心层（仓库内的 `skills/`）

每个 skill 一个目录，约定结构（**仓库内，不含本地凭据**）：

```
skills/<skill-name>/
├── SKILL.md              # 入口：frontmatter（name/description/triggers）+ 规则正文
├── config.spec.toml      # 【关键】声明本 skill 需要哪些配置项（见 4.3）
├── scripts/              # skill 调用的脚本（如 gerrit_api.py，读 $BICV_HOME/credentials）
└── references/           # 补充文档（按需）
```

- `SKILL.md` 是平台发现 skill 的入口（Claude 和 Codex 都扫 frontmatter）
- 不需要凭据的 skill 可以没有 `config.spec.toml`
- **仓库里不再有任何 `config.local.json`** —— 凭据全部在 `~/.bicv/credentials/`

### 4.3 配置声明规范（`config.spec.toml`）— 系统的地基

setup 之所以能"根据 skill 自动配置"，靠的是每个 skill **声明自己需要什么**。规范示例（`skills/gerrit/config.spec.toml`）：

```yaml
# skills/gerrit/config.spec.toml
skill: gerrit
title: Gerrit 代码审查
fields:
  - key: base_url
    label: Gerrit 服务地址
    type: string
    required: true
    placeholder: "https://gerrit.example.com"
  - key: username
    label: 用户名
    type: string
    required: true
  - key: password
    label: HTTP 密码 / Token
    type: secret        # secret：输入时隐藏，存储时脱敏展示
    required: true
  - key: verify_ssl
    label: 是否校验 SSL 证书
    type: bool
    default: true
```

- setup 扫描所有 `config.spec.toml`，据此**动态生成交互式问卷**
- 字段类型：`string` / `secret` / `int` / `bool` / `enum` / `list`
- 字段属性：`default` / `placeholder` / `required` / `label`（给用户看的中文说明）

### 4.4 凭据存储与安全

**存储位置**：`~/.bicv/credentials/<skill>.json`（一个 skill 一个文件）：

```json
// ~/.bicv/credentials/gerrit.json
{
  "base_url": "https://gerrit.example.com",
  "username": "lizhe",
  "password": "*****",
  "verify_ssl": true
}
```

- **明文 JSON 存储**（自用环境，不引入 keychain / env 等额外复杂度）
- `~/.bicv/` 整个目录天然在用户家目录，**不会进 git**（仓库根本不管它）
- skill 脚本通过 `$BICV_HOME/credentials/<skill>.json` 读取（4.1 约定）
- `type: secret` 字段仅影响**输入时隐藏显示**和 `list` 时的**脱敏展示**，存储仍是明文

### 4.5 平台部署适配层

**两个平台都已有官方 plugin marketplace**（命令高度对称，参考 superpowers 当前做法）：

| 平台 | 注册 marketplace | 安装插件 | 能否被 setup 脚本自动执行 |
|---|---|---|---|
| **Claude Code** | `claude plugin marketplace add <repo>`（非交互 CLI） | 写 `settings.json` 的 `enabledPlugins` 或 `/plugin install` | ✅ 有非交互 CLI `claude plugin marketplace ...`，可脚本化 |
| **Codex CLI** | `codex plugin marketplace add <src>` | `codex plugin install <name>` | ✅ 真正的 CLI 命令，可脚本化 |

仓库内提供两端的 marketplace 声明文件（若选 marketplace 机制）：
- Claude：`.claude-plugin/marketplace.json` + 每个 plugin 的 `.claude-plugin/plugin.json`
- Codex：`.agents/plugins/marketplace.json`（Codex 官方约定路径），并需用户 `config.toml` 里 `[features] plugins = true`

**部署机制三种选择**（⚠️ 决策 G，建议 **G1**）：
- **G1 两端 marketplace**（推荐、最规范、两端全自动、可被市场收录）：仓库同时提供 `.claude-plugin/marketplace.json` 与 `.agents/plugins/marketplace.json`
  - Codex：setup 自动 `codex plugin marketplace add` + `codex plugin install`
  - Claude：setup 自动 `claude plugin marketplace add <repo> --scope user|project`；也可直接写 `.claude/settings.json` 的 `extraKnownMarketplaces` + `enabledPlugins`（项目级可随仓库共享给团队）
- **G2 两端软链**（最简单）：软链 `~/.bicv/repo/skills/*` 到 `~/.claude/skills/` 与 `~/.agents/skills/`，不走 marketplace；只覆盖 skills
- **G3 混合**：Codex 走 marketplace，Claude 走软链

**部署范围（scope）**：两端 CLI 都支持 `--scope`，安装时让用户选（参考 superpowers），不写死：
- `user`（默认）：全局生效，装一次到处可用
- `project`：仅当前项目；Claude 通过 `--scope project` 写入项目 `.claude/settings.json`（可随 git 共享给团队），Codex 同理

软链相关：源统一在 `~/.bicv/repo/`，`update` = `git pull`，平台侧自动跟随；幂等；自动建目录。

### 4.6 setup 工具（部署 + 配置一体化）

**技术栈**：Python（与现有 `.gitignore` 一致，跨平台、易读 spec）。⚠️ **开放决策 C — 是否同意用 Python？**（备选：纯 shell / Node）

**CLI 设计**：

```bash
# 一键：clone 仓库到 ~/.bicv/repo + 部署到两端 + 配置凭据（主力命令）
bicv-setup install [--scope user|project]

# 仅部署（不问凭据）
bicv-setup deploy [--target claude|codex|all] [--scope user|project]

# 仅配置/重配凭据
bicv-setup config [--skill gerrit]

# 查看各 skill 的部署 + 配置状态
bicv-setup list

# 更新（git pull ~/.bicv/repo，平台侧软链自动跟随，保留已有凭据）
bicv-setup update

# 卸载
bicv-setup uninstall [--target claude|codex|all]
```

**`install` 的执行流程**：

```
1. 准备家目录：确保 ~/.bicv/ 及子目录存在
2. 获取源：若 ~/.bicv/repo 不存在则 clone；存在则提示是否 update
   （开发模式 --dev /path/to/local/clone：从本地 clone 软链，方便开发）
3. 检测环境：已装 Claude Code？Codex？→ 确定部署目标
4. 确定 scope：交互询问部署到「用户级」还是「项目级」（默认 user；`--scope` 可跳过询问）
5. 部署：对每个目标平台，按 scope 把 repo/skills/* 软链到对应目录
6. 扫描所有 config.spec.toml，汇总需要配置的字段
7. 交互式逐 skill 收集凭据（已有 credentials/<skill>.json 的默认跳过/提示覆盖）
8. 写入 ~/.bicv/credentials/<skill>.json
9. 记录 state.json，输出汇总：哪些 skill 已部署、哪些已配置、哪些待配置
```

**非交互模式**（CI / 批量）：`--non-interactive --config-file preset.yaml`，从预设文件读凭据。

**安装方式**（用户怎么拿到 `bicv-setup`）：

```bash
# 方式一：一键脚本（类似 oh-my-claude-code）
#   Linux / macOS（bash）：
curl -fsSL https://raw.githubusercontent.com/<you>/bicv_skills/main/setup/install.sh | bash

#   Windows（PowerShell）：
irm https://raw.githubusercontent.com/<you>/bicv_skills/main/setup/install.ps1 | iex

# 方式二：clone 后直接跑（所有平台通用）
git clone https://github.com/<you>/bicv_skills.git
cd bicv_skills && python -m setup install
```

- 一键脚本只做「拉取仓库 + 启动 `python -m setup install`」的引导，核心逻辑全在跨平台的 Python 里
- 提供**两个引导脚本**：`install.sh`（bash）+ `install.ps1`（PowerShell），覆盖 Linux / macOS / Windows
- ⚠️ **开放决策 D — 已基本定**：一键保留（Linux/macOS 用 curl，Windows 用 PowerShell `irm|iex`），同时保留 clone 方式

---

## 五、目录结构（仓库内，完整）

```
bicv_skills/                        # 仓库（纯净，无任何本地凭据）
├── skills/                         # 能力核心（跨平台共享）
│   ├── gerrit/
│   │   ├── SKILL.md
│   │   ├── config.spec.toml
│   │   ├── scripts/gerrit_api.py   # 读 $BICV_HOME/credentials/gerrit.json
│   │   └── references/
│   ├── jenkins/
│   ├── zentao/
│   └── _template/                  # 新 skill 模板（含 config.spec 样例）
│
├── setup/                          # 安装 + 配置工具
│   ├── __init__.py
│   ├── cli.py                      # CLI 入口（argparse）
│   ├── home.py                     # ~/.bicv/ 家目录管理（BICV_HOME）
│   ├── deployer.py                 # 平台部署（Claude/Codex adapter）
│   ├── wizard.py                   # 交互式配置向导
│   ├── spec.py                     # 解析 config.spec.toml
│   ├── store.py                    # 读写 ~/.bicv/credentials/（含权限处理）
│   ├── install.sh                  # 一键安装引导（Linux/macOS：curl|bash）
│   ├── install.ps1                 # 一键安装引导（Windows：irm|iex）
│   └── requirements.txt            # pyyaml 等
│
├── docs/
│   ├── plans/plugin-system-plan.md # 本文档
│   └── writing-a-skill.md          # 如何新增 skill（含 config.spec 规范）
│
├── tests/                          # setup 工具的测试
├── README.md
├── .gitignore
└── LICENSE
```

> 注：凭据、state、本地 clone 都在 `~/.bicv/`，**不在仓库里**；仓库始终保持可分发、可提交的纯净状态。

---

## 六、实施阶段（里程碑）

每个阶段交付可验证的东西，逐步搭起来。

### Phase 0 — 脚手架与规范（基础）
- 建立目录结构（`skills/`、`setup/`、`docs/`、`tests/`）
- 定义 `config.spec.toml` 规范（字段类型、属性）
- 写 `skills/_template/` skill 模板
- 定义 `~/.bicv/` 目录布局与 `BICV_HOME` 约定
- **验证**：规范文档 + 模板可被人理解

### Phase 1 — 家目录与配置向导（核心增量）
- `setup/home.py`：`~/.bicv/` 初始化、`BICV_HOME` 定位
- `setup/spec.py`：解析 `config.spec.toml`
- `setup/wizard.py`：交互式收集凭据（secret 字段隐藏输入）
- `setup/store.py`：读写 `~/.bicv/credentials/<skill>.json`（权限 600/700）
- **验证**：给一个假 skill 带 spec，跑 `bicv-setup config` 能正确交互并写入 `~/.bicv/credentials/`

### Phase 2 — 平台部署层
- `setup/deployer.py`：Claude adapter（软链到 `~/.claude/skills/`）
- Codex adapter（软链到 `~/.agents/skills/`）
- 平台检测（是否安装了 Claude Code / Codex）
- clone 仓库到 `~/.bicv/repo/`（含 `--dev` 本地源模式）
- 幂等：重复部署不报错
- **验证**：部署后，Claude Code 和 Codex 都能发现并触发该 skill

### Phase 3 — 一体化 CLI
- `setup/cli.py`：串起 deploy + config（`install` 命令）
- `list` / `update` / `uninstall` 子命令
- 非交互模式（`--non-interactive`）
- `state.json` 记录部署状态
- **验证**：一条 `bicv-setup install` 端到端跑通

### Phase 4 — 第一个真实 skill 端到端验证
- 用 **gerrit** skill 做样板（带 `config.spec.toml` + `scripts/gerrit_api.py`）
- 部署到 Claude + Codex，配置凭据，验证两个平台都能实际调通 gerrit
- **验证**：真实端到端可用，作为后续 skill 的参照

### Phase 5 — 文档与测试
- `README.md`：安装与使用说明
- `docs/writing-a-skill.md`：新增 skill 指南
- `tests/`：spec 解析、向导、deployer 的单测
- 一键 `install.sh` 脚本（如决策 D 选要）

---

## 七、待你决策的开放问题（汇总）

| 编号 | 问题 | 我的建议 | 状态 |
|---|---|---|---|
| ✅ | 凭据/数据存储位置 | 统一到 `~/.bicv/` | **已定（v0.2）** |
| ✅ A | 凭据存储方式 | 明文 JSON（自用环境） | **已定（v0.3）** |
| ✅ B | 部署范围（scope） | 安装时让用户选 user / project | **已定（v0.4）** |
| ✅ C | 技术栈 | Python >= 3.13（内置 tomllib） | **已定** |
| ✅ D | 一键安装 | curl（Linux/macOS）+ PowerShell `irm\|iex`（Windows）+ clone | **已定（v0.5）** |
| ✅ E | 项目正式名称 | `bicv_skills` | **已定** |
| ✂️ F | session-start hook | **首版不做（砍掉）**，将来需要再评估 | **已定（砍）** |
| ✅ G | 部署机制 | **G1 两端 marketplace**（两端都有非交互 CLI，全自动） | **已定（v0.6）** |

---

## 八、风险与取舍

1. **Codex 的 skill 发现机制可能随版本变化** — `~/.agents/skills/` 是当前观察到的约定。**对策**：adapter 隔离，变化只改一处。

2. **凭据目录被误共享/备份** — `~/.bicv/credentials/` 含明文凭据（自用环境可接受）。**对策**：该目录不进 git（仓库无关它）；若整机备份/云同步，由用户自行注意。

3. **跨平台软链** — Windows 上 symlink 需要管理员权限或开发者模式。**对策**：Windows 下回退到拷贝 + `state.json` 记录映射用于 update。

4. **`~/.bicv/repo` 与用户已有 clone 冲突** — 开发者可能已有仓库 clone。**对策**：`--dev <path>` 模式从本地源软链，不重复 clone。

5. **scope 蔓延** — 容易顺手做 plugin 市场、session hook 等大功能。**对策**：严格按 Phase 推进，F 类增强后置。
6. **Claude plugin CLI 需较新版本** — `claude plugin marketplace` 等非交互子命令要求较新的 Claude Code。**对策**：setup 检测版本，旧版回退为直接写 `.claude/settings.json` 的 `extraKnownMarketplaces` + `enabledPlugins`，或提示用户在会话内 `/plugin install`。

---

## 九、下一步

所有开放决策已敲定（v0.7 定稿）。进入 **Phase 0**：搭脚手架 + 定规范。
