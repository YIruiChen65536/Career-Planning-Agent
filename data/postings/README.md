# JD 语料格式（数据纪律见 06 手册§6：每条必须带 url 或来源说明）

本目录按岗位方向分文件存放，如 `backend.json`、`frontend.json`，内容为 JSON 数组：

```json
[
  {
    "id": "boss-20261020-001",
    "title": "Java 后端开发工程师",
    "company": "某科技公司",
    "source": "BOSS直聘",
    "url": "https://www.zhipin.com/job_detail/xxx.html",
    "description": "岗位职责：1. 负责后端服务开发…… 任职要求：1. 熟悉 Java……"
  }
]
```

要求：
- 每个方向 10~20 条，总计 50~100 条（M2 验收标准）；
- `description` 保留 JD 原文（技能抽取的输入），不要自己改写；
- `url` 是"真实数据与证据"评分的凭证，断链也要留；
- 涉及 HR 个人信息的一律抹除后再入库。
