# bicv_skills

跨 **Claude Code** / **Codex** / **Hermes** 的 skill 能力包，通过 `npx skills` 一条命令安装到所有已安装的 agent。

## 这是什么

一套固定的 skill 能力（gerrit / jenkins / zentao / mysql 等），通过 [`npx skills`](https://github.com/vercel-labs/skills) 安装。`npx skills` 会自动检测本机已安装的 agent，把 skill 软链接（Windows 上是 directory junction）到各自的 skills 目录，改一次源码所有 agent 同步生效。

设计参考 [obra/superpowers](https://github.com/obra/Superpowers)，增加「凭据统一管理」能力。

## 包含的 skill

| skill | 用途 |
|---|---|
| `gerrit-restapi` | 通过 REST API 查询 / 操作 Gerrit |
| `jenkins-restapi` | 通过 REST API 操作 Jenkins |
| `zentao-restapi` | 通过 REST API 操作禅道 |
| `mysql` | MySQL SELECT / INSERT / UPDATE（禁止 DELETE/DROP/...） |

各 skill 自包含，配置解析模块 `system_config.py` 随 skill 一起安装，不依赖外部共享包。

## 安装

一条命令通装三平台，替换 `philosophy912/bicv_skills` 为你的实际路径即可：

```bash
npx skills add philosophy912/bicv_skills -y -g
```

- `-g` 安装到用户级（所有项目可用），不加则装到当前项目的 `.claude/skills/` 等。
- `npx skills` 自动检测本机已安装的 agent 并分别链接：

| agent | 全局 skills 路径 |
|---|---|
| Claude Code | `~/.claude/skills/<skill>/SKILL.md`（或 `$CLAUDE_CONFIG_DIR/skills`） |
| Codex | `~/.codex/skills/<skill>/SKILL.md`（或 `$CODEX_HOME/skills`） |
| Hermes | `~/.hermes/skills/<skill>/SKILL.md`（或 `$HERMES_HOME/skills`） |

> **Codex 兼容性提示：** `npx skills` 给 Codex 装的也是标准 `~/.codex/skills/<skill>/SKILL.md` 树，而非 Codex 原生的 `AGENTS.md` 约定。若你的 Codex 版本不扫描 `~/.codex/skills/`，装了也不会被加载，需要自行把 skill 内容并入 `AGENTS.md`。建议安装后在 Codex 里实测一次。Claude Code 与 Hermes 无此问题。

> **Windows：** `npx skills` 用 directory junction 链接，不需要管理员权限或 Developer Mode；若 junction 创建失败会自动 fallback 到复制。

> 替换 `philosophy912/bicv_skills` 为你的实际路径，例如 `your-org/bicv_skills`、本地 `file:///abs/path/to/bicv_skills`，或公司内网 GitLab 地址。

## 配置

各 skill 凭据统一存在 `~/.bicv/<skill-name>.json`，结构必须包含 `systems` 字典，支持多实例（多套 Gerrit、多套 Jenkins 等），CLI 通过 `--system <name>` 切换。详见 [config 规范](docs/config-spec.md)。

## 文档

- [config 规范](docs/config-spec.md)
- [如何新增 skill](docs/writing-a-skill.md)
- [测试指南](docs/testing-guide.md)（每个 skill 脚本覆盖率 ≥90%）
