// tldrcve — progressive enhancement only. Pages are fully readable without this file.
(function () {
  "use strict";
  document.documentElement.classList.remove("no-js");

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
        var hit = !state.q || r.dataset.search.indexOf(state.q) !== -1;
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
