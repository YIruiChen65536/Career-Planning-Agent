/*
 * app.js — 职规 Agent 前端主逻辑
 *
 * 页面流：①画像表单 → POST /api/plan → ②分析页（技能频率图 + 映射表 + 八学期时间轴）→ ③SSE 对话面板
 * 降级纪律（硬要求）：任何 fetch 失败/非200/超时 → 自动切换 mock.js 内置演示数据并亮出「演示数据」角标，
 * 任何情况下不白屏、不因 JS 异常卡死。
 *
 * 超时策略：/api/plan 按任务约定可能 10–30 秒，给 60s 上限 + 进度反馈 + 可取消；
 * /api/chat 的首字节 = 服务端整段对话 LLM 跑完才开始流式回放，冷缓存要等数秒，
 * 故建连等待放宽到 30s（断网时 connection refused 依旧毫秒级失败，不影响离线演示）；
 * /api/analyze 同理放宽到 30s：语料多时冷缓存抽取可能超过 3s，太短会让真实数据被误降级成演示数据。
 */
(function () {
  "use strict";

  // ------------------------------------------------------------------
  // 配置
  // ------------------------------------------------------------------

  // 同源调用；联调后端时可用 ?api=http://127.0.0.1:8000 覆盖
  var API_BASE = (function () {
    try {
      return new URLSearchParams(window.location.search).get("api") || "";
    } catch (e) { return ""; }
  })();

  var TIMEOUT_PLAN_MS = 60000;      // /api/plan：真实链路 10–30s，留足余量，期间有进度条可取消
  var TIMEOUT_ANALYZE_MS = 30000;   // /api/analyze：冷缓存抽取 12 条 JD 可能 >3s，放宽避免真实数据被误降级
  var TIMEOUT_CHAT_CONNECT_MS = 30000; // /api/chat：TTFB = 服务端整轮对话跑完的时间（冷缓存数秒），30s 内等到首帧
  var CHAT_STREAM_MAX_MS = 120000;  // SSE 建连后整体上限

  var STORAGE_PROFILE = "careerAgent.profile.v1";
  var STORAGE_CHAT = "careerAgent.chat.v1";
  var CHAT_HISTORY_MAX = 60;
  var CHAT_HISTORY_SEND = 12;     // 每轮随请求上送的近期消息条数（服务端上限 32）
  // 与后端 schemas.UNNAMED_PROFILE_NAME 逐字一致：姓名留空时按默认档案名建档/寻址，
  // 双方各写一个字面量（前端拿不到 Python 常量），改其一必须同步另一个
  var DEFAULT_PROFILE_NAME = "未命名学生";

  var TERMS = (window.MOCK && window.MOCK.TERMS) ||
    ["大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上", "大四下"];
  var QUICK_ROLES = ["Python后端", "算法工程师", "前端", "数据分析"];
  var SKILL_SUGGESTIONS = ["Python", "C/C++", "Java", "SQL", "Git", "HTML/CSS"];
  var CAT_CN = { hard: "硬技能", tool: "工具", soft: "软技能" };

  // ------------------------------------------------------------------
  // 状态
  // ------------------------------------------------------------------

  var state = {
    view: "home",
    profile: null,        // 最近一次提交的画像
    demoReasons: [],      // 降级原因清单（驱动角标与横幅）
    planAbort: null,      // 生成中的 AbortController
    loading: null,        // 加载遮罩计时器句柄
    formSkills: [],       // 标签输入里的技能
    chat: {
      open: false,
      busy: false,
      history: [],        // [{role:"user"|"assistant", content, demo?}]
    },
  };

  // ------------------------------------------------------------------
  // 工具
  // ------------------------------------------------------------------

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function svgEl(tag, attrs) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function storageGet(key, fallback) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }

  function storageSet(key, value) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 隐私模式下静默 */ }
  }

  var toastTimer = null;
  function toast(msg) {
    var node = $("toast");
    node.textContent = msg;
    node.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.hidden = true; }, 3600);
  }

  function mockReady() { return !!(window.MOCK && typeof window.MOCK.plan === "function"); }

  // ------------------------------------------------------------------
  // 降级演示模式
  // ------------------------------------------------------------------

  function resetDemo() {
    state.demoReasons = [];
    updateDemoUI();
  }

  function markDemo(section, detail) {
    var label = { plan: "路线规划", analyze: "岗位分析", chat: "实时对话" }[section] || section;
    state.demoReasons.push(label + "：" + detail);
    updateDemoUI();
  }

  function updateDemoUI() {
    var has = state.demoReasons.length > 0;
    $("demo-badge").hidden = !has;
    $("demo-banner").hidden = !has;
    if (has) {
      var unique = [];
      state.demoReasons.forEach(function (r) {
        if (unique.indexOf(r) === -1) unique.push(r);
      });
      $("demo-banner-reason").textContent = unique.join("；") + "。";
    }
  }

  function setSourceTag(id, src) {
    var node = $(id);
    node.dataset.src = src;
    node.textContent = { real: "真实数据", mock: "演示数据", builtin: "内置知识库", pending: "数据源待定" }[src] || src;
  }

  // ------------------------------------------------------------------
  // 网络层：带超时的 fetch + 错误归类
  // ------------------------------------------------------------------

  function fetchJSON(path, options, timeoutMs, externalSignal) {
    var ctrl = new AbortController();
    var timedOut = false;
    var timer = setTimeout(function () {
      timedOut = true;
      ctrl.abort();
    }, timeoutMs);

    function abortFromOutside() { ctrl.abort(); }
    if (externalSignal) {
      if (externalSignal.aborted) abortFromOutside();
      else externalSignal.addEventListener("abort", abortFromOutside);
    }

    var opts = Object.assign({}, options || {}, { signal: ctrl.signal });

    return fetch(API_BASE + path, opts).then(
      function (res) {
        clearTimeout(timer);
        if (!res.ok) {
          // 带出服务端错误详情（如 503 的"LLM 不可用：…"），让降级横幅能说明真实原因
          return res
            .json()
            .catch(function () { return null; })
            .then(function (body) {
              var err = new Error("HTTP " + res.status);
              err.kind = "http";
              err.status = res.status;
              var detail = body && typeof body.detail === "string" ? body.detail : "";
              if (detail) err.detail = detail;
              throw err;
            });
        }
        return res.json().catch(function () {
          var err = new Error("响应不是合法 JSON");
          err.kind = "parse";
          throw err;
        });
      },
      function (e) {
        clearTimeout(timer);
        throw classifyFetchError(e, timedOut);
      }
    );
  }

  function classifyFetchError(e, timedOut) {
    if (e && e.kind) return e; // 已归类
    if (e && e.name === "AbortError") {
      if (timedOut) return makeErr("timeout", "请求超时");
      return makeErr("cancelled", "已取消");
    }
    return makeErr("network", "网络不可达或服务未启动");
  }

  function makeErr(kind, message) {
    var err = new Error(message);
    err.kind = kind;
    return err;
  }

  function describeErr(err) {
    if (!err) return "未知错误";
    var base;
    switch (err.kind) {
      case "timeout": base = "等待超时"; break;
      case "http": base = "服务返回 " + err.status; break;
      case "parse": base = "响应格式异常"; break;
      case "cancelled": base = "已取消"; break;
      default: base = "网络不可达";
    }
    // 服务端透出的原因（如"LLM 不可用：请检查 .env 配置"）对排查最有价值，截短附在后面
    if (err.detail) base += "（" + String(err.detail).slice(0, 120) + "）";
    return base;
  }

  function loadPlan(profile, signal) {
    return fetchJSON("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    }, TIMEOUT_PLAN_MS, signal);
  }

  function loadAnalyze(keyword, signal) {
    var kw = encodeURIComponent(String(keyword || ""));
    return fetchJSON("/api/analyze/" + kw + "?limit=12", { method: "GET" }, TIMEOUT_ANALYZE_MS, signal);
  }

  // ------------------------------------------------------------------
  // 视图切换
  // ------------------------------------------------------------------

  function showView(name) {
    state.view = name;
    $("view-home").hidden = name !== "home";
    $("view-analysis").hidden = name !== "analysis";
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  // ------------------------------------------------------------------
  // 表单：年级 / 快捷岗位 / 技能标签 / 小时滑杆
  // ------------------------------------------------------------------

  function initForm() {
    var gradeSel = $("f-grade");
    TERMS.forEach(function (t) {
      var opt = el("option", null, t);
      opt.value = t;
      gradeSel.appendChild(opt);
    });
    gradeSel.value = "大二上";

    QUICK_ROLES.forEach(function (role) {
      var chip = el("button", "chip", role);
      chip.type = "button";
      chip.addEventListener("click", function () {
        $("f-role").value = role;
        $("f-role").focus();
      });
      $("role-chips").appendChild(chip);
    });

    SKILL_SUGGESTIONS.forEach(function (s) {
      var chip = el("button", "chip", "+ " + s);
      chip.type = "button";
      chip.addEventListener("click", function () {
        addSkill(s);
        $("f-skill-input").focus();
      });
      $("skill-suggest").appendChild(chip);
    });

    var skillInput = $("f-skill-input");
    skillInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === "," || ev.key === "，" || ev.key === ";" || ev.key === "；") {
        ev.preventDefault();
        addSkill(skillInput.value);
      } else if (ev.key === "Backspace" && !skillInput.value && state.formSkills.length) {
        removeSkill(state.formSkills.length - 1);
      }
    });
    skillInput.addEventListener("blur", function () { addSkill(skillInput.value); });

    var hours = $("f-hours");
    var syncHours = function () {
      var v = Number(hours.value);
      $("f-hours-display").textContent = String(v);
      hours.style.setProperty("--fill", (v / 40) * 100 + "%");
    };
    hours.addEventListener("input", syncHours);
    syncHours();
  }

  function addSkill(raw) {
    var input = $("f-skill-input");
    var name = String(raw || input.value || "").trim().replace(/[,，;；]+$/, "");
    if (!name) return;
    if (state.formSkills.some(function (s) { return s === name; })) {
      input.value = "";
      return;
    }
    if (state.formSkills.length >= 12) {
      toast("技能最多添加 12 个");
      input.value = "";
      return;
    }
    state.formSkills.push(name);
    input.value = "";
    renderSkillTags();
  }

  function removeSkill(idx) {
    state.formSkills.splice(idx, 1);
    renderSkillTags();
  }

  function renderSkillTags() {
    var list = $("skill-tags");
    list.textContent = "";
    state.formSkills.forEach(function (s, i) {
      var li = el("li", "tag");
      li.appendChild(el("span", null, s));
      var x = el("button", "tag-x", "×");
      x.type = "button";
      x.setAttribute("aria-label", "移除技能 " + s);
      x.addEventListener("click", function () { removeSkill(i); });
      li.appendChild(x);
      list.appendChild(li);
    });
  }

  function readProfile() {
    return {
      name: $("f-name").value.trim(),
      grade: $("f-grade").value,
      target_role: $("f-role").value.trim(),
      path: (document.querySelector('input[name="path"]:checked') || {}).value || "就业",
      skills: state.formSkills.slice(),
      weekly_hours: Number($("f-hours").value) || 0,
      notes: $("f-notes").value.trim(),
    };
  }

  function prefillProfile(profile) {
    if (!profile) return;
    if (profile.name) $("f-name").value = profile.name;
    if (profile.grade && TERMS.indexOf(profile.grade) !== -1) $("f-grade").value = profile.grade;
    if (profile.target_role) $("f-role").value = profile.target_role;
    if (Array.isArray(profile.skills)) {
      state.formSkills = profile.skills.filter(function (s) { return typeof s === "string" && s; }).slice(0, 12);
      renderSkillTags();
    }
    if (typeof profile.weekly_hours === "number") {
      $("f-hours").value = String(Math.min(40, Math.max(0, profile.weekly_hours)));
      $("f-hours").dispatchEvent(new Event("input"));
    }
    if (profile.path) {
      var radio = document.querySelector('input[name="path"][value="' + profile.path + '"]');
      if (radio) radio.checked = true;
    }
    if (profile.notes) $("f-notes").value = profile.notes;
  }

  // ------------------------------------------------------------------
  // 生成流程：loading 反馈 + plan/analyze 并行 + 失败降级
  // ------------------------------------------------------------------

  var STAGES = [
    [0, "已提交画像，等待后端规划…"],
    [3, "AI 正在解析目标岗位的招聘要求…"],
    [10, "正在规划八学期成长路线…（真实接口约需 10–30 秒）"],
    [26, "快好了——复杂画像会稍慢，可继续等待或取消。"],
  ];

  function startLoading() {
    var overlay = $("loading-overlay");
    var fill = $("loading-fill");
    var stage = $("loading-stage");
    var elapsedNode = $("loading-elapsed");
    var t0 = Date.now();

    overlay.hidden = false;
    fill.style.width = "0%";

    function tick() {
      var sec = Math.round((Date.now() - t0) / 1000);
      var pct = 95 * (1 - Math.exp(-sec / 9)); // 渐近 95%，完成时直接拉满
      fill.style.width = Math.min(95, pct) + "%";
      elapsedNode.textContent = "已等待 " + sec + " 秒";
      for (var i = STAGES.length - 1; i >= 0; i--) {
        if (sec >= STAGES[i][0]) { stage.textContent = STAGES[i][1]; break; }
      }
    }
    tick();
    var timer = setInterval(tick, 250);
    state.loading = { timer: timer, t0: t0 };
  }

  function finishLoading() {
    if (state.loading) clearInterval(state.loading.timer);
    state.loading = null;
    $("loading-fill").style.width = "100%";
    var overlay = $("loading-overlay");
    setTimeout(function () { overlay.hidden = true; }, 180);
  }

  function cancelPlan() {
    if (state.planAbort) state.planAbort.abort();
  }

  function generateRoadmap(profile) {
    state.profile = profile;
    storageSet(STORAGE_PROFILE, profile);
    resetDemo();
    startLoading();

    var ctrl = new AbortController();
    state.planAbort = ctrl;

    var planPromise = loadPlan(profile, ctrl.signal).then(
      function (data) { return { data: data, mock: false }; },
      function (err) {
        if (err.kind === "cancelled") throw err;
        markDemo("plan", describeErr(err) + "，已使用演示路线");
        return { data: mockReady() ? window.MOCK.plan(profile) : emptyRoadmap(), mock: true };
      }
    );

    var analyzePromise = loadAnalyze(profile.target_role, ctrl.signal).then(
      function (data) { return { data: data, mock: false }; },
      function (err) {
        if (err.kind === "cancelled") throw err;
        markDemo("analyze", describeErr(err) + "，技能频率为演示数据");
        return { data: mockReady() ? window.MOCK.analyze(profile.target_role) : emptyAnalyze(), mock: true };
      }
    );

    function settle(planRes, analyzeRes) {
      finishLoading();
      state.planAbort = null;

      var cancelled = planRes === "cancelled" || analyzeRes === "cancelled";
      var planOut = planRes;
      var analyzeOut = analyzeRes;
      if (planRes === "cancelled") {
        // 取消后也不允许白屏：同样落到演示数据，只是角标要如实标注
        markDemo("plan", "已取消等待，使用演示路线");
        planOut = { data: mockReady() ? window.MOCK.plan(profile) : emptyRoadmap(), mock: true };
      }
      if (analyzeRes === "cancelled") {
        markDemo("analyze", "已取消等待，技能频率为演示数据");
        analyzeOut = { data: mockReady() ? window.MOCK.analyze(profile.target_role) : emptyAnalyze(), mock: true };
      }
      if (cancelled) toast("已取消等待，当前展示演示数据");

      renderAnalysis(profile, planOut, analyzeOut);
      showView("analysis");
    }

    var planDone = false, analyzeDone = false, planVal = null, analyzeVal = null;
    planPromise.then(
      function (v) { planDone = true; planVal = v; if (analyzeDone) settle(planVal, analyzeVal); },
      function (err) {
        if (err.kind !== "cancelled") err = makeErr("network", "规划失败");
        planDone = true; planVal = "cancelled";
        // 取消后 analyze 继续等没有意义，也一并断掉
        if (!analyzeDone) ctrl.abort();
        if (analyzeDone) settle(planVal, analyzeVal);
      }
    );
    analyzePromise.then(
      function (v) { analyzeDone = true; analyzeVal = v; if (planDone) settle(planVal, analyzeVal); },
      function (err) {
        if (err.kind !== "cancelled") err = makeErr("network", "分析失败");
        analyzeDone = true; analyzeVal = "cancelled";
        if (planDone) settle(planVal, analyzeVal);
      }
    );
  }

  function emptyRoadmap() {
    return { profile_summary: "", semesters: [], risks: [] };
  }

  function emptyAnalyze() {
    return { postings: [], skills: [], errors: [] };
  }

  function onSubmitForm(ev) {
    ev.preventDefault();
    var profile = readProfile();
    if (!profile.target_role) {
      var tip = $("form-error");
      tip.textContent = "请先填写目标岗位，或点击下方快捷项。";
      tip.hidden = false;
      $("f-role").focus();
      return;
    }
    $("form-error").hidden = true;
    var btn = $("btn-submit");
    btn.disabled = true;
    generateRoadmap(profile);
    // generateRoadmap 结束时会清掉 loading；轮询据此恢复按钮（120s 兜底防泄漏）
    var waited = 0;
    var poll = setInterval(function () {
      waited += 300;
      if (!state.loading || waited > 120000) { clearInterval(poll); btn.disabled = false; }
    }, 300);
  }

  // ------------------------------------------------------------------
  // 分析页渲染
  // ------------------------------------------------------------------

  function renderAnalysis(profile, planRes, analyzeRes) {
    renderProfileBar(profile);
    renderChart(analyzeRes.data, analyzeRes.mock);
    renderMappings(profile.target_role);
    renderTimeline(planRes.data, planRes.mock);
    updateDemoUI();
  }

  function renderProfileBar(profile) {
    var bar = $("profile-bar");
    bar.textContent = "";

    function item(label, value, cls) {
      var wrap = el("div", "pb-item");
      wrap.appendChild(el("span", "pb-label", label));
      wrap.appendChild(el("span", "pb-value" + (cls ? " " + cls : ""), value || "未填"));
      return wrap;
    }

    bar.appendChild(item("姓名", profile.name, "pb-name"));
    bar.appendChild(item("年级", profile.grade));
    bar.appendChild(item("目标岗位", profile.target_role));
    bar.appendChild(item("路线", profile.path));
    bar.appendChild(item("每周投入", profile.weekly_hours + " 小时"));

    var skillsWrap = el("div", "pb-item");
    skillsWrap.appendChild(el("span", "pb-label", "已有技能"));
    var tagWrap = el("span", "pb-skills");
    if (profile.skills && profile.skills.length) {
      profile.skills.forEach(function (s) { tagWrap.appendChild(el("span", "pb-skill", s)); });
    } else {
      tagWrap.appendChild(el("span", null, "暂无"));
    }
    skillsWrap.appendChild(tagWrap);
    bar.appendChild(skillsWrap);
  }

  // ---------- SVG 条形图（原生手写） ----------

  function renderChart(analyzeData, isMock) {
    setSourceTag("chart-source-tag", isMock ? "mock" : "real");

    var skills = (analyzeData && Array.isArray(analyzeData.skills)) ? analyzeData.skills : [];
    var postings = (analyzeData && Array.isArray(analyzeData.postings)) ? analyzeData.postings : [];
    var errors = (analyzeData && Array.isArray(analyzeData.errors)) ? analyzeData.errors : [];

    var sub = $("chart-subtitle");
    var jdCount = postings.length;
    var extra = errors.length ? "（另有 " + errors.length + " 条 JD 解析失败）" : "";
    sub.textContent = skills.length
      ? "基于 " + jdCount + " 条「" + (state.profile ? state.profile.target_role : "") + "」方向招聘 JD 的统计" + extra +
        "，按出现条数降序；颜色区分技能类别，淡色为非核心，右侧「核心」= 出现率达标。"
      : "暂无技能统计数据。";

    var legend = $("chart-legend");
    legend.textContent = "";
    [["c-hard", "硬技能"], ["c-tool", "工具/框架"], ["c-soft", "软技能"], ["c-dim", "淡色 = 非核心"]].forEach(function (pair) {
      var item = el("span", "legend-item");
      var swatch = el("span", "legend-swatch " + pair[0]);
      item.appendChild(swatch);
      item.appendChild(el("span", null, pair[1]));
      legend.appendChild(item);
    });

    var mount = $("chart-mount");
    mount.textContent = "";

    if (!skills.length) {
      mount.appendChild(el("p", "chart-empty", "该岗位暂无可统计的技能数据，试试更换目标岗位关键词。"));
      return;
    }

    var top = skills.slice().sort(function (a, b) { return b.frequency - a.frequency; }).slice(0, 12);
    var max = Math.max.apply(null, top.map(function (s) { return s.frequency; }));

    var W = 720, ROW_H = 32, GAP = 6, LABEL_W = 132, RIGHT_W = 52, PLOT_TOP = 6;
    var plotW = W - LABEL_W - RIGHT_W;
    var H = PLOT_TOP * 2 + top.length * (ROW_H + GAP) - GAP;

    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
    svg.setAttribute("aria-label", "岗位技能频率条形图");

    var bars = [];
    top.forEach(function (s, i) {
      var y = PLOT_TOP + i * (ROW_H + GAP);
      var barW = Math.max(6, Math.round((s.frequency / max) * plotW));
      var catColor = { hard: "#0E7A6F", tool: "#4A6B80", soft: "#B45309" }[s.category] || "#4A6B80";

      var row = svgEl("g", { class: "chart-row" });
      var title = svgEl("title", {});
      title.textContent = s.skill + "｜" + (CAT_CN[s.category] || "技能") +
        "｜出现 " + s.frequency + " 条 JD" + (s.is_core ? "（核心要求）" : "") +
        (s.aliases && s.aliases.length ? "｜别名：" + s.aliases.join("、") : "");
      row.appendChild(title);

      var label = svgEl("text", {
        x: LABEL_W - 10, y: y + ROW_H / 2 + 4.5,
        "text-anchor": "end", class: "chart-label" + (s.is_core ? "" : " dim"),
      });
      label.textContent = String(s.skill).slice(0, 12);
      row.appendChild(label);

      var track = svgEl("rect", { x: LABEL_W, y: y + 10, width: plotW, height: 12, rx: 6, class: "chart-bar-bg", fill: "#EEF3F2" });
      row.appendChild(track);

      var bar = svgEl("rect", {
        x: LABEL_W, y: y + 10, width: barW, height: 12, rx: 6,
        class: "chart-bar", fill: catColor, opacity: s.is_core ? "1" : "0.38",
      });
      row.appendChild(bar);
      bars.push(bar);

      var value = svgEl("text", {
        x: LABEL_W + barW + 8, y: y + ROW_H / 2 + 4,
        class: "chart-value",
      });
      value.textContent = s.frequency;
      row.appendChild(value);

      if (s.is_core) {
        var coreTag = svgEl("text", { x: W - 4, y: y + ROW_H / 2 + 4, "text-anchor": "end", class: "chart-coretag" });
        coreTag.textContent = "核心";
        row.appendChild(coreTag);
      }

      svg.appendChild(row);
    });

    mount.appendChild(svg);
    // 下一帧再展开动画（transition 需要）；隐藏标签页里 rAF 不触发，超时兜底直接显示
    var reveal = function () { bars.forEach(function (b) { b.classList.add("in"); }); };
    requestAnimationFrame(function () { requestAnimationFrame(reveal); });
    setTimeout(reveal, 900);
  }

  // ---------- 映射表 ----------

  function renderMappings(role) {
    setSourceTag("map-source-tag", "builtin");
    var tbody = $("map-body");
    tbody.textContent = "";

    var mappings = mockReady() ? window.MOCK.mappings(role) : [];
    if (!mappings.length) {
      var tr0 = el("tr");
      var td0 = el("td", null, "暂无映射数据");
      td0.colSpan = 5;
      tr0.appendChild(td0);
      tbody.appendChild(tr0);
      return;
    }

    mappings.forEach(function (m) {
      var tr = el("tr");

      var tdSkill = el("td");
      var nameLine = el("div", "map-skill");
      nameLine.textContent = m.skill;
      var cat = (m.category && CAT_CN[m.category]) ? m.category : null;
      if (cat) {
        var catTag = el("span", "map-cat " + cat, CAT_CN[cat]);
        nameLine.appendChild(catTag);
      }
      tdSkill.appendChild(nameLine);
      if (m.gap_note) tdSkill.appendChild(el("p", "map-gap", "提示：" + m.gap_note));
      tr.appendChild(tdSkill);

      tr.appendChild(listCell(m.courses));
      tr.appendChild(listCell(m.competitions));
      tr.appendChild(listCell(m.projects));
      tr.appendChild(listCell(m.internships));

      tbody.appendChild(tr);
    });
  }

  function listCell(items) {
    var td = el("td");
    if (Array.isArray(items) && items.length) {
      var ul = el("ul", "map-list");
      items.forEach(function (it) { ul.appendChild(el("li", null, it)); });
      td.appendChild(ul);
    } else {
      td.appendChild(el("span", "map-none", "—"));
    }
    return td;
  }

  // ---------- 八学期时间轴 ----------

  function renderTimeline(roadmap, isMock) {
    setSourceTag("plan-source-tag", isMock ? "mock" : "real");

    var data = roadmap || {};
    var semesters = Array.isArray(data.semesters) ? data.semesters : [];
    var risks = Array.isArray(data.risks) ? data.risks : [];

    $("plan-summary").textContent = data.profile_summary || "";

    var risksCard = $("risks-card");
    var risksList = $("risks-list");
    risksList.textContent = "";
    if (risks.length) {
      risks.forEach(function (r) { risksList.appendChild(el("li", null, r)); });
      risksCard.hidden = false;
    } else {
      risksCard.hidden = true;
    }

    var ol = $("timeline");
    ol.textContent = "";

    if (!semesters.length) {
      var tip = el("li", "chart-empty", "暂无学期规划数据。");
      ol.appendChild(tip);
      return;
    }

    semesters.forEach(function (s, i) {
      var li = el("li", "tl-item");
      li.appendChild(el("span", "tl-station", String(i + 1)));

      var card = el("div", "tl-card");

      var head = el("div", "tl-head");
      head.appendChild(el("h3", "tl-term", s.term || "第 " + (i + 1) + " 学期"));
      head.appendChild(el("span", "tl-hours", (s.hours_per_week || 0) + " 小时/周"));
      card.appendChild(head);

      if (s.focus) card.appendChild(el("p", "tl-focus", s.focus));

      if (Array.isArray(s.courses) && s.courses.length) {
        var courses = el("div", "tl-courses");
        s.courses.forEach(function (c) { courses.appendChild(el("span", "tl-course", c)); });
        card.appendChild(courses);
      }

      if (Array.isArray(s.actions) && s.actions.length) {
        var actions = el("ul", "tl-actions");
        s.actions.forEach(function (a) { actions.appendChild(el("li", null, a)); });
        card.appendChild(actions);
      }

      if (s.milestone) {
        var ms = el("div", "tl-milestone");
        ms.appendChild(el("b", null, "里程碑"));
        ms.appendChild(el("span", null, s.milestone));
        card.appendChild(ms);
      }

      li.appendChild(card);
      ol.appendChild(li);
    });
  }

  // ------------------------------------------------------------------
  // 对话面板
  // ------------------------------------------------------------------

  function currentProfileName() {
    if (state.profile && state.profile.name) return state.profile.name;
    var stored = storageGet(STORAGE_PROFILE, null);
    return (stored && stored.name) || DEFAULT_PROFILE_NAME;
  }

  function chatHistoryForRequest() {
    // 本轮 user 消息在 submitChat 里已 push，先去掉；再取最近 N 条随请求上送，
    // 让服务端 run_dialogue 拼进 prompt（多轮记忆），不再只存在本地做渲染
    return state.chat.history.slice(0, -1).slice(-CHAT_HISTORY_SEND)
      .map(function (m) {
        return { role: m.role === "assistant" ? "assistant" : "user", content: String(m.content || "") };
      });
  }

  function initChat() {
    state.chat.history = storageGet(STORAGE_CHAT, []);
    if (!Array.isArray(state.chat.history)) state.chat.history = [];
    renderHistory();

    $("btn-open-chat").addEventListener("click", openChat);
    $("chat-fab").addEventListener("click", openChat);
    $("btn-chat-close").addEventListener("click", closeChat);
    $("btn-chat-clear").addEventListener("click", clearChat);

    var form = $("chat-form");
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      submitChat();
    });

    var input = $("chat-input");
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        submitChat();
      }
    });
    input.addEventListener("input", function () {
      input.style.height = "auto";
      input.style.height = Math.min(110, input.scrollHeight) + "px";
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && state.chat.open) closeChat();
    });

    $("chat-fab").hidden = false;
  }

  function openChat() {
    state.chat.open = true;
    $("chat-panel").classList.add("open");
    $("chat-panel").setAttribute("aria-hidden", "false");
    $("chat-fab").hidden = true;
    scrollChatToBottom(false);
    $("chat-input").focus();
  }

  function closeChat() {
    state.chat.open = false;
    $("chat-panel").classList.remove("open");
    $("chat-panel").setAttribute("aria-hidden", "true");
    $("chat-fab").hidden = false;
  }

  function clearChat() {
    state.chat.history = [];
    storageSet(STORAGE_CHAT, []);
    renderHistory();
    toast("对话记录已清空");
  }

  function renderHistory() {
    var box = $("chat-messages");
    box.textContent = "";
    if (!state.chat.history.length) {
      box.appendChild(el("p", "chat-empty-tip",
        "还没有对话。生成路线图后，可以问顾问：\n「大三下最该做什么？」「每周只有 8 小时怎么办？」「我想改考研路线。」"));
      return;
    }
    state.chat.history.forEach(function (m) {
      appendMessageNode(m.role, m.content, m.demo);
    });
    scrollChatToBottom(false);
  }

  function appendMessageNode(role, content, demo) {
    var wrap = el("div", "chat-msg " + (role === "user" ? "user" : "assistant"));
    var bubble = el("div", "chat-bubble");
    bubble.textContent = content;
    wrap.appendChild(bubble);
    var meta = el("div", "chat-meta");
    if (demo) meta.appendChild(el("span", "chat-demo-tag", "演示回复"));
    meta.appendChild(el("span", null, role === "user" ? "我" : "顾问"));
    wrap.appendChild(meta);
    $("chat-messages").appendChild(wrap);
    return wrap;
  }

  function scrollChatToBottom(smooth) {
    var box = $("chat-messages");
    try {
      box.scrollTo({ top: box.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    } catch (e) {
      box.scrollTop = box.scrollHeight;
    }
  }

  function saveChatHistory() {
    storageSet(STORAGE_CHAT, state.chat.history.slice(-CHAT_HISTORY_MAX));
  }

  function submitChat() {
    var input = $("chat-input");
    var text = input.value.trim();
    if (!text || state.chat.busy) return;
    input.value = "";
    input.style.height = "auto";

    state.chat.history.push({ role: "user", content: text });
    saveChatHistory();

    var empty = $("chat-messages").querySelector(".chat-empty-tip");
    if (empty) empty.remove();

    appendMessageNode("user", text, false);
    scrollChatToBottom(true);

    state.chat.busy = true;
    $("btn-chat-send").disabled = true;

    var wrap = el("div", "chat-msg assistant");
    var bubble = el("div", "chat-bubble");
    bubble.textContent = "";
    // 等待首帧的"正在思考"占位：真实链路服务端要跑完整轮对话才开始流式回放，空白等待体感像卡死
    var thinking = el("span", "chat-thinking");
    thinking.appendChild(el("span", "chat-thinking-dot"));
    thinking.appendChild(el("span", "chat-thinking-dot"));
    thinking.appendChild(el("span", "chat-thinking-dot"));
    thinking.appendChild(el("span", "chat-thinking-text", " 正在思考…"));
    bubble.appendChild(thinking);
    wrap.appendChild(bubble);
    var meta = el("div", "chat-meta");
    meta.appendChild(el("span", null, "顾问"));
    wrap.appendChild(meta);
    $("chat-messages").appendChild(wrap);
    scrollChatToBottom(true);

    var type = createTypewriter(bubble, function () { scrollChatToBottom(true); });
    var received = "";
    var finalized = false;
    var lastTurn = null; // 终帧 DialogueTurn（服务端意图识别结果，见 actionNote）

    function finish(demo, note) {
      if (finalized) return;
      finalized = true;
      type.end(function () {
        if (demo) {
          var demoTag = el("span", "chat-demo-tag", "演示回复");
          meta.insertBefore(demoTag, meta.firstChild);
        }
        if (note) {
          bubble.appendChild(el("span", "chat-demo-tag", " " + note));
        }
        state.chat.history.push({ role: "assistant", content: received, demo: !!demo });
        saveChatHistory();
        state.chat.busy = false;
        $("btn-chat-send").disabled = false;
        scrollChatToBottom(true);
      });
    }

    streamChat(
      {
        profile_name: currentProfileName(),
        message: text,
        history: chatHistoryForRequest(), // 多轮上下文随请求上送（服务端拼进对话 prompt）
      },
      {
        onText: function (t) {
          received += t;
          type.push(t);
        },
        onTurn: function (turn) {
          lastTurn = turn;
        },
        onDone: function () {
          if (!received.trim()) {
            // 建连成功但内容为空 → 视为失败走降级
            fallbackChat(text, type, finish, received);
            return;
          }
          finish(false, actionNote(lastTurn));
        },
        onFail: function () {
          fallbackChat(text, type, finish, received);
        },
      }
    );
  }

  // 终帧 DialogueTurn.action 的消费：识别到改路线/调时长意图时附上明确行动指引。
  // 当前版本重排仍在表单侧完成（对话内自动重排需要结构化新目标，属后续扩展），
  // 至少让"我说了要改"有系统回应，不再静默丢弃意图帧。
  function actionNote(turn) {
    if (!turn || !turn.action) return null;
    if (turn.action === "replan") {
      return "已识别改路线请求：请点上方「修改画像」切换路线/岗位后重新生成";
    }
    if (turn.action === "adjust_hours") {
      return "已识别调时长请求：请回表单调整每周投入后重新生成";
    }
    return null;
  }

  function fallbackChat(userText, type, finish, alreadyReceived) {
    if (alreadyReceived) {
      finish(false, "（连接中断，以上为已收到的部分）");
      return;
    }
    if (!mockReady()) {
      type.push("暂时联系不上顾问服务，请稍后重试。");
      finish(false, null);
      return;
    }
    markDemo("chat", "实时对话不可用，回复为演示内容");
    var reply = window.MOCK.chat(userText).reply;
    // 模拟流式：按小片推进，保留打字机观感
    var idx = 0;
    var CHUNK = 3;
    var timer = setInterval(function () {
      if (idx >= reply.length) {
        clearInterval(timer);
        finish(true, null);
        return;
      }
      var piece = reply.slice(idx, idx + CHUNK);
      idx += CHUNK;
      type.push(piece);
    }, 28);
  }

  /**
   * 打字机渲染：SSE 到达的文本先进队列，再按固定节奏放出，
   * 保证即使服务端一次性推整段回复也有流式观感。
   */
  function createTypewriter(bubble, onOverflow) {
    var queue = "";
    var timer = null;
    var ended = false;
    var doneCb = null;
    var flush = false; // 收流结束后置真：不再保持打字节奏，一次放完剩余队列

    function clearThinking() {
      var think = bubble.querySelector(".chat-thinking");
      if (think) think.remove();
    }

    function drain() {
      if (!queue) {
        clearInterval(timer);
        timer = null;
        if (ended && doneCb) {
          var cb = doneCb;
          doneCb = null;
          removeCursor();
          cb();
        }
        return;
      }
      // 队列越长放得越快，避免真实流式时延迟堆积；收流结束则立即放完，
      // 否则后台页/慢环境下定时器被节流，回复停在某处、发送按钮长时间不可用
      var speed = flush ? queue.length : Math.max(1, Math.floor(queue.length / 16));
      var piece = queue.slice(0, speed);
      queue = queue.slice(speed);
      bubble.appendChild(document.createTextNode(piece));
      if (onOverflow) onOverflow();
    }

    function ensureCursor() {
      if (bubble.querySelector(".chat-cursor")) return;
      var cur = el("span", "chat-cursor");
      bubble.appendChild(cur);
    }

    function removeCursor() {
      var cur = bubble.querySelector(".chat-cursor");
      if (cur) cur.remove();
    }

    return {
      push: function (text) {
        if (!text) return;
        clearThinking();
        queue += text;
        ensureCursor();
        if (!timer) timer = setInterval(drain, 18);
      },
      end: function (cb) {
        ended = true;
        doneCb = cb || null;
        clearThinking();
        if (!queue) {
          if (doneCb) {
            var f0 = doneCb;
            doneCb = null;
            removeCursor();
            f0();
          }
          return;
        }
        if (document.hidden) {
          // 后台页里定时器会被强节流（可达 1 次/分钟），同步放完剩余文本，
          // 避免回复停在半截、发送按钮长时间不可用
          if (timer) { clearInterval(timer); timer = null; }
          var rest = queue;
          queue = "";
          bubble.appendChild(document.createTextNode(rest));
          if (onOverflow) onOverflow();
          removeCursor();
          if (doneCb) {
            var f1 = doneCb;
            doneCb = null;
            f1();
          }
          return;
        }
        flush = true;
        if (!timer) timer = setInterval(drain, 18);
      },
    };
  }

  /**
   * POST /api/chat（SSE）。契约：body={profile_name, message, history}。
   * 帧格式：data: {"delta":...} 增量帧 + data: {"turn":{reply,action,reason}} 终帧；
   * 兼容多种服务端事件格式：data: [DONE] / {"reply":...} / 纯文本。
   * 3 秒未建连 → onFail（降级）；建连后按流读取，整体上限 120s。
   * onTurn(turn) 可选：终帧的完整 DialogueTurn（意图识别结果）。
   */
  function streamChat(body, handlers) {
    var ctrl = new AbortController();
    var connectTimer = setTimeout(function () { ctrl.abort(); }, TIMEOUT_CHAT_CONNECT_MS);
    var overallTimer = setTimeout(function () { ctrl.abort(); }, CHAT_STREAM_MAX_MS);
    var connected = false;

    fetch(API_BASE + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    }).then(
      function (res) {
        connected = true;
        clearTimeout(connectTimer);
        if (!res.ok) {
          var err = new Error("HTTP " + res.status);
          err.kind = "http";
          err.status = res.status;
          throw err;
        }
        var ctype = (res.headers.get("content-type") || "").toLowerCase();
        if (ctype.indexOf("text/event-stream") !== -1 && res.body) {
          return consumeSSE(res, handlers);
        }
        // 非 SSE：按整段 JSON 处理（DialogueTurn 契约 {reply, action, reason}）
        return res.json().then(function (data) {
          if (data && typeof data === "object" && data.action) handlers.onTurn && handlers.onTurn(data);
          var text = extractText(data);
          if (text) handlers.onText(text);
        });
      }
    ).then(function () {
      clearTimeout(overallTimer);
      handlers.onDone();
    }).catch(function (e) {
      clearTimeout(connectTimer);
      clearTimeout(overallTimer);
      if (connected && e && e.name === "AbortError") {
        // 整体超时断流：按结束处理，已收到内容由 onDone 兜底
        handlers.onDone();
      } else {
        handlers.onFail(classifyFetchError(e, !connected));
      }
    });
  }

  function consumeSSE(res, handlers) {
    var reader = res.body.getReader();
    var decoder = new TextDecoder("utf-8");
    var buffer = "";
    var finished = false;

    function handlePayload(payload) {
      if (finished) return;
      var data = payload.trim();
      if (!data || data.charAt(0) === ":") return; // 注释/心跳
      if (data === "[DONE]") { finished = true; return; }
      var text = "";
      try {
        var obj = JSON.parse(data);
        if (obj && typeof obj === "object" && obj.turn) {
          // 终帧：完整 DialogueTurn（意图识别），不是文本增量——交给 onTurn 消费
          if (handlers.onTurn) handlers.onTurn(obj.turn);
          return;
        }
        text = extractText(obj);
      } catch (e) {
        text = data; // 纯文本增量
      }
      if (text) handlers.onText(text);
    }

    function pump() {
      return reader.read().then(function (result) {
        if (result.done) return;
        buffer += decoder.decode(result.value, { stream: true }).replace(/\r\n/g, "\n");
        var events = buffer.split("\n\n");
        buffer = events.pop() || "";
        events.forEach(function (ev) {
          // 一个事件可能多行 data:，按规范以换行拼接
          var dataLines = ev.split("\n")
            .filter(function (line) { return line.indexOf("data:") === 0; })
            .map(function (line) { return line.slice(5).replace(/^\s/, ""); });
          if (dataLines.length) handlePayload(dataLines.join("\n"));
        });
        if (finished) {
          try { reader.cancel(); } catch (e) { /* 已结束 */ }
          return;
        }
        return pump();
      });
    }

    return pump();
  }

  function extractText(data) {
    if (data == null) return "";
    if (typeof data === "string") return data;
    if (Array.isArray(data)) {
      return data.map(extractText).filter(Boolean).join("");
    }
    if (typeof data === "object") {
      // OpenAI 风格
      if (data.choices && data.choices[0]) {
        var piece = data.choices[0].delta || data.choices[0].message;
        var inner = extractText(piece);
        if (inner) return inner;
      }
      var keys = ["delta", "content", "text", "reply", "token", "message", "data"];
      for (var i = 0; i < keys.length; i++) {
        if (typeof data[keys[i]] === "string" && data[keys[i]]) return data[keys[i]];
      }
    }
    return "";
  }

  // ------------------------------------------------------------------
  // 全局兜底与启动
  // ------------------------------------------------------------------

  function init() {
    initForm();
    initChat();

    prefillProfile(storageGet(STORAGE_PROFILE, null));

    $("profile-form").addEventListener("submit", onSubmitForm);
    $("btn-cancel-plan").addEventListener("click", cancelPlan);
    $("btn-back-home").addEventListener("click", function () { showView("home"); });
    $("btn-refresh").addEventListener("click", function () {
      if (state.profile) {
        prefillProfile(state.profile);
        showView("home");
        toast("已回到表单，可直接重新生成");
      } else {
        showView("home");
      }
    });

    // 全局兜底：任何未捕获异常只提示，不白屏
    window.addEventListener("error", function (ev) {
      if (ev && ev.message && !state.loading) {
        toast("页面出现小问题，但功能仍可使用");
      }
    });
    window.addEventListener("unhandledrejection", function () {
      /* promise 兜底：已由各链路 catch 处理 */
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
