# 访问权限

> **English Title**: Access Rights REST API Endpoints
>
> 本文档为 Gerrit 访问权限，包含完整的 REST API 端点说明、请求/响应示例。
>
> **版本**: v3.8.3

---

## 目录

- [Access Rights Endpoints (访问权限端点)](#access-rights-endpoints-(访问权限端点))
- [List Access Rights](#list-access-rights)
- [JSON Entities](#json-entities)
- [AccessSectionInfo](#accesssectioninfo)
- [PermissionInfo](#permissioninfo)
- [PermissionRuleInfo](#permissionruleinfo)
- [ProjectAccessInfo](#projectaccessinfo)

---

# Gerrit Code Review - /access/ REST API

version v3.8.3

Table of Contents

  * Access Rights Endpoints (访问权限端点)
    * List Access Rights
  * JSON Entities
    * AccessSectionInfo
    * PermissionInfo
    * PermissionRuleInfo
    * ProjectAccessInfo

This page describes the access rights related REST endpoints. Please also take note of the general information on the [REST API](rest-api.html).

## Access Rights Endpoints (访问权限端点)

### List Access Rights

'GET /access/?project=[{project-name}](rest-api-projects.html#project-name)'

Lists the access rights for projects. The projects for which the access rights should be returned must be specified as `project` options. The `project` can be specified multiple times.

As result a map is returned that maps the project name to ProjectAccessInfo entities.

The entries in the map are sorted by project name.

Request
    
    
      GET /access/?project=MyProject&project=All-Projects HTTP/1.0

Response
    
    
      HTTP/1.1 200 OK
      Content-Type: application/json; charset=UTF-8
    
      )]}'
      {
        "All-Projects": {
          "revision": "edd453d18e08640e67a8c9a150cec998ed0ac9aa",
          "local": {
            "GLOBAL_CAPABILITIES": {
              "permissions": {
                "priority": {
                  "rules": {
                    "15bfcd8a6de1a69c50b30cedcdcc951c15703152": {
                      "action": "BATCH"
                    }
                  }
                },
                "streamEvents": {
                  "rules": {
                    "15bfcd8a6de1a69c50b30cedcdcc951c15703152": {
                      "action": "ALLOW"
                    }
                  }
                },
                "administrateServer": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    }
                  }
                }
              }
            },
            "refs/meta/config": {
              "permissions": {
                "submit": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                },
                "label-Code-Review": {
                  "label": "Code-Review",
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW",
                      "min": -2,
                      "max": 2
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW",
                      "min": -2,
                      "max": 2
                    }
                  }
                },
                "read": {
                  "exclusive": true,
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                },
                "push": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                }
              }
            },
            "refs/for/refs/*": {
              "permissions": {
                "pushMerge": {
                  "rules": {
                    "global:Registered-Users": {
                      "action": "ALLOW"
                    }
                  }
                },
                "push": {
                  "rules": {
                    "global:Registered-Users": {
                      "action": "ALLOW"
                    }
                  }
                }
              }
            },
            "refs/tags/*": {
              "permissions": {
                "createSignedTag": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                },
                "createTag": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                }
              }
            },
            "refs/heads/*": {
              "permissions": {
                "forgeCommitter": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                },
                "forgeAuthor": {
                  "rules": {
                    "global:Registered-Users": {
                      "action": "ALLOW"
                    }
                  }
                },
                "submit": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                },
                "editTopicName": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW",
                      "force": true
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW",
                      "force": true
                    }
                  }
                },
                "label-Code-Review": {
                  "label": "Code-Review",
                  "rules": {
                    "global:Registered-Users": {
                      "action": "ALLOW",
                      "min": -1,
                      "max": 1
                    },
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW",
                      "min": -2,
                      "max": 2
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW",
                      "min": -2,
                      "max": 2
                    }
                  }
                },
                "create": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                },
                "push": {
                  "rules": {
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    },
                    "global:Project-Owners": {
                      "action": "ALLOW"
                    }
                  }
                }
              }
            },
            "refs/*": {
              "permissions": {
                "read": {
                  "rules": {
                    "global:Anonymous-Users": {
                      "action": "ALLOW"
                    },
                    "53a4f647a89ea57992571187d8025f830625192a": {
                      "action": "ALLOW"
                    }
                  }
                }
              }
            }
          },
          "is_owner": true,
          "owner_of": [
            "GLOBAL_CAPABILITIES",
            "refs/meta/config",
            "refs/for/refs/*",
            "refs/tags/*",
            "refs/heads/*",
            "refs/*"
          ],
          "can_upload": true,
          "can_add": true,
          "can_add_tags": true,
          "config_visible": true,
          "groups": {
             "53a4f647a89ea57992571187d8025f830625192a": {
               "url": "#/admin/groups/uuid-53a4f647a89ea57992571187d8025f830625192a",
               "options": {},
               "description": "Gerrit Site Administrators",
               "group_id": 1,
               "owner": "Administrators",
               "owner_id": "53a4f647a89ea57992571187d8025f830625192a",
               "created_on": "2009-06-08 23:31:00.000000000",
               "name": "Administrators"
             },
             "global:Registered-Users": {
               "options": {},
               "name": "Registered Users"
             },
             "global:Project-Owners": {
               "options": {},
               "name": "Project Owners"
             },
             "15bfcd8a6de1a69c50b30cedcdcc951c15703152": {
               "url": "#/admin/groups/uuid-15bfcd8a6de1a69c50b30cedcdcc951c15703152",
               "options": {},
               "description": "Service accounts that interact with Gerrit",
               "group_id": 2,
               "owner": "Administrators",
               "owner_id": "53a4f647a89ea57992571187d8025f830625192a",
               "created_on": "2009-06-08 23:31:00.000000000",
               "name": "Service Users"
             },
             "global:Anonymous-Users": {
               "options": {},
               "name": "Anonymous Users"
             }
          }
        },
        "MyProject": {
          "revision": "61157ed63e14d261b6dca40650472a9b0bd88474",
          "inherits_from": {
            "id": "All-Projects",
            "name": "All-Projects",
            "description": "Access inherited by all other projects."
          },
          "local": {},
          "is_owner": true,
          "owner_of": [
            "refs/*"
          ],
          "can_upload": true,
          "can_add": true,
          "can_add_tags": true,
          "config_visible": true
        }
      }

## JSON Entities

### AccessSectionInfo

The `AccessSectionInfo` describes the access rights that are assigned on a ref.

Field Name |  | Description  
---|---|---  
`permissions` |  | The permissions assigned on the ref of this access section as a map that maps the permission names to PermissionInfo entities.  
  
### PermissionInfo

The `PermissionInfo` entity contains information about an assigned permission.

Field Name |  | Description  
---|---|---  
`label` | optional | The name of the label. Not set if it’s not a label permission.  
`exclusive` | not set if `false` | Whether this permission is assigned exclusively.  
`rules` |  | The rules assigned for this permission as a map that maps the UUIDs of the groups for which the permission are assigned to PermissionRuleInfo entities.  
  
### PermissionRuleInfo

The `PermissionRuleInfo` entity contains information about a permission rule that is assigned to group.

Field Name |  | Description  
---|---|---  
`action` |  | The action of this rule. For normal permissions this can be `ALLOW`, `DENY` or `BLOCK`. Special values for global capabilities are `INTERACTIVE` and `BATCH`.  
`force` | not set if `false` | Whether the force flag is set.  
`min` | not set if range is empty (from `0` to `0`) or not set | The min value of the permission range.  
`max` | not set if range is empty (from `0` to `0`) or not set | The max value of the permission range.  
  
### ProjectAccessInfo

The `ProjectAccessInfo` entity contains information about the access rights for a project.

Field Name |  | Description  
---|---|---  
`revision` |  | The revision of the `refs/meta/config` branch from which the access rights were loaded.  
`inherits_from` | not set for the `All-Projects` project | The parent project from which permissions are inherited as a [ProjectInfo](rest-api-projects.html#project-info) entity.  
`local` |  | The local access rights of the project as a map that maps the refs to AccessSectionInfo entities.  
`is_owner` | not set if `false` | Whether the calling user owns this project.  
`owner_of` |  | The list of refs owned by the calling user.  
`can_upload` | not set if `false` | Whether the calling user can upload to any ref.  
`can_add` | not set if `false` | Whether the calling user can add any ref.  
`can_add_tags` | not set if `false` | Whether the calling user can add any tag ref.  
`config_visible` | not set if `false` | Whether the calling user can see the `refs/meta/config` branch of the project.  
`groups` |  | A map of group UUID to [GroupInfo](rest-api-groups.html#group-info) objects, with names and URLs for the group UUIDs used in the `local` map. This will include names for groups that might be invisible to the caller.  
`config_web_links` | optional | Links to the history of the configuration file governing this project’s access rights as list of [WebLinkInfo](rest-api-changes.html#web-link-info) entities.  
  
* * *

Part of [Gerrit Code Review](index.html)

Search 

Version v3.8.3  

