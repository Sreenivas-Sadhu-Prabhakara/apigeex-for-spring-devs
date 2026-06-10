// app.js — progressive enhancement for the static "Apigee X for Spring devs" site:
//   1. one-click "Copy" on every code block
//   2. mobile navigation toggle
//   3. localStorage progress tracking (nav ticks + progress bar + "mark complete")
//   4. reading-progress bar
//   5. "On this page" TOC active-section highlighting
//
// The session total and storage key are injected per-page via window.__COURSE__
// (see build.py) so nothing here hard-codes a count that could drift.
(function () {
  "use strict";

  var COURSE = window.__COURSE__ || { total: 33, key: "apigeex-spring.progress.v1" };
  var PROGRESS_KEY = COURSE.key;
  var TOTAL = COURSE.total;

  function getDone() {
    try { return JSON.parse(localStorage.getItem(PROGRESS_KEY)) || []; }
    catch (e) { return []; }
  }
  function setDone(arr) {
    arr = arr.filter(function (v, i, a) { return a.indexOf(v) === i; }).sort(function (a, b) { return a - b; });
    try { localStorage.setItem(PROGRESS_KEY, JSON.stringify(arr)); } catch (e) {}
    return arr;
  }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  // ---- Copy buttons on code blocks ----
  document.querySelectorAll("div.codehilite").forEach(function (block) {
    var pre = block.querySelector("pre");
    if (!pre) return;
    var btn = document.createElement("button");
    btn.className = "copy-btn"; btn.type = "button"; btn.textContent = "Copy";
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(pre.innerText).then(function () {
        btn.textContent = "Copied"; btn.classList.add("copied");
        setTimeout(function () { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 1400);
      }).catch(function () { btn.textContent = "Press Ctrl+C"; });
    });
    block.appendChild(btn);
  });

  // ---- Mobile nav toggle ----
  var toggle = document.getElementById("navToggle");
  if (toggle) toggle.addEventListener("click", function () { document.body.classList.toggle("nav-open"); });
  document.querySelectorAll(".sidebar a").forEach(function (a) {
    a.addEventListener("click", function () { document.body.classList.remove("nav-open"); });
  });

  // ---- Progress: reflect completion in the sidebar ----
  function refreshProgress() {
    var done = getDone();
    document.querySelectorAll(".sidebar li[data-session]").forEach(function (li) {
      var s = +li.getAttribute("data-session");
      li.classList.toggle("completed", done.indexOf(s) >= 0);
    });
    var fill = document.getElementById("navProgressFill");
    var text = document.getElementById("navProgressText");
    var pct = TOTAL ? Math.round((done.length / TOTAL) * 100) : 0;
    if (fill) fill.style.width = pct + "%";
    if (text) text.textContent = done.length + " / " + TOTAL + " complete";
  }
  refreshProgress();

  // ---- "Mark complete" toggle on a session page ----
  var markBtn = document.getElementById("markComplete");
  var main = document.querySelector("main[data-session]");
  if (markBtn && main) {
    var sid = +main.getAttribute("data-session");
    var code = (markBtn.parentNode.getAttribute("data-session-code") || pad(sid));
    var lastNode = markBtn.childNodes[markBtn.childNodes.length - 1];
    var sync = function () {
      var isDone = getDone().indexOf(sid) >= 0;
      markBtn.parentNode.classList.toggle("is-done", isDone);
      lastNode.nodeValue = isDone ? (" " + code + " complete") : (" Mark " + code + " complete");
    };
    markBtn.addEventListener("click", function () {
      var done = getDone(), i = done.indexOf(sid);
      if (i >= 0) done.splice(i, 1); else done.push(sid);
      setDone(done); refreshProgress(); sync();
    });
    sync();
  }

  // ---- Reading-progress bar ----
  var bar = document.getElementById("readingBar");
  if (bar) {
    var onScroll = function () {
      var h = document.documentElement, b = document.body;
      var st = h.scrollTop || b.scrollTop;
      var sh = (h.scrollHeight || b.scrollHeight) - h.clientHeight;
      bar.style.width = (sh > 0 ? (st / sh) * 100 : 0) + "%";
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // ---- "On this page" active-section highlighting ----
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll(".toc-rail a"));
  if (tocLinks.length) {
    var targets = tocLinks.map(function (a) {
      var id = decodeURIComponent(a.getAttribute("href").slice(1));
      return document.getElementById(id);
    });
    var spy = function () {
      var pos = window.scrollY + 120, idx = 0;
      for (var i = 0; i < targets.length; i++) {
        if (targets[i] && targets[i].offsetTop <= pos) idx = i;
      }
      tocLinks.forEach(function (a, i) { a.classList.toggle("active", i === idx); });
    };
    window.addEventListener("scroll", spy, { passive: true });
    spy();
  }
})();
