/* widgets.js — interactive learning widgets for the Apigee X (Spring devs) site.
 *
 * Authoring: in Markdown, write a ```widget fenced block whose body is JSON
 * with a "type" field. build.py turns it into:
 *   <div class="widget" data-widget="TYPE"><script type="application/json">…</script></div>
 * and this file hydrates it on DOMContentLoaded.
 *
 * Widget types: pipeline | sequence | statemachine | ratelimit | chart | quiz | curriculummap
 */
(function () {
  "use strict";

  var COURSE = window.__COURSE__ || { key: "apigeex-spring.progress.v1" };
  function completedSessions() {
    try { return JSON.parse(localStorage.getItem(COURSE.key)) || []; }
    catch (e) { return []; }
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var REG = {};
  function register(type, fn) { REG[type] = fn; }

  /* ---------------------------------------------------------------- pipeline */
  register("pipeline", function (el, cfg) {
    var stages = cfg.stages || [];
    el.innerHTML =
      '<div class="w-head"><span class="w-kind">Interactive</span><h4>' +
      esc(cfg.title || "Request / response pipeline") + "</h4></div>" +
      '<div class="pl-controls">' +
      '<button class="w-btn pl-run">&#9654; Send a request</button>' +
      '<button class="w-btn ghost pl-reset">Reset</button>' +
      '<span class="pl-status"></span></div>' +
      '<div class="pl-track"></div>' +
      '<div class="pl-detail">Press <b>Send a request</b> — or click any stage — to see what runs and when.</div>';
    var track = el.querySelector(".pl-track");
    var detail = el.querySelector(".pl-detail");
    var status = el.querySelector(".pl-status");
    stages.forEach(function (s, i) {
      var b = document.createElement("button");
      b.className = "pl-stage phase-" + (s.phase || "req");
      b.innerHTML = '<span class="pl-idx">' + (i + 1) + "</span><span class='pl-name'>" + esc(s.name) + "</span>";
      b.addEventListener("click", function () { show(i); });
      track.appendChild(b);
    });
    var chips = Array.prototype.slice.call(track.children);
    function show(i) {
      chips.forEach(function (c, j) { c.classList.toggle("on", j === i); });
      var s = stages[i];
      detail.innerHTML = "<b>" + esc(s.name) + '</b> <span class="pl-tag ' + (s.phase || "req") + '">' +
        (s.phase === "res" ? "response" : s.phase === "route" ? "routing" : "request") + "</span><br>" + esc(s.desc || "");
    }
    var timer = null;
    function reset() { if (timer) clearInterval(timer); chips.forEach(function (c) { c.classList.remove("on"); }); status.textContent = ""; }
    el.querySelector(".pl-run").addEventListener("click", function () {
      reset(); var i = 0; status.textContent = "running…";
      timer = setInterval(function () {
        if (i >= stages.length) { clearInterval(timer); status.textContent = "done ✓"; return; }
        show(i); i++;
      }, 680);
    });
    el.querySelector(".pl-reset").addEventListener("click", function () {
      reset(); detail.innerHTML = "Press <b>Send a request</b> — or click any stage — to see what runs and when.";
    });
  });

  /* ---------------------------------------------------------------- sequence */
  register("sequence", function (el, cfg) {
    var actors = cfg.actors || [], steps = cfg.steps || [];
    var W = Math.max(520, actors.length * 150), rowH = 52, top = 66, H = top + steps.length * rowH + 24;
    var ax = {};
    actors.forEach(function (a, i) { ax[a.id] = Math.round((i + 0.5) * (W / actors.length)); });
    var cur = 0, timer = null;
    el.innerHTML =
      '<div class="w-head"><span class="w-kind">Step through</span><h4>' + esc(cfg.title || "Sequence") + "</h4></div>" +
      '<div class="seq-controls">' +
      '<button class="w-btn seq-prev">&#8249; Prev</button>' +
      '<button class="w-btn seq-next">Next &#8250;</button>' +
      '<button class="w-btn ghost seq-play">&#9654; Play</button>' +
      '<span class="seq-count"></span></div>' +
      '<div class="seq-scroll"><svg class="seq-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMin meet"></svg></div>' +
      '<div class="seq-note"></div>';
    var svg = el.querySelector(".seq-svg"), note = el.querySelector(".seq-note"), count = el.querySelector(".seq-count");
    function draw() {
      var s = '<defs><marker id="seqah" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto">' +
        '<path d="M0,0 L7,3 L0,6 z"/></marker></defs>';
      actors.forEach(function (a) {
        s += '<line class="seq-life" x1="' + ax[a.id] + '" y1="' + (top - 12) + '" x2="' + ax[a.id] + '" y2="' + (H - 8) + '"/>';
      });
      actors.forEach(function (a) {
        var x = ax[a.id];
        s += '<g class="seq-actor"><rect x="' + (x - 64) + '" y="12" width="128" height="34" rx="7"/>' +
          '<text x="' + x + '" y="34" text-anchor="middle">' + esc(a.label) + "</text></g>";
      });
      steps.forEach(function (st, i) {
        if (i > cur) return;
        var y = top + i * rowH + rowH / 2, active = i === cur ? " act" : "", ret = st.kind === "return" ? " ret" : "";
        if (st.from === st.to) {
          var x = ax[st.from];
          s += '<path class="seq-arrow self' + ret + active + '" d="M ' + x + " " + (y - 9) + " h 44 v 18 h -38\" marker-end='url(#seqah)'/>";
          s += '<text class="seq-lbl' + active + '" x="' + (x + 50) + '" y="' + (y - 12) + '" text-anchor="start">' + esc(st.label) + "</text>";
        } else {
          var x1 = ax[st.from], x2 = ax[st.to], dir = x2 > x1 ? 1 : -1;
          s += '<line class="seq-arrow' + ret + active + '" x1="' + x1 + '" y1="' + y + '" x2="' + (x2 - dir * 9) + '" y2="' + y + "\" marker-end='url(#seqah)'/>";
          s += '<text class="seq-lbl' + active + '" x="' + ((x1 + x2) / 2) + '" y="' + (y - 8) + '" text-anchor="middle">' + esc(st.label) + "</text>";
        }
      });
      svg.innerHTML = s;
      var st = steps[cur] || {};
      note.innerHTML = '<span class="seq-step">' + (cur + 1) + ".</span> " + esc(st.note || st.label || "");
      count.textContent = "Step " + (cur + 1) + " / " + steps.length;
    }
    function go(n) { cur = Math.max(0, Math.min(steps.length - 1, n)); draw(); }
    el.querySelector(".seq-prev").addEventListener("click", function () { stop(); go(cur - 1); });
    el.querySelector(".seq-next").addEventListener("click", function () { stop(); go(cur + 1); });
    function stop() { if (timer) { clearInterval(timer); timer = null; el.querySelector(".seq-play").innerHTML = "&#9654; Play"; } }
    el.querySelector(".seq-play").addEventListener("click", function () {
      if (timer) { stop(); return; }
      this.innerHTML = "&#10073;&#10073; Pause"; if (cur >= steps.length - 1) cur = 0;
      timer = setInterval(function () {
        if (cur >= steps.length - 1) { stop(); return; }
        go(cur + 1);
      }, 1100);
    });
    draw();
  });

  /* ------------------------------------------------------------ statemachine */
  register("statemachine", function (el, cfg) {
    var states = cfg.states || [], trans = cfg.transitions || [], events = cfg.events || [];
    var start = cfg.start || (states[0] && states[0].id), cur = start;
    var byId = {}; states.forEach(function (s) { byId[s.id] = s; });
    el.innerHTML =
      '<div class="w-head"><span class="w-kind">Explore</span><h4>' + esc(cfg.title || "State machine") + "</h4></div>" +
      '<div class="sm-states"></div>' +
      '<div class="sm-events"></div>' +
      '<div class="sm-log"><div class="sm-log-title">Transition log</div><ul></ul></div>' +
      '<div class="sm-controls"><button class="w-btn ghost sm-reset">Reset</button></div>';
    var statesEl = el.querySelector(".sm-states"), eventsEl = el.querySelector(".sm-events"), logEl = el.querySelector(".sm-log ul");
    states.forEach(function (s) {
      var d = document.createElement("span");
      d.className = "sm-state" + (s.terminal ? " terminal" : "");
      d.setAttribute("data-id", s.id);
      d.textContent = s.label;
      statesEl.appendChild(d);
    });
    events.forEach(function (ev) {
      var b = document.createElement("button");
      b.className = "w-btn sm-ev"; b.textContent = ev.label || ev.id;
      b.addEventListener("click", function () { fire(ev.id, ev.label || ev.id); });
      eventsEl.appendChild(b);
    });
    function render() {
      statesEl.querySelectorAll(".sm-state").forEach(function (n) {
        n.classList.toggle("on", n.getAttribute("data-id") === cur);
      });
      var s = byId[cur];
      eventsEl.querySelectorAll(".sm-ev").forEach(function (b, i) {
        var ev = events[i];
        var allowed = !!trans.find(function (t) { return t.from === cur && t.event === ev.id; });
        b.disabled = (s && s.terminal) || !allowed;
        b.classList.toggle("disabled", b.disabled);
      });
    }
    function log(html, cls) {
      var li = document.createElement("li"); li.className = cls || ""; li.innerHTML = html;
      logEl.appendChild(li); logEl.parentNode.scrollTop = logEl.parentNode.scrollHeight;
    }
    function fire(evId, evLabel) {
      var t = trans.find(function (t) { return t.from === cur && t.event === evId; });
      if (!t) { log('&#10007; <b>' + esc(evLabel) + "</b> not allowed in <b>" + esc(byId[cur].label) + "</b>", "bad"); return; }
      log('&#10003; <b>' + esc(byId[cur].label) + "</b> &rarr; <b>" + esc(byId[t.to].label) + "</b> on <b>" + esc(evLabel) + "</b>" +
        (t.desc ? '<span class="sm-desc">' + esc(t.desc) + "</span>" : ""), "good");
      cur = t.to; render();
    }
    el.querySelector(".sm-reset").addEventListener("click", function () { cur = start; logEl.innerHTML = ""; render(); });
    render();
  });

  /* ----------------------------------------------------------- ratelimit sim */
  register("ratelimit", function (el, cfg) {
    var rate = cfg.ratePerMin || 30, interval = 60000 / rate;
    var last = 0, allowed = 0, blocked = 0;
    el.innerHTML =
      '<div class="w-head"><span class="w-kind">Simulator</span><h4>' + esc(cfg.title || "SpikeArrest simulator") + "</h4></div>" +
      '<p class="rl-explain">Policy: <code>&lt;Rate&gt;' + rate + "pm&lt;/Rate&gt;</code> &rarr; SpikeArrest allows at most one request every <b>" +
      Math.round(interval) + " ms</b>. Click fast, or burst, and watch what gets <span class='rl-ok-t'>200</span> vs <span class='rl-no-t'>429</span>.</p>" +
      '<div class="rl-controls">' +
      '<button class="w-btn rl-send">Send 1 request</button>' +
      '<button class="w-btn rl-burst">Burst &times;5</button>' +
      '<button class="w-btn ghost rl-reset">Reset</button></div>' +
      '<div class="rl-track"></div>' +
      '<div class="rl-stats"><span class="rl-ok">200 allowed: <b>0</b></span>' +
      '<span class="rl-no">429 blocked: <b>0</b></span></div>';
    var track = el.querySelector(".rl-track");
    var okEl = el.querySelector(".rl-ok b"), noEl = el.querySelector(".rl-no b");
    function tick() {
      var now = Date.now(), ok = (now - last) >= interval;
      if (ok) { last = now; allowed++; } else { blocked++; }
      var t = document.createElement("span");
      t.className = "rl-tick " + (ok ? "ok" : "no");
      t.title = ok ? "200 OK" : "429 Too Many Requests";
      track.appendChild(t);
      while (track.children.length > 60) track.removeChild(track.firstChild);
      okEl.textContent = allowed; noEl.textContent = blocked;
    }
    el.querySelector(".rl-send").addEventListener("click", tick);
    el.querySelector(".rl-burst").addEventListener("click", function () { for (var i = 0; i < 5; i++) tick(); });
    el.querySelector(".rl-reset").addEventListener("click", function () {
      last = 0; allowed = 0; blocked = 0; track.innerHTML = ""; okEl.textContent = "0"; noEl.textContent = "0";
    });
  });

  /* ------------------------------------------------------------------- chart */
  register("chart", function (el, cfg) {
    el.innerHTML =
      '<div class="w-head"><span class="w-kind">Data</span><h4>' + esc(cfg.title || "Chart") + "</h4></div>" +
      '<div class="chart-wrap" style="height:' + (cfg.height || 300) + 'px"><canvas></canvas></div>' +
      (cfg.caption ? '<p class="w-cap">' + esc(cfg.caption) + "</p>" : "");
    var canvas = el.querySelector("canvas");
    (function go() {
      if (!window.Chart) { return setTimeout(go, 120); }
      window.Chart.defaults.color = "#8A93A0";
      window.Chart.defaults.borderColor = "rgba(255,255,255,.08)";
      new window.Chart(canvas, {
        type: cfg.chartType || "line",
        data: cfg.data || {},
        options: Object.assign({ responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { boxWidth: 12 } } } }, cfg.options || {})
      });
    })();
  });

  /* -------------------------------------------------------------------- quiz */
  register("quiz", function (el, cfg) {
    var qs = cfg.questions || [], answered = 0, correct = 0;
    var head = '<div class="w-head"><span class="w-kind">Check yourself</span><h4>' +
      esc(cfg.title || "Quick check") + "</h4></div>";
    var body = qs.map(function (q, qi) {
      var opts = (q.options || []).map(function (o, oi) {
        return '<button class="quiz-opt" data-q="' + qi + '" data-o="' + oi + '">' + esc(o) + "</button>";
      }).join("");
      return '<div class="quiz-q" data-q="' + qi + '"><div class="quiz-prompt"><b>' + (qi + 1) + ".</b> " +
        esc(q.q) + "</div><div class='quiz-opts'>" + opts + "</div>" +
        '<div class="quiz-explain"></div></div>';
    }).join("");
    el.innerHTML = head + body + '<div class="quiz-score"></div>';
    el.querySelectorAll(".quiz-opt").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var qi = +btn.getAttribute("data-q"), oi = +btn.getAttribute("data-o"), q = qs[qi];
        var qEl = el.querySelector('.quiz-q[data-q="' + qi + '"]');
        if (qEl.classList.contains("done")) return;
        qEl.classList.add("done");
        var isRight = oi === q.answer;
        answered++; if (isRight) correct++;
        qEl.querySelectorAll(".quiz-opt").forEach(function (b) {
          var o = +b.getAttribute("data-o");
          b.disabled = true;
          if (o === q.answer) b.classList.add("right");
          else if (o === oi) b.classList.add("wrong");
        });
        var ex = qEl.querySelector(".quiz-explain");
        ex.innerHTML = (isRight ? '<span class="quiz-tag ok">Correct</span> ' : '<span class="quiz-tag no">Not quite</span> ') + esc(q.explain || "");
        ex.classList.add("show");
        var sc = el.querySelector(".quiz-score");
        sc.textContent = "Score: " + correct + " / " + qs.length;
        if (answered === qs.length) sc.classList.add("done");
      });
    });
  });

  /* --------------------------------------------------------- curriculum map */
  register("curriculummap", function (el) {
    el.innerHTML = '<div class="cmap-loading">Loading curriculum map…</div>';
    fetch("assets/curriculum.json").then(function (r) { return r.json(); }).then(function (cur) {
      var done = completedSessions();
      var parts = cur.parts.map(function (p) {
        var cards = p.sessions.map(function (sid) {
          var m = cur.sessions[String(sid)];
          var isDone = done.indexOf(sid) >= 0;
          return '<a class="cmap-card part-' + p.id + (isDone ? " done" : "") +
            '" href="session-' + (sid < 10 ? "0" + sid : sid) + '.html" ' +
            'title="' + esc(m.objective) + '">' +
            '<span class="cmap-code">' + esc(m.code) + '</span>' +
            '<span class="cmap-check">&#10003;</span>' +
            '<span class="cmap-title">' + esc(m.title) + "</span>" +
            '<span class="cmap-bridge">' + esc(m.bridge) + "</span></a>";
        }).join("");
        return '<div class="cmap-part"><div class="cmap-part-title">' + esc(p.title) +
          '<span class="cmap-part-theme">' + esc(p.theme) + "</span></div><div class='cmap-grid'>" + cards + "</div></div>";
      }).join("");
      el.innerHTML = parts;
    }).catch(function () {
      el.innerHTML = '<div class="cmap-loading">The curriculum map loads when the site is served over HTTP (it is live on the published site).</div>';
    });
  });

  /* ----------------------------------------------------------- bootstrap --- */
  function hydrate() {
    document.querySelectorAll(".widget[data-widget]").forEach(function (el) {
      if (el.dataset.hydrated) return;
      el.dataset.hydrated = "1";
      var type = el.getAttribute("data-widget"), cfg = {};
      var s = el.querySelector('script[type="application/json"]');
      if (s) { try { cfg = JSON.parse(s.textContent); } catch (e) { /* keep cfg empty */ } }
      var fn = REG[type];
      if (fn) {
        try { fn(el, cfg); }
        catch (e) { el.innerHTML = '<div class="w-err">widget error: ' + esc(e.message) + "</div>"; }
      } else {
        el.innerHTML = '<div class="w-err">unknown widget: ' + esc(type) + "</div>";
      }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", hydrate);
  else hydrate();
})();
