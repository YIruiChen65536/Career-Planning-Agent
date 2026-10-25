# data/ 课程-机会资产库说明

> 本目录下 `curriculum.json`（示例培养方案）与 `opportunities.json`（竞赛/项目/实习清单）是流水线③映射与④规划（`career_agent/pipeline.py` 的 `map_courses` / `make_roadmap`，见 pipeline.py:53-60）的静态数据底座。本文说明字段含义、设计取舍与 M3 的消费方式。

## 1. curriculum.json —— 示例培养方案

顶层 `note` 已注明：**这是示例方案，团队可整体替换为本校真实方案**（保持字段结构、替换 `courses` 数组即可）。

`courses[]` 每门课 5 个字段：

| 字段 | 含义 | 约束 |
|---|---|---|
| `code` | 课程代码（示例自编：GE=通识、MATH/PHYS=外院基础、CS=专业课、PR=实践） | 全文件唯一 |
| `name` | 课程名 | 全文件唯一 |
| `semester` | 开课学期，1-8（1=大一上 … 8=大四下） | 整数 1-8 |
| `category` | 课程类别 | 五选一：通识必修 / 学科基础 / 专业核心 / 专业选修 / 实践环节 |
| `skills_covered` | 该课覆盖的技能，用**可与 JD 技能对齐的英文通用名** | 可为空数组（思政、体育等无对应技术技能） |

共 56 门（通识必修 14 / 学科基础 11 / 专业核心 10 / 专业选修 14 / 实践环节 7），学期排布符合真实先修链：数据结构(3)先于算法(5)与计组(4)先于操作系统(5)，概率(4)+线代(2)先于机器学习(6)，机器学习(6)先于深度学习/NLP/CV(7)。

## 2. opportunities.json —— 机会清单

顶层三块：

- `competitions[]`（16 个）：`{name, level, months[], skills[], prep_hours_est}`
  - `level`：国际 / 国家 / 省级 / 校级（本清单只收录国际与国家级主流赛事）；
  - `months`：从报名/预选到决赛的**常见举办月份**（数字 1-12 数组，全年滚动型赛事如 Kaggle/天池为 1-12）；
  - `prep_hours_est`：零基础到能参赛的粗估总投入小时数，供④把机会折算进每周时间预算。
- `projects[]`（10 个）：`{name, desc, skills[], duration_weeks}` —— 建议项目类型，`duration_weeks` 是业余时间投入的典型周期。
- `internships[]`（4 档）：`{stage, typical_roles[], skills[], note}` —— 按大一暑假 / 大二暑假 / 大三暑假 / 大四分档，`note` 说明该档定位与时间窗口。

## 3. 设计取舍

1. **示例方案而非真实方案**：先用手写示例打通③映射全链路，避免被"等教务处数据"阻塞；替换成本被压缩为"改一个 JSON 文件"。
2. **skills_covered / skills 全部用英文通用名**（Python、MySQL、Data Structures…），与②归并输出的 `SkillStat.skill` 规范名（schemas.py:33-34）同风格，③对齐时可直接按名匹配或走一次 LLM 别名对齐；避免中英混写导致"机器学习 ≠ Machine Learning"的假不匹配。
3. **课程粒度而非知识点粒度**：一门课只标 1~4 个主技能，不穷举知识点——映射的语义判断本就交给 LLM，数据只需提供"锚点"。
4. **竞赛时间写"常见月份"而非具体日期**：赛事逐年微调，写月份够④做学期排布（如"大三上 → 9/10/11 月的 ICPC 区域赛"），又不会因具体日期过期而误导。
5. **竞赛事实全部核实、拿不准就保守**：逐条经 WebSearch 核对官网/教育部/高校通知（2025-2026 年口径）。两处保守处理说明：全国大学生信息安全竞赛近年初赛移至 11-12 月（第 18/19 届），决赛在次年 3-7 月，故只写初赛月份；"挑战杯"大挑为两年一届（全国终审在奇数年），但按其常见校/省赛（4-5 月）与全国终审（10-11 月）月份收录。
6. **实习按暑假分档而非按岗位罗列**：③映射输出的是"某能力 → 某档实习的某类岗位"，分档结构与 `SemesterPlan.term`（如"大二下"→ 大二暑假）天然对齐。

## 4. M3 消费方式（谁读它、怎么对齐 skills）

- **读者**：仅流水线③`map_courses`（与④`make_roadmap`间接使用其输出）。它们是静态 JSON，直接 `json.load` 读入后拼进 Agent 的 prompt 上下文（体量小，无需入库；入库走 SQLite 的是 LLM 缓存与档案，不是这俩文件）。
- **对齐流程**：②产出的 `SkillStat[]`（JD 侧技能）→ ③对每个技能在 `curriculum.courses[].skills_covered` 与 `opportunities.{competitions,projects,internships}[].skills` 中做名称对齐（先精确/别名匹配，匹配不上交 LLM 做一次语义对齐，结果进缓存）→ 命中的课程/竞赛/项目/实习写入 `CourseMapping`（schemas.py:40-48），课程覆盖不到的写 `gap_note` 自学建议。
- **学期回填**：③输出的课程带 `semester`，④据此把行动项落进对应 `SemesterPlan.actions`；竞赛按 `months` 换算到学期（如月份 9-11 → 秋季学期），并按学生 `weekly_hours`（schemas.py:78）与 `prep_hours_est` 做可行性裁剪。
- **自检**：交付时已用一次性 Python 命令验证两个 JSON 可解析、`semester`∈1-8、`months`∈1-12、课程 `code`/`name` 与竞赛 `name` 无重复（见交付记录）。

## 5. 维护

- 替换为本校真实培养方案时：保持字段结构，全量替换 `courses`；`skills_covered` 命名延续"英文通用名"约定，避免对齐退化。
- 竞赛信息每年开学季复核一次（尤其months 与赛制调整过的信安竞赛）。
