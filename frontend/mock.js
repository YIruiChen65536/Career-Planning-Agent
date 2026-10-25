/*
 * mock.js — 降级演示模式数据（唯一数据来源，app.js 只从这里取）
 *
 * 字段与 career_agent/schemas.py 严格一致：
 *   JobPosting        {id, title, company, source, url, description}
 *   SkillStat         {skill, category("hard"|"tool"|"soft"), frequency, is_core, aliases}
 *   CourseMapping     {skill, courses, competitions, projects, internships, gap_note}
 *   SemesterPlan      {term, focus, courses, actions, milestone, hours_per_week}
 *   Roadmap           {profile_summary, semesters, risks}
 *   DialogueTurn      {reply, action("none"|"replan"|"adjust_hours"|"clarify"), reason}
 *
 * 内容依据 data/curriculum.json（课程名）与 data/opportunities.json（竞赛/项目/实习阶段）整理，
 * 明确标注为演示语料，不冒充真实抓取数据。
 */
(function () {
  "use strict";

  var TERMS = ["大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上", "大四下"];

  // ------------------------------------------------------------------
  // ①+② analyze 演示数据：{postings, skills, errors}
  // ------------------------------------------------------------------

  function posting(id, title, company, desc) {
    return { id: id, title: title, company: company, source: "内置演示语料", url: null, description: desc };
  }

  function skill(name, category, frequency, isCore, aliases) {
    return { skill: name, category: category, frequency: frequency, is_core: isCore, aliases: aliases || [] };
  }

  var ANALYZE_LIBRARY = {
    backend: {
      keywords: ["后端", "服务端", "server", "backend", "Python后端"],
      data: {
        postings: [
          posting("demo-backend-001", "Python后端开发工程师", "深圳TCL新技术有限公司",
            "岗位职责：参与软件产品（服务端/脚本工具）的设计、开发和测试。任职要求：2026届本科及以上，计算机相关专业；熟练掌握Python（语法、面向对象、高级特性、数据结构与算法）；熟练使用Flask、Django等主流框架；掌握MySQL基础、ORM操作及Redis基础和原理；有AI Agent/NLP方向项目经验者优先；有团队合作精神。（演示语料，节选）"),
          posting("demo-backend-002", "服务端开发工程师（Java方向）", "美团",
            "岗位职责：负责到店业务服务端需求迭代与系统优化。任职要求：本科及以上；扎实的Java基础与数据结构算法功底；熟悉Spring Boot、MySQL、Redis；了解Linux常用命令与Git协作流程；有高并发项目经验者优先；沟通能力良好。（演示语料，节选）"),
          posting("demo-backend-003", "后端开发实习生", "字节跳动",
            "岗位职责：参与内容平台后端服务开发。任职要求：本科在读，计算机相关专业；熟悉至少一门后端语言（Python/Java/Go）；理解MySQL索引与事务；熟悉Docker、Linux开发环境；每周可实习4天以上，实习期3个月以上优先。（演示语料，节选）"),
          posting("demo-backend-004", "Golang后端开发工程师", "拼多多集团",
            "岗位职责：负责电商交易链路服务端开发与性能优化。任职要求：本科及以上；熟悉Golang或愿意从Python/Java转Go；熟悉MySQL、Redis、消息队列；具备良好的数据结构与算法基础；熟悉Git协作，有开源贡献经历加分。（演示语料，节选）"),
        ],
        skills: [
          skill("Python", "hard", 4, true, ["Python开发", "Python编程"]),
          skill("MySQL", "tool", 4, true, ["SQL"]),
          skill("数据结构", "hard", 4, true, ["数据结构与算法"]),
          skill("Redis", "tool", 3, true, []),
          skill("Linux", "tool", 3, true, []),
          skill("Git", "tool", 3, true, []),
          skill("Spring Boot", "tool", 2, true, ["Spring"]),
          skill("Django", "tool", 2, false, ["Flask"]),
          skill("Docker", "tool", 2, false, []),
          skill("算法", "hard", 2, false, ["算法设计"]),
          skill("团队协作", "soft", 2, false, ["团队合作"]),
          skill("沟通能力", "soft", 1, false, []),
        ],
      },
    },
    algo: {
      keywords: ["算法", "机器学习", "AI", "人工智能", "深度学习"],
      data: {
        postings: [
          posting("demo-algo-001", "2027届正式批-算法工程师", "拼多多集团",
            "岗位职责：利用机器学习、深度学习技术优化搜索、推荐、广告等场景效果。任职要求：硕士及以上，计算机相关专业；具备强悍的编码能力，熟悉Linux开发环境；熟悉TensorFlow、PyTorch等主流框架；有顶会论文或竞赛获奖者优先。（演示语料，节选）"),
          posting("demo-algo-002", "推荐算法工程师", "美团",
            "岗位职责：负责推荐精排/重排模型迭代与线上效果优化。任职要求：本科及以上；扎实的机器学习基础与Python编码能力；熟悉PyTorch；熟悉常用数据结构与算法；有Kaggle/天池竞赛经历或论文复现经验加分。（演示语料，节选）"),
          posting("demo-algo-003", "AI算法实习生（NLP方向）", "阿里巴巴",
            "岗位职责：参与大模型训练与评测相关算法工作。任职要求：计算机/数学相关专业在读；熟悉Python与PyTorch；了解深度学习常见模型；能阅读中英文论文并复现；每周实习4天以上优先。（演示语料，节选）"),
          posting("demo-algo-004", "计算机视觉算法工程师", "海康威视",
            "岗位职责：负责目标检测、图像分割算法研发与落地。任职要求：本科及以上；熟悉C++/Python；掌握OpenCV、PyTorch；熟悉Linux环境；有CVPR等论文或算法竞赛获奖者优先；具备良好的沟通能力与团队协作精神。（演示语料，节选）"),
        ],
        skills: [
          skill("Python", "hard", 4, true, ["Python编程"]),
          skill("机器学习", "hard", 4, true, ["Machine Learning"]),
          skill("PyTorch", "tool", 4, true, []),
          skill("深度学习", "hard", 3, true, ["Deep Learning"]),
          skill("数据结构", "hard", 3, true, ["数据结构与算法"]),
          skill("Linux", "tool", 3, true, []),
          skill("C/C++", "hard", 2, false, ["C++"]),
          skill("论文复现", "hard", 2, false, ["论文阅读"]),
          skill("算法", "hard", 2, false, []),
          skill("团队协作", "soft", 2, false, ["团队合作"]),
          skill("沟通能力", "soft", 1, false, []),
        ],
      },
    },
    frontend: {
      keywords: ["前端", "web", "Web", "H5", "frontend"],
      data: {
        postings: [
          posting("demo-fe-001", "Web前端开发工程师", "京东集团",
            "岗位职责：负责电商主站页面开发与性能优化。任职要求：本科及以上；精通HTML/CSS/JavaScript；熟悉Vue或React生态；了解TypeScript、Webpack构建流程；熟悉Git协作；对浏览器渲染原理有理解者优先。（演示语料，节选）"),
          posting("demo-fe-002", "前端开发实习生", "腾讯",
            "岗位职责：参与PC/移动端Web页面开发。任职要求：本科在读；扎实的HTML/CSS/JS基础；会用Vue3或React开发组件；了解HTTP协议与浏览器调试工具；每周实习4天以上。（演示语料，节选）"),
          posting("demo-fe-003", "小程序前端开发工程师", "美团",
            "岗位职责：负责到店小程序的功能迭代与体验优化。任职要求：本科及以上；熟悉JavaScript与微信小程序开发；了解组件化开发思想；有跨端框架（Taro/uni-app）经验加分；沟通能力良好。（演示语料，节选）"),
          posting("demo-fe-004", "大前端工程师（React方向）", "小红书",
            "岗位职责：负责社区产品Web端研发。任职要求：本科及以上；熟练掌握TypeScript与React；熟悉前端工程化与性能优化；了解Node.js；有个人技术博客或开源项目者优先。（演示语料，节选）"),
        ],
        skills: [
          skill("JavaScript", "hard", 4, true, ["JS"]),
          skill("HTML/CSS", "hard", 4, true, ["CSS", "HTML"]),
          skill("Vue", "tool", 3, true, ["Vue.js", "Vue3"]),
          skill("React", "tool", 2, false, []),
          skill("TypeScript", "hard", 2, false, ["TS"]),
          skill("Git", "tool", 3, true, []),
          skill("浏览器原理", "hard", 2, false, ["浏览器渲染"]),
          skill("Webpack", "tool", 2, false, ["Vite"]),
          skill("Node.js", "tool", 1, false, []),
          skill("沟通能力", "soft", 2, false, []),
          skill("团队协作", "soft", 1, false, []),
        ],
      },
    },
    data: {
      keywords: ["数据分析", "数据", "商业分析", "bi"],
      data: {
        postings: [
          posting("demo-da-001", "数据分析师（商业化方向）", "快手",
            "岗位职责：负责商业化业务的数据分析与策略支持。任职要求：本科及以上；精通SQL；熟练使用Python（Pandas）处理数据；了解统计学基础与AB实验；熟悉Tableau/FineBI等可视化工具者优先；业务理解与沟通能力强。（演示语料，节选）"),
          posting("demo-da-002", "商业数据分析师", "网易",
            "岗位职责：搭建业务指标体系，输出分析报告。任职要求：本科及以上，统计/计算机相关专业；SQL与Excel熟练；会用Python做数据清洗；有 Hive/Spark 使用经验加分；逻辑清晰，报告表达能力强。（演示语料，节选）"),
          posting("demo-da-003", "数据分析实习生", "哔哩哔哩",
            "岗位职责：支持用户增长专题的数据提取与分析。任职要求：本科在读；SQL必须熟练；会用Python/Pandas；了解漏斗与留存分析；实习3个月以上；对数据敏感，沟通顺畅。（演示语料，节选）"),
          posting("demo-da-004", "数据分析师（风控方向）", "蚂蚁集团",
            "岗位职责：负责风控策略的数据分析与效果评估。任职要求：本科及以上；扎实的统计学基础；精通SQL，熟悉Python；了解机器学习常用模型者优先；能跨团队协作推动策略落地。（演示语料，节选）"),
        ],
        skills: [
          skill("SQL", "hard", 4, true, ["Hive SQL"]),
          skill("Python", "hard", 4, true, ["Python编程"]),
          skill("统计学", "hard", 3, true, ["概率论与数理统计"]),
          skill("数据可视化", "tool", 3, true, ["Tableau", "FineBI"]),
          skill("Pandas", "tool", 3, true, []),
          skill("Excel", "tool", 2, false, []),
          skill("Hive", "tool", 2, false, ["大数据"]),
          skill("业务理解", "soft", 3, true, ["业务Sense"]),
          skill("沟通能力", "soft", 2, false, ["表达能力"]),
          skill("机器学习", "hard", 1, false, []),
        ],
      },
    },
  };

  var ANALYZE_EMPTY = {
    postings: [
      posting("demo-default-001", "软件开发工程师（通用方向）", "演示数据",
        "该岗位方向暂无真实语料，以下为演示用通用JD：任职要求：本科及以上，计算机相关专业；掌握至少一门编程语言与数据结构基础；熟悉MySQL与Git；具备良好的学习能力与团队协作精神。（演示语料，节选）"),
    ],
    skills: [
      skill("Python", "hard", 1, false, []),
      skill("数据结构", "hard", 1, false, []),
      skill("MySQL", "tool", 1, false, ["SQL"]),
      skill("Git", "tool", 1, false, []),
      skill("学习能力", "soft", 1, false, []),
      skill("团队协作", "soft", 1, false, []),
    ],
  };

  /** 按岗位关键词返回 analyze 演示响应；contract = GET /api/analyze/{keyword} 的返回体。 */
  function analyze(keyword) {
    var kw = String(keyword || "").toLowerCase();
    var hit = null;
    Object.keys(ANALYZE_LIBRARY).forEach(function (key) {
      if (hit) return;
      var lib = ANALYZE_LIBRARY[key];
      for (var i = 0; i < lib.keywords.length; i++) {
        if (kw.indexOf(lib.keywords[i].toLowerCase()) !== -1) { hit = lib.data; return; }
      }
    });
    var data = hit || ANALYZE_EMPTY;
    // 演示数据也按「频率降序」输出，与真实接口的 pandas 排序行为一致
    var skills = data.skills.slice().sort(function (a, b) { return b.frequency - a.frequency; });
    return { postings: data.postings, skills: skills, errors: [] };
  }

  // ------------------------------------------------------------------
  // ③ mappings 演示数据：CourseMapping[]（课程名取自 data/curriculum.json，
  //    竞赛/项目/实习取自 data/opportunities.json）
  // ------------------------------------------------------------------

  var MAPPINGS_LIBRARY = {
    backend: [
      { skill: "Python", courses: ["程序设计基础（C语言）→ 语言迁移自学"], competitions: ["蓝桥杯全国软件和信息技术专业人才大赛"], projects: ["网络爬虫与数据分析报告", "电商后端系统（REST API）"], internships: ["Web后端实习生（CRUD）·大二暑假", "后端开发实习生·大三暑假"], gap_note: "课内以 C/Java 为主，Python 工程化（虚拟环境、异步、打包）需要自学。" },
      { skill: "MySQL", courses: ["数据库系统"], competitions: [], projects: ["电商后端系统（REST API）"], internships: ["后端开发实习生·大三暑假"], gap_note: "索引、事务、锁等进阶内容课内只讲概念，建议对着真实慢查询练习。" },
      { skill: "Redis", courses: [], competitions: [], projects: ["电商后端系统（缓存模块）"], internships: ["后端开发实习生·大三暑假"], gap_note: "培养方案不覆盖，自学后务必在小项目里落地缓存与分布式锁。" },
      { skill: "数据结构", courses: ["数据结构", "算法设计与分析"], competitions: ["CCF CSP计算机软件能力认证", "蓝桥杯全国软件和信息技术专业人才大赛"], projects: [], internships: [], gap_note: "" },
      { skill: "Linux", courses: ["操作系统"], competitions: [], projects: ["个人博客/作品集网站（云服务器部署）"], internships: ["运维助理·大二暑假"], gap_note: "" },
      { skill: "Spring Boot", courses: ["软件工程"], competitions: [], projects: ["电商后端系统（REST API）"], internships: ["后端开发实习生·大三暑假"], gap_note: "Java 课内只讲语法，Spring 生态靠项目带：先跑通再读原理。" },
      { skill: "Docker", courses: ["云计算与容器技术"], competitions: [], projects: ["电商后端系统（容器化交付）"], internships: ["后端开发实习生·大三暑假"], gap_note: "选修课容量有限，建议自学并用容器交付课程项目。" },
      { skill: "团队协作", courses: ["软件工程综合实践"], competitions: ["中国大学生计算机设计大赛"], projects: ["校园二手交易平台（全栈）"], internships: [], gap_note: "" },
    ],
    algo: [
      { skill: "Python", courses: ["机器学习", "数据挖掘"], competitions: ["Kaggle数据科学竞赛", "阿里云天池大数据竞赛"], projects: ["推荐系统复现（MovieLens/淘宝公开数据）"], internships: ["算法实习生·大三暑假"], gap_note: "" },
      { skill: "机器学习", courses: ["机器学习", "人工智能导论"], competitions: ["Kaggle数据科学竞赛", "CCF大数据与计算智能大赛（BDCI）"], projects: ["Kaggle Playground 入门赛"], internships: ["算法实习生·大三暑假"], gap_note: "课内只到经典模型，面试要求的推导与调参经验要靠竞赛和论文复现补齐。" },
      { skill: "PyTorch", courses: ["深度学习"], competitions: ["Kaggle数据科学竞赛"], projects: ["推荐系统复现（MovieLens/淘宝公开数据）"], internships: ["算法实习生·大三暑假"], gap_note: "选修课在大三下才开，建议大二暑假先跟官方教程跑通三个案例。" },
      { skill: "数据结构", courses: ["数据结构", "算法设计与分析"], competitions: ["CCF CSP计算机软件能力认证", "中国大学生程序设计竞赛（CCPC）"], projects: [], internships: [], gap_note: "" },
      { skill: "Linux", courses: ["操作系统"], competitions: [], projects: ["实验室科研课题"], internships: ["算法实习生·大三暑假"], gap_note: "" },
      { skill: "统计学", courses: ["概率论与数理统计", "数值计算方法"], competitions: ["全国大学生数学建模竞赛（高教社杯）"], projects: [], internships: [], gap_note: "算法面试会考 A/B 实验与假设检验，课内深度不够需自学。" },
      { skill: "论文复现", courses: ["深度学习", "自然语言处理"], competitions: ["“挑战杯”全国大学生课外学术科技作品竞赛"], projects: ["实验室科研课题"], internships: [], gap_note: "从中文顶刊综述入手，先复现公开代码再改模型。" },
    ],
    frontend: [
      { skill: "JavaScript", courses: ["Web开发技术"], competitions: ["中国大学生计算机设计大赛"], projects: ["个人博客/作品集网站", "微信小程序应用"], internships: ["Web前端实习生·大二暑假"], gap_note: "" },
      { skill: "HTML/CSS", courses: ["Web开发技术"], competitions: ["中国大学生计算机设计大赛"], projects: ["个人博客/作品集网站"], internships: ["Web前端实习生·大二暑假"], gap_note: "课内只讲基础布局，Flex/Grid 与响应式需自学。" },
      { skill: "Vue", courses: ["Web开发技术"], competitions: [], projects: ["校园二手交易平台（全栈）"], internships: ["Web前端实习生·大二暑假"], gap_note: "课程不涉及框架，建议官方文档+项目各过一遍。" },
      { skill: "React", courses: [], competitions: [], projects: ["个人博客/作品集网站（React 重构）"], internships: ["前端开发实习生·大三暑假"], gap_note: "培养方案完全未覆盖，投 React 岗前至少完成一个完整项目。" },
      { skill: "TypeScript", courses: [], competitions: [], projects: ["校园二手交易平台（TS 重构）"], internships: ["前端开发实习生·大三暑假"], gap_note: "在 Vue/React 项目里顺手切换到 TS，成本最低。" },
      { skill: "浏览器原理", courses: ["计算机网络"], competitions: [], projects: [], internships: [], gap_note: "结合《高性能浏览器》类资料自学，面试高频。" },
      { skill: "Git", courses: ["软件工程"], competitions: [], projects: ["开源贡献（good first issue 起步）"], internships: [], gap_note: "" },
      { skill: "沟通能力", courses: ["软件工程综合实践"], competitions: ["中国大学生计算机设计大赛"], projects: ["校园二手交易平台（全栈）"], internships: [], gap_note: "" },
    ],
    data: [
      { skill: "SQL", courses: ["数据库系统"], competitions: [], projects: ["网络爬虫与数据分析报告"], internships: ["数据分析实习生·大二暑假起均可投"], gap_note: "窗口函数与复杂 JOIN 课内讲得浅，刷 SQL 题库补齐。" },
      { skill: "Python", courses: ["数据挖掘", "机器学习"], competitions: ["Kaggle数据科学竞赛"], projects: ["网络爬虫与数据分析报告"], internships: ["数据分析实习生·大三暑假"], gap_note: "" },
      { skill: "统计学", courses: ["概率论与数理统计"], competitions: ["全国大学生数学建模竞赛（高教社杯）", "美国大学生数学建模竞赛（MCM/ICM）"], projects: [], internships: [], gap_note: "AB 实验设计课内没有，建议自学 + 在分析报告里实践。" },
      { skill: "数据可视化", courses: ["数值计算方法"], competitions: ["全国大学生数学建模竞赛（高教社杯）"], projects: ["网络爬虫与数据分析报告"], internships: ["数据分析实习生·大三暑假"], gap_note: "Tableau/FineBI 培养方案不覆盖，用开源库（Matplotlib/ECharts）入门即可。" },
      { skill: "Pandas", courses: ["数据挖掘"], competitions: ["Kaggle数据科学竞赛"], projects: ["网络爬虫与数据分析报告"], internships: [], gap_note: "" },
      { skill: "Hive", courses: ["大数据技术"], competitions: ["CCF大数据与计算智能大赛（BDCI）"], projects: [], internships: ["数据分析师·大三暑假"], gap_note: "选修课在大三下，想提前接触可先用 Docker 本地搭环境。" },
      { skill: "业务理解", courses: [], competitions: ["“挑战杯”全国大学生课外学术科技作品竞赛"], projects: ["网络爬虫与数据分析报告"], internships: ["数据分析实习生·大二暑假"], gap_note: "多读行业分析报告，实习面试时能讲出业务指标怎么拆。" },
      { skill: "沟通能力", courses: ["软件工程综合实践"], competitions: [], projects: [], internships: ["数据分析实习生·大二暑假"], gap_note: "" },
    ],
  };

  var MAPPINGS_DEFAULT = MAPPINGS_LIBRARY.backend;

  /** 按岗位关键词返回 CourseMapping[] 演示数据（本前端无对应真实端点，始终标注为内置知识库）。 */
  function mappings(keyword) {
    var kw = String(keyword || "").toLowerCase();
    if (kw.indexOf("算法") !== -1 || kw.indexOf("机器学习") !== -1 || kw === "ai" || kw.indexOf("深度学习") !== -1) return MAPPINGS_LIBRARY.algo;
    if (kw.indexOf("前端") !== -1 || kw.indexOf("web") !== -1 || kw === "h5") return MAPPINGS_LIBRARY.frontend;
    if (kw.indexOf("数据") !== -1 || kw.indexOf("分析") !== -1) return MAPPINGS_LIBRARY.data;
    return MAPPINGS_DEFAULT;
  }

  // ------------------------------------------------------------------
  // ④ plan 演示数据：Roadmap（完整 8 学期模板，从当前学期截取）
  // ------------------------------------------------------------------

  var PLAN_TEMPLATE = {
    job: [
      { focus: "打牢程序设计基础，适应大学节奏", courses: ["程序设计基础（C语言）", "高等数学I"], actions: ["完成 C 语言入门 100 题", "加入一个技术社团或实验室兴趣组", "学会用 Git 管理自己的代码"], milestone: "能独立写出结构清晰的百行级 C 程序", hours: 8 },
      { focus: "补齐数学与数据结构前置", courses: ["高等数学II", "线性代数"], actions: ["洛谷/LeetCode 数组与字符串专题 ≥50 题", "建立自己的第一个 GitHub 仓库", "找一位学长学姐做方向访谈"], milestone: "GitHub 有连续提交记录", hours: 10 },
      { focus: "数据结构与面向对象，初定技术方向", courses: ["数据结构", "面向对象程序设计（Java）", "离散数学I"], actions: ["LeetCode 累计 150 题", "完成数据结构课程设计并写项目文档", "对照目标岗位 JD 列出技能差距清单"], milestone: "数据结构课程设计成绩良好以上", hours: 12 },
      { focus: "数据库与 Web 基础，做出第一个完整项目", courses: ["数据库系统", "Web开发技术"], actions: ["完成「个人博客/作品集网站」并部署上线", "报名蓝桥杯练手（4 月赛程）", "简历初稿完成并请人复盘"], milestone: "作品集网站可公网访问", hours: 14 },
      { focus: "核心专业课 + 冲刺第一段技术实习", courses: ["操作系统", "算法设计与分析"], actions: ["投递日常实习（小公司/校内基地门槛友好）", "整理操作系统与网络高频八股", "每周 3 道算法题保持手感"], milestone: "拿到一段技术实习 offer 或进入终面", hours: 16 },
      { focus: "实习黄金窗口：以转正为目标", courses: ["计算机网络", "软件工程"], actions: ["进入目标方向日常实习", "参与开源项目并提交 ≥3 个 PR", "把实习产出沉淀成简历条目"], milestone: "实习评价可转正或获得明确背书", hours: 18 },
      { focus: "秋招冲刺：把项目与实习讲成故事", courses: ["生产实习", "毕业设计（开题）"], actions: ["8 月起投递秋招，目标 30+ 家", "每周复盘面试题并回填简历", "毕设选题贴合目标岗位"], milestone: "收获 ≥2 个意向 offer", hours: 20 },
      { focus: "毕业设计收尾 + 入职准备无缝衔接", courses: ["毕业设计"], actions: ["毕设答辩通过", "提前学习入职团队的技术栈", "整理大学技术资产（仓库/文档/博客）"], milestone: "签约落地，平稳毕业", hours: 12 },
    ],
    kaoyan: [
      { focus: "打牢程序设计与数学底子", courses: ["程序设计基础（C语言）", "高等数学I"], actions: ["C 语言入门 100 题", "高数同步刷题，建立错题本"], milestone: "高数期末 85+ 且错题本成体系", hours: 9 },
      { focus: "数学主线不断，兼顾程序能力", courses: ["高等数学II", "线性代数"], actions: ["线代习题册全刷", "用 C 完成一个小工具（如成绩统计）"], milestone: "数学两学期平均分 85+", hours: 11 },
      { focus: "数据结构与专业方向探索", courses: ["数据结构", "面向对象程序设计（Java）", "离散数学I"], actions: ["确定考研目标院校池（3 所）", "LeetCode 累计 100 题维持手感"], milestone: "目标院校与专业方向书面确定", hours: 12 },
      { focus: "数据库与概率论：408/数学双线铺垫", courses: ["数据库系统", "概率论与数理统计"], actions: ["概率论习题全刷", "了解目标院校 408/自命题差异"], milestone: "概率论期末 85+，院校清单定稿", hours: 13 },
      { focus: "考研一轮启动：数学 + 专业课同步", courses: ["操作系统", "算法设计与分析"], actions: ["数学一轮复习（高数/线代/概率）", "408 数据结构+操作系统一轮", "暂停实习计划，保留一个课程项目"], milestone: "一轮习题正确率 ≥70%", hours: 18 },
      { focus: "考研一轮收尾 + 二轮启动", courses: ["计算机网络", "计算机组成原理"], actions: ["408 计网+组成原理一轮", "数学二轮专题突破", "收集目标院校复试线与真题"], milestone: "408 四门一轮完成", hours: 20 },
      { focus: "考研冲刺：真题为主", courses: ["毕业设计（开题）"], actions: ["政治+英语真题冲刺", "408 二轮错题复盘", "9 月研招网报名，12 月初试"], milestone: "完成初试并估分对齐复试线", hours: 22 },
      { focus: "复试与毕设双线推进", courses: ["毕业设计"], actions: ["复试机试+面试准备", "联系导师并准备简历与成绩单", "毕设选题兼顾复试方向"], milestone: "收到拟录取通知", hours: 15 },
    ],
  };

  function hoursFor(base, weeklyHours) {
    // weekly_hours>0 时按比例缩放；0/缺省时用模板原值。下限 3h/周，上限 40h/周。
    if (!weeklyHours || weeklyHours <= 0) return Math.min(40, Math.max(3, base));
    var scaled = Math.round(base * (weeklyHours / 14));
    return Math.min(40, Math.max(3, scaled));
  }

  /**
   * 依据画像生成 Roadmap 演示数据（contract = POST /api/plan 返回体）。
   * 从画像当前学期截到「大四下」；大一上提交即得到完整 8 学期路线。
   */
  function plan(profile) {
    var p = profile || {};
    var name = p.name || "同学";
    var grade = p.grade || "大一上";
    var role = p.target_role || "Python后端";
    var path = p.path || "就业";
    var weekly = p.weekly_hours || 0;
    var skills = Array.isArray(p.skills) ? p.skills : [];

    var isKaoyan = path === "考研";
    var table = isKaoyan ? PLAN_TEMPLATE.kaoyan : PLAN_TEMPLATE.job;
    var startIndex = Math.max(0, TERMS.indexOf(grade));
    if (startIndex === -1) startIndex = 0;

    var semesters = [];
    for (var i = startIndex; i < TERMS.length; i++) {
      var t = table[i];
      semesters.push({
        term: TERMS[i],
        focus: t.focus,
        courses: t.courses.slice(),
        actions: t.actions.slice(),
        milestone: t.milestone,
        hours_per_week: hoursFor(t.hours, weekly),
      });
    }

    var summary =
      name + "，" + grade + "，目标「" + role + "」，路线：" + path +
      "；每周课外可投入约 " + (weekly > 0 ? weekly + " 小时" : "未定") +
      "。已有基础：" + (skills.length ? skills.join("、") : "暂无") + "。" +
      (p.notes ? "备注：" + p.notes : "");

    var risks = isKaoyan
      ? [
          "初试（12 月）与毕设开题重叠，需在大三下完成毕设选题调研。",
          "408 四门课与课内进度不同步，自学需占每周 6 小时以上。",
          "若目标院校复试线连年上涨，建议同步准备秋招兜底。",
        ]
      : [
          "大四上秋招与毕设开题重叠，9–11 月每周投入需提至 20 小时以上。",
          weekly > 0 && weekly < 10
            ? "当前每周投入 " + weekly + " 小时偏低，建议把「作品集项目」提前到大二上启动。"
            : "若每周投入低于 10 小时，作品集项目应提前一个学期启动。",
          "目标岗位未定：建议在大二下前完成一次岗位调研，再切换到专属路线。",
        ];

    return { profile_summary: summary, semesters: semesters, risks: risks };
  }

  // ------------------------------------------------------------------
  // ⑤ chat 演示回复：DialogueTurn 契约（reply + action + reason）
  // ------------------------------------------------------------------

  function chat(message) {
    var msg = String(message || "");
    if (/(考研|保研|读研|换方向|转方向|换岗位|转行|考公)/.test(msg)) {
      return {
        reply:
          "换到考研路线意味着大三下到大四上会被数学与 408 占满，现有路线里的实习和竞赛要让位。\n" +
          "建议这样过渡：① 本学期先保持算法题手感；② 下学期启动数学一轮；③ 暑假前完成目标院校调研。\n" +
          "需要的话，我可以按考研路线为你重新生成八学期规划。",
        action: "replan",
        reason: "消息表达了更换路线（考研）的意图",
      };
    }
    if (/(时间|小时|太忙|没空|减负|加量|投入)/.test(msg)) {
      return {
        reply:
          "每周可投入时间直接决定路线密度。少于 10 小时我会把项目类行动后移一个学期，优先保数据结构与课程进度；\n" +
          "多于 20 小时则会提前启动实习投递。告诉我你的新时长，我帮你核对各学期安排是否还成立。",
        action: "adjust_hours",
        reason: "消息涉及每周投入时长的调整",
      };
    }
    if (/(年级|大几|怎么做|从哪开始|不知道|迷茫)/.test(msg)) {
      return {
        reply:
          "先对齐两个信息我再给具体建议：① 你现在的年级和已修课程；② 目标岗位方向（Python后端/算法/前端/数据分析）。\n" +
          "有了这两项，我可以告诉你本学期最值得投入的两三件事，以及下学期的关键节点。",
        action: "clarify",
        reason: "缺少年级与目标岗位信息，无法给出具体规划",
      };
    }
    return {
      reply:
        "从当前路线图看，本学期优先级是：① 把核心课程绩点稳住（数据结构/操作系统是面试硬门槛）；\n" +
        "② 每周固定 3 道算法题保持手感；③ 用一个课程项目练工程化（Git、测试、文档）。\n" +
        "技能频率图里标「核心」的技能是目标岗位出现率最高的要求，优先补齐它们性价比最高。",
      action: "none",
      reason: "常规咨询，基于现有路线图给出建议",
    };
  }

  window.MOCK = {
    TERMS: TERMS,
    analyze: analyze,
    mappings: mappings,
    plan: plan,
    chat: chat,
  };
})();
