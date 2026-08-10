# People 系统人才库 API 预留协议

本项目已预留 People / ATS 系统的人才库接入层：

- 代码入口：`modules/talent_pool/people_system.py`
- 环境配置：`.env` 中的 `PEOPLE_*` 变量
- 使用位置：简历开源 → 候选线索 → 数据源 `内部人才库`

## 1. 搜索人才

默认请求：

```http
GET {PEOPLE_API_BASE_URL}{PEOPLE_API_SEARCH_ENDPOINT}?q=...&department=...&location=...&limit=...
Authorization: Bearer {PEOPLE_API_TOKEN}
```

默认配置：

```env
PEOPLE_API_SEARCH_ENDPOINT=/api/talents/search
```

建议返回：

```json
{
  "items": [
    {
      "id": "people_123",
      "candidate_name": "张三",
      "current_org": "某公司",
      "domain": "大模型",
      "level": "专家",
      "skills": ["LLM", "RAG", "Agent"],
      "education": ["清华大学"],
      "work_summary": "负责企业级 RAG 平台建设",
      "project_summary": "主导 Agent Workflow 落地",
      "location": "北京",
      "work_email": "zhangsan@example.com",
      "lark": "ou_xxx",
      "github": "https://github.com/example",
      "contact_channels": [
        {
          "type": "工作邮箱",
          "value": "zhangsan@example.com",
          "source": "People 系统授权字段",
          "confidence": "high"
        }
      ],
      "tags": ["内部人才库", "重点关注"]
    }
  ]
}
```

联系方式字段只建议返回招聘场景下被授权使用的联系方式，例如工作邮箱、招聘系统联系方式、公开主页、公开 GitHub profile、公开 LinkedIn 链接等。不要返回身份证、家庭住址、私人敏感信息。

支持的列表字段名：`items` / `data` / `results` / `talents` / `candidates`。

## 2. 查询人才详情

默认请求：

```http
GET {PEOPLE_API_BASE_URL}/api/talents/{people_id}
Authorization: Bearer {PEOPLE_API_TOKEN}
```

默认配置：

```env
PEOPLE_API_PROFILE_ENDPOINT=/api/talents/{people_id}
```

## 3. 查询候选状态

默认请求：

```http
GET {PEOPLE_API_BASE_URL}/api/talents/{people_id}/status
Authorization: Bearer {PEOPLE_API_TOKEN}
```

默认配置：

```env
PEOPLE_API_STATUS_ENDPOINT=/api/talents/{people_id}/status
```

建议返回：

```json
{
  "people_id": "people_123",
  "current_status": "待联系",
  "last_contacted_at": "2026-08-09",
  "owner": "HR",
  "notes": "此前对算法专家岗位感兴趣"
}
```

## 4. 同步到本地人才库

代码入口：

```python
from modules.talent_pool.people_system import import_people_profile_to_local_pool

talent_pool_id = import_people_profile_to_local_pool("people_123")
```

这会调用详情接口，并写入本地 SQLite `talent_pool` 表。

## 配置示例

```env
PEOPLE_API_BASE_URL=https://people-api.company.com
PEOPLE_API_TOKEN=your_service_token
PEOPLE_API_AUTH_HEADER=Authorization
PEOPLE_API_TOKEN_PREFIX=Bearer
PEOPLE_API_SEARCH_ENDPOINT=/api/talents/search
PEOPLE_API_PROFILE_ENDPOINT=/api/talents/{people_id}
PEOPLE_API_STATUS_ENDPOINT=/api/talents/{people_id}/status
PEOPLE_API_TIMEOUT=15
```
