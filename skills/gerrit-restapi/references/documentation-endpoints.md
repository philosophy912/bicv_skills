# 文档

> **English Title**: Documentation REST API Endpoints
>
> 本文档为 Gerrit 文档，包含完整的 REST API 端点说明、请求/响应示例。
>
> **版本**: v3.8.3

---

## 目录

- [Documentation Search Endpoints](#documentation-search-endpoints)
- [Search Documentation](#search-documentation)
- [JSON Entities](#json-entities)
- [DocResult](#docresult)

---

# Gerrit Code Review - /Documentation/ REST API

version v3.8.3

Table of Contents

  * Documentation Search Endpoints
    * Search Documentation
  * JSON Entities
    * DocResult

This page describes the documentation search related REST endpoints. Please also take note of the general information on the [REST API](rest-api.html).

Please note that this feature is only usable with documentation built-in. You’ll need to `bazel build withdocs` or `bazel build release` to test this feature.

## Documentation Search Endpoints

### Search Documentation

'GET /Documentation/'

With `q` parameter, search our documentation index for the terms.

A list of DocResult entities is returned describing the results.

Request
    
    
      GET /Documentation/?q=test HTTP/1.0

Response
    
    
      HTTP/1.1 200 OK
      Content-Disposition: attachment
      Content-Type: application/json; charset=UTF-8
    
      )]}'
      [
        {
          "title": "Gerrit Code Review - REST API Developers\u0027 Notes",
          "url": "Documentation/dev-rest-api.html"
        },
        {
          "title": "Gerrit Code Review - REST API",
          "url": "Documentation/rest-api.html"
        },
        {
          "title": "Gerrit Code Review - /plugins/ REST API",
          "url": "Documentation/rest-api-plugins.html"
        },
        {
          "title": "Gerrit Code Review - /config/ REST API",
          "url": "Documentation/rest-api-config.html"
        },
        {
          "title": "Gerrit Code Review for Git",
          "url": "Documentation/index.html"
        },
        {
          "title": "Gerrit Code Review - /access/ REST API",
          "url": "Documentation/rest-api-access.html"
        },
        {
          "title": "Gerrit Code Review - Java Plugin Development",
          "url": "Documentation/dev-plugins.html"
        },
        {
          "title": "Gerrit Code Review - JavaScript Plugin Development and API",
          "url": "Documentation/pg-plugin-dev.html"
        },
        {
          "title": "Gerrit Code Review - Developer Setup",
          "url": "Documentation/dev-readme.html"
        },
        {
          "title": "Gerrit Code Review - Hooks",
          "url": "Documentation/config-hooks.html"
        },
        {
          "title": "Gerrit Code Review - /groups/ REST API",
          "url": "Documentation/rest-api-groups.html"
        },
        {
          "title": "Gerrit Code Review - /accounts/ REST API",
          "url": "Documentation/rest-api-accounts.html"
        },
        {
          "title": "Gerrit Code Review - /projects/ REST API",
          "url": "Documentation/rest-api-documentation.html"
        },
        {
          "title": "Gerrit Code Review - /projects/ REST API",
          "url": "Documentation/rest-api-projects.html"
        },
        {
          "title": "Gerrit Code Review - Prolog Submit Rules Cookbook",
          "url": "Documentation/prolog-cookbook.html"
        },
        {
          "title": "Gerrit Code Review - /changes/ REST API",
          "url": "Documentation/rest-api-changes.html"
        },
        {
          "title": "Gerrit Code Review - Configuration",
          "url": "Documentation/config-gerrit.html"
        },
        {
          "title": "Gerrit Code Review - Access Controls",
          "url": "Documentation/access-control.html"
        },
        {
          "title": "Gerrit Code Review - Licenses",
          "url": "Documentation/licenses.html"
        }
      ]

Query documentation

GET /Documentation/?q=keyword HTTP/1.0 

## JSON Entities

### DocResult

The `DocResult` entity contains information about a document.

Field Name |  | Description  
---|---|---  
`title` |  | The title of the document.  
`url` |  | The URL of the document.  
  
* * *

Part of [Gerrit Code Review](index.html)

Search 

Version v3.8.3  

