# bicv_skills

跨 **Claude Code** 和 **Codex** 的 skill 能力包，通过 plugin marketplace 安装。

## 这是什么

一套固定的 skill 能力（gerrit / jenkins / zentao / mysql 等），打包成一个 plugin，可通过 `claude plugin marketplace add` 或 `codex plugin marketplace add` 安装到任一平台。

设计参考 [obra/superpowers](https://github.com/obra/Superpowers)，增加「凭据统一管理」能力。

## 包含的 skill

| skill | 用途 |
|---|---|
| `gerrit-restapi` | 通过 REST API 查询 / 操作 Gerrit |
| `jenkins-restapi` | 通过 REST API 操作 Jenkins |
| `zentao-restapi` | 通过 REST API 操作禅道 |
| `mysql` | MySQL SELECT / INSERT / UPDATE（禁止 DELETE/DROP/...） |

## 安装

按平台分开装,同一个仓库装一次就够。

### Claude Code

Claude Code 用 `.claude-plugin/marketplace.json`(plugin name: `bicv-skills`)。

- 注册 marketplace(指向本仓库):

  ```bash
  /plugin marketplace add <owner>/bicv_skills
  ```

- 安装 plugin:

  ```bash
  /plugin install bicv-skills@bicv-skills
  ```

### Codex

Codex 用 `.agents/plugins/marketplace.json`(同 plugin name)。

- 在 Codex 中执行:

  ```bash
  /plugin marketplace add <owner>/bicv_skills
  ```

- 安装 plugin:

  ```bash
  /plugin install bicv-skills@bicv-skills
  ```

> 把 `<owner>/bicv_skills` 替换成实际仓库路径,例如 `your-org/bicv_skills` 或本地 `file:///abs/path/to/bicv_skills`。

## 配置

各 skill 凭据统一存在 `~/.bicv/<skill-name>.json`，结构必须包含 `systems` 字典，支持多实例（多套 Gerrit、多套 Jenkins 等），CLI 通过 `--system <name>` 切换。详见 [config 规范](docs/config-spec.md)。

## 文档

- [config 规范](docs/config-spec.md)
- [如何新增 skill](docs/writing-a-skill.md)