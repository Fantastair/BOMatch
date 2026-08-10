/* =========================================================
   BOMatch 1.0.0 — 客户端交互增强
   表格排序 · 即时过滤 · 移动端导航 · flash 自动消失 · 返回顶部
   纯原生 JS，无构建链
   ========================================================= */
(function () {
  "use strict";

  /* ---------- 工具 ---------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  /* 提取单元格排序值：优先 data-sort-value，否则文本（数字智能识别） */
  function cellValue(cell) {
    if (cell.dataset.sortValue !== undefined) return cell.dataset.sortValue;
    var text = (cell.textContent || "").trim();
    // 去掉千分位逗号、货币符号，尝试转数字
    var num = parseFloat(text.replace(/[,¥$]/g, ""));
    return isNaN(num) ? text : num;
  }

  /* ---------- 1. 表格列排序 ----------
     在表头 th 上加 class="sortable"（可加 data-sort="numeric|text"）即启用 */
  function initTableSort() {
    $all("table.data-table thead th.sortable").forEach(function (th) {
      th.addEventListener("click", function () {
        var table = th.closest("table");
        var tbody = table.tBodies[0];
        if (!tbody) return;
        var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
        var isAsc = !(th.classList.contains("sort-asc") || th.classList.contains("sort-desc"));
        // 若之前按 desc 排序，则本轮应升序
        if (th.classList.contains("sort-desc")) isAsc = true;

        // 清除本表其他列的排序态
        $all("th.sortable", table).forEach(function (t) {
          t.classList.remove("sort-asc", "sort-desc");
        });

        var rows = Array.from(tbody.rows).filter(function (r) {
          return !r.classList.contains("no-match");
        });

        rows.sort(function (a, b) {
          var av = cellValue(a.cells[idx]);
          var bv = cellValue(b.cells[idx]);
          if (typeof av === "number" && typeof bv === "number") {
            return isAsc ? av - bv : bv - av;
          }
          var as = String(av).toLowerCase();
          var bs = String(bv).toLowerCase();
          if (as < bs) return isAsc ? -1 : 1;
          if (as > bs) return isAsc ? 1 : -1;
          return 0;
        });

        rows.forEach(function (r) { tbody.appendChild(r); });
        th.classList.add(isAsc ? "sort-asc" : "sort-desc");
      });
    });
  }

  /* ---------- 2. 客户端即时过滤 ----------
     input[data-live-filter="<table selector>"]：按输入过滤表格行（匹配所有文本） */
  function initLiveFilter() {
    $all("input[data-live-filter]").forEach(function (input) {
      var table = $(input.dataset.liveFilter);
      if (!table) return;
      var tbody = table.tBodies[0];
      if (!tbody) return;
      var countEl = document.getElementById(input.dataset.count || "");
      var emptyRow = $("tr.empty", tbody);

      input.addEventListener("input", function () {
        var q = (input.value || "").trim().toLowerCase();
        var visible = 0;
        $all("tr", tbody).forEach(function (tr) {
          if (tr.classList.contains("empty") || tr.classList.contains("no-match")) return;
          var match = !q || tr.textContent.toLowerCase().indexOf(q) !== -1;
          tr.style.display = match ? "" : "none";
          if (match) visible++;
        });
        if (emptyRow) emptyRow.style.display = visible ? "none" : "";
        if (countEl) countEl.textContent = String(visible);
      });
    });
  }

  /* ---------- 3. 移动端导航 ---------- */
  function initNav() {
    var toggle = $(".nav-toggle");
    var nav = $(".topbar nav");
    if (!toggle || !nav) return;
    toggle.addEventListener("click", function () {
      nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", nav.classList.contains("open"));
    });
    // 点击导航链接后自动收起
    $all("a", nav).forEach(function (a) {
      a.addEventListener("click", function () { nav.classList.remove("open"); });
    });
  }

  /* ---------- 3b. 用户下拉菜单 ---------- */
  function initUserMenu() {
    var toggle = document.getElementById("user-menu-toggle");
    var dropdown = document.getElementById("user-menu-dropdown");
    if (!toggle || !dropdown) return;
    function close() {
      dropdown.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    }
    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      var willOpen = dropdown.hidden;
      dropdown.hidden = !willOpen;
      toggle.setAttribute("aria-expanded", String(willOpen));
    });
    // 点击菜单外部或按 Esc 关闭
    document.addEventListener("click", function (e) {
      if (!e.target.closest("#user-menu")) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  /* ---------- 4. flash 消息自动消失 ---------- */
  function initFlash() {
    $all(".flash").forEach(function (el) {
      setTimeout(function () {
        el.style.transition = "opacity .5s ease, transform .5s ease";
        el.style.opacity = "0";
        el.style.transform = "translateY(-4px)";
        setTimeout(function () { el.remove(); }, 600);
      }, 6000);
    });
  }

  /* ---------- 5. 返回顶部 ---------- */
  function initBackToTop() {
    var btn = $(".back-to-top");
    if (!btn) return;
    function update() {
      btn.classList.toggle("show", window.scrollY > 400);
    }
    window.addEventListener("scroll", update, { passive: true });
    update();
    btn.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  /* ---------- 6. 表单提交加载态（data-loading 按钮） ---------- */
  function initLoadingButtons() {
    $all("form[data-loading]").forEach(function (form) {
      var btn = $('button[type="submit"]', form);
      if (!btn) return;
      form.addEventListener("submit", function () {
        btn.classList.add("is-loading");
        btn.disabled = true;
      });
    });
  }

  /* ---------- 7. 筛选表单自动提交（实时筛选，data-autosubmit） ---------- */
  function initAutoSubmitFilters() {
    document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
      var debounceTimer = null;
      // 下拉框 / 复选框：change 立即提交
      form.querySelectorAll("select, input[type=checkbox]").forEach(function (ctl) {
        ctl.addEventListener("change", function () {
          clearTimeout(debounceTimer);
          form.submit();
        });
      });
      // 搜索框：停止输入 400ms 后自动提交（防抖）
      form.querySelectorAll("input[type=search]").forEach(function (q) {
        q.addEventListener("input", function () {
          clearTimeout(debounceTimer);
          debounceTimer = setTimeout(function () { form.submit(); }, 400);
        });
      });
    });
  }

  /* ---------- 启动 ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    initTableSort();
    initLiveFilter();
    initNav();
    initUserMenu();
    initFlash();
    initBackToTop();
    initLoadingButtons();
    initAutoSubmitFilters();
  });
})();
