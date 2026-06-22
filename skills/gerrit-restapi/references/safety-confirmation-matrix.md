# Gerrit 高危操作确认矩阵

在使用 `gerrit-restapi` 执行任何写操作前，先判断风险等级。所有 **严重** 和 **高危** 操作都必须逐次征得用户确认。

## 确认规则

1. 每次具体操作独立确认，不能因为同类操作已确认过一次就跳过后续确认。
2. 确认时必须明确说明 API、HTTP 方法、目标资源和影响。
3. 只有用户明确同意后才能执行。

## 严重操作

| 端点分组 | API 接口 | 风险说明 |
|---------|---------|---------|
| `/accounts/` | `PUT /accounts/{username}` | 创建新账户，可分配组和密钥 |
| `/accounts/` | `PUT /accounts/{account-id}/password.http` | 设置/生成 HTTP 密码 |
| `/accounts/` | `POST /accounts/{account-id}/sshkeys` | 添加 SSH 公钥 |
| `/changes/` | `POST /changes/{change-id}/revisions/{revision}/submit` | 提交变更到代码库 |
| `/config/` | `POST /config/server/reload` | 重载服务器全局配置 |
| `/config/` | `POST /config/server/caches/` (FLUSH_ALL) | 刷新所有缓存 |
| `/groups/` | `PUT /groups/{group-name}` | 创建用户组 |
| `/groups/` | `PUT /groups/{group-id}/owner` | 转移组所有权 |
| `/plugins/` | `PUT /plugins/{plugin-id}.jar` | 安装/覆盖插件，可执行任意代码 |
| `/plugins/` | `POST /plugins/{plugin-id}/gerrit~disable` | 禁用插件 |
| `/projects/` | `PUT /projects/{project-name}/ban` | 封禁 commit，不可逆 |
| `/projects/` | `POST /projects/{project-name}/access` | 修改项目访问权限 |
| `/projects/` | `PUT /projects/{project-name}/config` | 修改项目全局配置 |

## 高危操作

| 端点分组 | API 接口 | 风险说明 |
|---------|---------|---------|
| `/accounts/` | `DELETE /accounts/{account-id}/active` | 停用账户 |
| `/accounts/` | `DELETE /accounts/{account-id}/sshkeys/{id}` | 删除 SSH 密钥 |
| `/accounts/` | `DELETE /accounts/{account-id}/password.http` | 删除 HTTP 密码 |
| `/accounts/` | `DELETE /accounts/{account-id}/emails/{id}` | 删除邮箱 |
| `/accounts/` | `DELETE /accounts/{account-id}/gpgkeys/{id}` | 删除 GPG 密钥 |
| `/accounts/` | `DELETE /accounts/{account-id}/name` | 删除账户名 |
| `/accounts/` | `POST /accounts/{account-id}/external.ids:delete` | 删除外部 ID，可能导致无法登录 |
| `/changes/` | `POST /changes/{change-id}/abandon` | 放弃变更 |
| `/changes/` | `POST /changes/` | 创建新变更 |
| `/changes/` | `POST /changes/{change-id}/revisions/{id}/review` | 发布审查评分 |
| `/config/` | `POST /config/server/caches/{name}/flush` | 刷新指定缓存 |
| `/config/` | `DELETE /config/server/tasks/{id}` | 杀死后台任务 |
| `/config/` | `PUT /config/server/preferences` | 修改全局默认偏好 |
| `/config/` | `PUT /config/server/preferences.diff` | 修改全局 Diff 偏好 |
| `/config/` | `PUT /config/server/preferences.edit` | 修改全局编辑偏好 |
| `/groups/` | `PUT /groups/{group-id}/members/{account-id}` | 添加组成员 |
| `/groups/` | `POST /groups/{group-id}/members.add` | 批量添加组成员 |
| `/groups/` | `DELETE /groups/{group-id}/members/{account-id}` | 移除组成员 |
| `/groups/` | `POST /groups/{group-id}/members.delete` | 批量移除组成员 |
| `/groups/` | `PUT /groups/{group-id}/groups/{group-id}` | 添加子组 |
| `/groups/` | `DELETE /groups/{group-id}/groups/{group-id}` | 移除子组 |
| `/plugins/` | `POST /plugins/{plugin-id}/gerrit~enable` | 启用插件 |
| `/plugins/` | `POST /plugins/{plugin-id}/gerrit~reload` | 重载插件 |
| `/projects/` | `PUT /projects/{project-name}` | 创建新项目 |
| `/projects/` | `DELETE /projects/{project-name}/branches/{id}` | 删除分支 |
| `/projects/` | `POST /projects/{project-name}/branches:delete` | 批量删除分支 |
| `/projects/` | `DELETE /projects/{project-name}/tags/{id}` | 删除标签 |
| `/projects/` | `POST /projects/{project-name}/tags:delete` | 批量删除标签 |
| `/projects/` | `PUT /projects/{project-name}/parent` | 修改项目父级 |
| `/projects/` | `PUT /projects/{project-name}/HEAD` | 修改默认 HEAD |
| `/projects/` | `POST /projects/{project-name}/gc` | 执行 Git 垃圾回收 |
| `/projects/` | `DELETE /projects/{project-name}/labels/{name}` | 删除审查标签 |

## 确认模板

```text
⚠️ 即将执行高危操作：
┌─────────────────┬──────────────────────────────────────────┐
│ 接口            │ DELETE /projects/MyProject/branches/feature-x │
│ 方法            │ DELETE                                      │
│ 目标            │ 项目 MyProject 的 feature-x 分支            │
│ 影响            │ 该分支将被永久删除，不可恢复                  │
└─────────────────┴──────────────────────────────────────────┘

是否确认执行？(确认/取消)
```
