# bicv_skills

跨 **Claude Code** / **Codex** / **Hermes** / **OpenClaw** 的 skill 能力包，通过 `npx skills` 一条命令安装到指定的 agent。

## 这是什么

一套固定的 skill 能力（gerrit / jenkins / zentao / mysql 等），通过 [`npx skills`](https://github.com/vercel-labs/skills) 安装。`npx skills` 把 skill 软链接（Windows 上是 directory junction）到指定 agent 的 skills 目录，改一次源码所有 agent 同步生效。

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

一条命令装到指定的四个 agent，替换 `philosophy912/bicv_skills` 为你的实际路径即可：

```bash
npx skills add philosophy912/bicv_skills -y -g \
  --agent claude-code codex hermes-agent openclaw
```

- `-g` 安装到用户级（所有项目可用），不加则装到当前项目的 `.claude/skills/` 等。
- `--agent` 显式限定只装到这四个 agent；本仓库只支持这四个，不装到其它 agent（如 Cursor / Gemini / Augment 等）。
- `npx skills` 会选定一个 agent 作为 universal 宿主（文件本体落在 `~/.agents/skills/<skill>/`），其余 agent 软链到同一份：

| agent（`--agent` 取值） | 落点 |
|---|---|
| `claude-code` | `~/.claude/skills/<skill>/` → 软链到 universal |
| `codex` | universal 宿主：`~/.agents/skills/<skill>/`（文件本体） |
| `hermes-agent` | `~/.hermes/skills/<skill>/` → 软链到 universal |
| `openclaw` | OpenClaw skills 目录 → 软链到 universal |

> **只装这四个 agent 的原理：** `--agent` 限定后，命令只往列出的 agent 装软链接，跳过其它。注意 `--agent` 取的是 `npx skills` 内部的 agent key（如 Hermes 是 `hermes-agent`，不是 `hermes`），写错会被拒并提示可用值。重跑同一条命令即可同步新增的 agent（命令运行那一刻才扫描，新增 agent 不会自动补装）。

> **Codex 兼容性提示：** `npx skills` 给 Codex 装的也是标准 `~/.codex/skills/<skill>/SKILL.md` 树，而非 Codex 原生的 `AGENTS.md` 约定。若你的 Codex 版本不扫描 `~/.codex/skills/`，装了也不会被加载，需要自行把 skill 内容并入 `AGENTS.md`。建议安装后在 Codex 里实测一次。Claude Code 与 Hermes 无此问题。

> **Windows：** `npx skills` 用 directory junction 链接，不需要管理员权限或 Developer Mode；若 junction 创建失败会自动 fallback 到复制。

> 替换 `philosophy912/bicv_skills` 为你的实际路径，例如 `your-org/bicv_skills`、本地 `file:///abs/path/to/bicv_skills`，或公司内网 GitLab 地址。

## 配置

各 skill 凭据统一存在 `~/.bicv/<skill-name>.json`，结构必须包含 `systems` 字典，支持多实例（多套 Gerrit、多套 Jenkins 等），CLI 通过 `--system <name>` 切换。详见 [config 规范](docs/config-spec.md)。

## 文档

- [config 规范](docs/config-spec.md)
- [如何新增 skill](docs/writing-a-skill.md)
- [测试指南](docs/testing-guide.md)（每个 skill 脚本覆盖率 ≥90%）
