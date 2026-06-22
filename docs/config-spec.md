# config 规范

所有 skill 的凭据/连接配置统一存放在用户家目录下。

## 文件位置

```
~/.bicv/<config_name>.json
```

`<config_name>` 由各 skill 自己决定，常见值：

| skill | config_name |
|---|---|
| gerrit-restapi | `gerrit.json` |
| jenkins-restapi | `jenkins.json` |
| zentao-restapi | `zentao.json` |
| mysql | `database.json` |

新 skill 在 `references/config.md` 里声明自己的 config_name。

文件必须位于用户家目录下（实现会校验 `Path.home()` 关系，防止路径穿越）。

## 文件结构

```json
{
  "systems": {
    "<system-name>": { ... }
  }
}
```

- 顶层必须有 `systems` 对象
- 键是系统名（CLI 用 `--system <name>` 切换）
- 值是该系统的连接配置，字段由各 skill 自行定义，见该 skill 的 `references/config.md`

## 加载机制

脚本通过 `shared.system_config.load_systems_config(config_name)` 加载，错误处理统一为 `ServiceError`：

- 路径越出家目录 → `Config file must live under the user home directory`
- 文件不存在 → `Cannot find config file: <path>`
- JSON 解析失败 → `Config file is not valid JSON: <path>`
- 顶层缺 `systems` 字典 → `Config file is missing a systems object`

调用方捕获 `ServiceError` 并提示用户在正确位置创建文件。

## 安全说明

自用环境，凭据**明文存储**。`~/.bicv/` 不进任何仓库。