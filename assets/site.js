// tldrcve — progressive enhancement only. Pages are fully readable without this file.
(function () {
  "use strict";
  document.documentElement.classList.remove("no-js");

  // Phone menu.
  var toggle = document.querySelector(".nav-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var open = toggle.closest(".site-header").classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Menu");
    });
  }

  // Copy buttons: data-copy="<element id>" copies that element's text; data-copy-link copies a URL.
  function copy(btn, text) {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(function () {
      var tip = btn.getAttribute("data-tip");
      btn.setAttribute("data-tip", "Copied!");
      btn.classList.add("is-done");
      setTimeout(function () {
        btn.setAttribute("data-tip", tip);
        btn.classList.remove("is-done");
      }, 1400);
    }, function () {});
  }
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      copy(btn, document.getElementById(btn.getAttribute("data-copy")).textContent.trim());
    });
  });
  document.querySelectorAll("[data-copy-link]").forEach(function (btn) {
    btn.addEventListener("click", function () { copy(btn, btn.getAttribute("data-copy-link")); });
  });

  // Expand all / collapse all, per pane.
  document.querySelectorAll("[data-folds]").forEach(function (pane) {
    var btn = pane.querySelector("[data-expand-all]");
    var folds = Array.prototype.slice.call(pane.querySelectorAll("details.fold"));
    if (!btn) return;
    function sync() {
      btn.textContent = folds.every(function (d) { return d.open; }) ? "Collapse all" : "Expand all";
    }
    btn.addEventListener("click", function () {
      var open = !folds.every(function (d) { return d.open; });
      folds.forEach(function (d) { d.open = open; });
      sync();
    });
    folds.forEach(function (d) { d.addEventListener("toggle", sync); });
  });

  // How we rate: CVE pages and incident pages as tabs (#incidents opens the second).
  var tabs = document.querySelector("[data-tabs]");
  if (tabs) {
    var panels = document.querySelectorAll("[data-tabpanel]");
    var show = function (name) {
      tabs.querySelectorAll("[data-tab]").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.tab === name ? "true" : "false"); });
      panels.forEach(function (p) { p.hidden = p.dataset.tabpanel !== name; });
    };
    tabs.querySelectorAll("[data-tab]").forEach(function (b) {
      b.addEventListener("click", function () { show(b.dataset.tab); history.replaceState(null, "", "#" + b.dataset.tab); });
    });
    show(location.hash === "#incidents" ? "incidents" : "cves");
  }

  // All CVEs: search, sort and release-date filter.
  var list = document.querySelector("[data-list]");
  if (list) {
    var ol = list.querySelector(".rows");
    var rows = Array.prototype.slice.call(ol.children);
    var input = list.querySelector("[data-list-filter]");
    var empty = list.querySelector(".list__empty");
    var state = { q: "", sort: "scare", days: "" };

    var q0 = new URLSearchParams(location.search).get("q");
    if (q0) { input.value = q0; state.q = q0.trim().toLowerCase(); }

    function press(group, btn) {
      group.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
    }
    function render() {
      var now = Date.now();
      var sorted = rows.slice().sort(function (a, b) {
        if (state.sort === "recent") return b.dataset.disclosed.localeCompare(a.dataset.disclosed);
        return parseFloat(b.dataset.scare) - parseFloat(a.dataset.scare);
      });
      var shown = 0;
      sorted.forEach(function (r) {
        var hit = !state.q ? !r.dataset.incident : r.dataset.search.indexOf(state.q) !== -1;
        if (hit && state.days) {
          var age = (now - new Date(r.dataset.disclosed + "T00:00:00Z").getTime()) / 864e5;
          hit = age <= parseInt(state.days, 10);
        }
        r.hidden = !hit;
        if (hit) shown++;
        ol.appendChild(r);
      });
      empty.hidden = shown !== 0;
    }

    input.addEventListener("input", function () { state.q = input.value.trim().toLowerCase(); render(); });
    list.querySelectorAll("[data-sort]").forEach(function (btn) {
      btn.addEventListener("click", function () { state.sort = btn.dataset.sort; press(btn.parentNode, btn); render(); });
    });
    list.querySelectorAll("[data-days]").forEach(function (btn) {
      btn.addEventListener("click", function () { state.days = btn.dataset.days; press(btn.parentNode, btn); render(); });
    });
    render();
  }
  // Safe versions: search and "no fix yet" filter.
  var vlist = document.querySelector("[data-vlist]");
  if (vlist) {
    var cards = Array.prototype.slice.call(vlist.querySelectorAll(".vcard"));
    var vin = vlist.querySelector("[data-vlist-filter]");
    var vempty = vlist.querySelector(".list__empty");
    var vstate = { q: "", nofix: "" };
    var vq0 = new URLSearchParams(location.search).get("q");
    if (vq0) { vin.value = vq0; vstate.q = vq0.trim().toLowerCase(); }
    if (new URLSearchParams(location.search).get("nofix")) vstate.nofix = "1";
    function vrender() {
      var shown = 0;
      cards.forEach(function (c) {
        var hit = (!vstate.q || c.dataset.search.indexOf(vstate.q) !== -1) && (!vstate.nofix || c.dataset.nofix === "1");
        c.hidden = !hit;
        if (hit) shown++;
      });
      vempty.hidden = shown !== 0;
      vlist.querySelectorAll("[data-nofix]").forEach(function (b) {
        if (b.tagName === "BUTTON") b.setAttribute("aria-pressed", b.dataset.nofix === vstate.nofix ? "true" : "false");
      });
    }
    vin.addEventListener("input", function () { vstate.q = vin.value.trim().toLowerCase(); vrender(); });
    vlist.querySelectorAll("button[data-nofix]").forEach(function (b) {
      b.addEventListener("click", function () { vstate.nofix = b.dataset.nofix; vrender(); });
    });
    vrender();
  }
  // 404 for a CVE or GHSA we don't cover: say so and point to the official records.
  var nf = document.querySelector("[data-notfound]");
  if (nf) {
    var id = decodeURIComponent(location.pathname).replace(/^\/+|\/+$/g, "");
    var cve = /^cve-\d{4}-\d{4,}$/i.test(id), ghsa = /^ghsa(-[23456789cfghjmpqrvwx]{4}){3}$/i.test(id);
    if (cve || ghsa) {
      var up = cve ? id.toUpperCase() : "GHSA-" + id.slice(5).toLowerCase();
      var href = cve ? "https://nvd.nist.gov/vuln/detail/" + up : "https://github.com/advisories/" + up;
      nf.textContent = "We don't have a page for " + up + ". We only cover the vulnerabilities people are talking about. ";
      var a = document.createElement("a");
      a.href = href;
      a.textContent = cve ? "Look it up on NVD →" : "Look it up on GitHub →";
      nf.appendChild(a);
    }
  }
})();

// Homepage "Coming up": hide dates already past, keep the next few.
(function () {
  var list = document.querySelector("[data-upcoming]");
  if (!list) return;
  var keep = parseInt(list.getAttribute("data-upcoming"), 10) || 6;
  var d = new Date();  // the reader's local date, as YYYY-MM-DD
  var today = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  var shown = 0;
  Array.prototype.forEach.call(list.querySelectorAll("li[data-date]"), function (li) {
    if (li.getAttribute("data-date") < today || shown >= keep) { li.hidden = true; } else { shown++; }
  });
  var empty = list.querySelector("[data-empty]");
  if (empty && shown === 0) empty.hidden = false;
})();

// Links to #sources open the folded sources and changelog.
(function () {
  function openSources() {
    if (location.hash !== "#sources") return;
    var d = document.getElementById("sources");
    if (d && d.tagName === "DETAILS") d.open = true;
  }
  openSources();
  window.addEventListener("hashchange", openSources);
})();

// Week page: one search box filters every section (new pages, changes, releases, coming up).
(function () {
  var input = document.querySelector("[data-week-filter]");
  if (!input) return;
  var sections = document.querySelectorAll("[data-week-section]");
  var empty = document.querySelector("[data-week-empty]");
  function apply() {
    var q = input.value.trim().toLowerCase();
    var any = false;
    Array.prototype.forEach.call(sections, function (sec) {
      var items = sec.querySelectorAll("[data-search]");
      var shown = 0;
      Array.prototype.forEach.call(items, function (it) {
        var hit = !q || it.getAttribute("data-search").indexOf(q) !== -1 || it.textContent.toLowerCase().indexOf(q) !== -1;
        it.hidden = !hit;
        if (hit) shown++;
      });
      sec.hidden = q !== "" && shown === 0;
      if (shown) any = true;
    });
    if (empty) empty.hidden = !q || any;
  }
  var params = new URLSearchParams(location.search);
  if (params.get("q")) input.value = params.get("q");
  input.addEventListener("input", apply);
  apply();
})();

// Homepage search: matching pages appear under the box as you type. Arrow keys and Enter open one; Enter without a
// pick (or "See all results") goes to All CVEs filtered, as before. Data: /api/cves.json, fetched on first focus.
(function () {
  "use strict";
  var form = document.querySelector("[data-suggest]");
  if (!form) return;
  var input = form.querySelector("input");
  var pages = null, shown = [], active = -1;
  var list = document.createElement("ul");
  list.id = "q-suggest";
  list.className = "suggest";
  list.setAttribute("role", "listbox");
  list.hidden = true;
  form.appendChild(list);
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-controls", "q-suggest");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-autocomplete", "list");

  function load() {
    if (pages) return Promise.resolve(pages);
    return fetch("/api/cves.json").then(function (r) { return r.json(); }).then(function (d) {
      pages = d.pages.map(function (p) {
        p._s = [p.name, p.product].concat(p.cves || [], p.ghsa || [], p.aliases || [], p.also_in || []).join(" ").toLowerCase();
        return p;
      });
      return pages;
    });
  }
  function item(cls, children, onPick) {
    var li = document.createElement("li");
    li.className = cls;
    li.setAttribute("role", "option");
    children.forEach(function (c) { li.appendChild(c); });
    li.addEventListener("mousedown", function (e) { e.preventDefault(); onPick(); });
    return li;
  }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; e.textContent = text; return e; }
  // Product, then up to two CVE IDs; each ID stays on one line so phones don't break it at the hyphen.
  function meta(p) {
    var m = el("span", "suggest__meta", p.product);
    (p.cves || []).slice(0, 2).forEach(function (id) { m.appendChild(document.createTextNode(" · ")); m.appendChild(el("span", "suggest__id", id)); });
    return m;
  }
  function render() {
    var q = input.value.trim().toLowerCase();
    list.textContent = "";
    if (!q || !pages) { close(); return; }
    var words = q.split(/\s+/);
    shown = pages.filter(function (p) { return words.every(function (w) { return p._s.indexOf(w) !== -1; }); }).slice(0, 6);
    shown.forEach(function (p, i) {
      var li = item("suggest__item", [
        el("span", "suggest__name", p.name),
        meta(p),
        el("span", "verdict verdict--" + (p.kind === "incident" ? "incident" : p.verdict), p.verdict_label)
      ], function () { location.href = "/" + p.slug + "/"; });
      li.id = "q-opt-" + i;
      list.appendChild(li);
    });
    var all = item("suggest__all", [el("span", "", shown.length ? "See all results for “" + input.value.trim() + "” →" : "No page matches yet. Search all CVEs →")], function () { form.submit(); });
    all.id = "q-opt-" + shown.length;
    list.appendChild(all);
    active = -1;
    highlight();
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }
  function highlight() {
    var rows = list.querySelectorAll('[role="option"]');
    rows.forEach(function (r, i) { r.classList.toggle("is-active", i === active); r.setAttribute("aria-selected", i === active ? "true" : "false"); });
    if (active >= 0) input.setAttribute("aria-activedescendant", "q-opt-" + active); else input.removeAttribute("aria-activedescendant");
  }
  function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; }

  input.addEventListener("focus", function () { load().then(render); });
  input.addEventListener("input", function () { load().then(render); });
  input.addEventListener("blur", close);
  input.addEventListener("keydown", function (e) {
    var rows = list.querySelectorAll('[role="option"]');
    if (e.key === "ArrowDown" && rows.length) { e.preventDefault(); active = Math.min(active + 1, rows.length - 1); highlight(); }
    else if (e.key === "ArrowUp" && rows.length) { e.preventDefault(); active = Math.max(active - 1, 0); highlight(); }
    else if (e.key === "Escape") { close(); }
    else if (e.key === "Enter" && active >= 0 && active < shown.length) { e.preventDefault(); location.href = "/" + shown[active].slug + "/"; }
  });
})();
