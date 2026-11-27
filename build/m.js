// Anonymous counters (no cookies, no ids): page view, what gets clicked, and quick exits (<15 s, no click). See /tietosuoja/.
(function () {
  var d = document.documentElement, P = d.getAttribute("data-pt") || "other", H = d.getAttribute("data-hl") === "1" ? 1 : 0;
  var K = (d.getAttribute("data-k") || "").slice(0, 40);
  var q = [["view", ""]], t0 = Date.now(), clicked = false, exitSent = false, searched = false;
  function send() {
    if (!q.length) return;
    var b = JSON.stringify({ p: P, h: H, l: d.lang || "fi", e: q.splice(0, 20) });
    try { if (navigator.sendBeacon && navigator.sendBeacon("/api/e", new Blob([b], { type: "application/json" }))) return; } catch (e) {}
    try { fetch("/api/e", { method: "POST", body: b, keepalive: true, headers: { "content-type": "application/json" } }); } catch (e) {}
  }
  function ev(k) { clicked = true; q.push(["click", k]); if (q.length >= 10) send(); }
  window.plEvent = ev;
  // landed here from a search engine: which restaurant / district pages people really look for (index gate)
  if (K && /(^|\.)(google|bing|duckduckgo|ecosia|yahoo|yandex|startpage|qwant)\./.test((document.referrer.split("/")[2] || ""))) q.push(["land", K]);
  function kind(a) {
    var k = a.getAttribute("data-ev"); if (k) return k;
    if (a.closest(".nearby")) return "nearby";
    if (a.matches(".days button,[data-day]")) return "day";
    if (a.matches("[data-cat]")) return "filter:" + a.getAttribute("data-cat");
    if (a.matches("[data-f]")) return "filter:" + a.getAttribute("data-f");
    if (a.matches("[data-fav]")) return "fav";
    if (a.matches("[data-view]")) return "view:" + a.getAttribute("data-view");
    if (a.matches("#near,.locbtn")) return "locate";
    if (a.matches("[data-share]")) return "share";
    if (a.closest(".src")) return "source";
    var h = a.getAttribute("href") || "";
    if (!h || h.charAt(0) === "#") return a.tagName === "BUTTON" ? "button" : "";
    if (/google\.[a-z]+\/maps/.test(h)) return "route";
    if (/parkpenny\.com/.test(h)) return "parkpenny";
    if (/[?&]v=/.test(h)) return "map";
    if (/^\/(en\/)?(ravintola|restaurant)\//.test(h)) return "venue";
    if (/^\/(en\/)?(lounas|lunch)\//.test(h)) return "area";
    if (/^https?:/.test(h)) return "website";
    return "nav";
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a,button"); if (!a) return;
    var k = kind(a); if (k) ev(k);
  }, true);
  // "Söin täällä – hyvä lounas": one per restaurant per day on this device; counted for "Suosituimmat"
  var today = new Date(Date.now() + 2 * 3600e3).toISOString().slice(0, 10);
  function liked(v) { try { return localStorage.getItem("pl_like_" + v) === today; } catch (e) { return false; } }
  function markLiked(root) {
    (root || document).querySelectorAll("[data-like]").forEach(function (b) {
      if (liked(b.getAttribute("data-like"))) { b.classList.add("done"); b.textContent = b.getAttribute("data-done") || b.textContent; b.disabled = true; }
    });
  }
  window.plMarkLiked = markLiked;
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-like]"); if (!b || b.disabled) return;
    e.preventDefault(); e.stopPropagation();
    var v = b.getAttribute("data-like");
    try { localStorage.setItem("pl_like_" + v, today); } catch (x) {}
    try { fetch("/api/like", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ v: v, k: "like" }), keepalive: true }); } catch (x) {}
    markLiked();
  }, true);
  window.plFavSent = function (v) {
    try { if (localStorage.getItem("pl_favsent_" + v)) return; localStorage.setItem("pl_favsent_" + v, "1"); } catch (x) {}
    try { fetch("/api/like", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ v: v, k: "fav" }), keepalive: true }); } catch (x) {}
  };
  document.addEventListener("DOMContentLoaded", function () { markLiked(); });
  document.addEventListener("input", function (e) {
    if (!searched && e.target && e.target.id === "q") { searched = true; ev("search"); }
  }, true);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState !== "hidden") return;
    if (!clicked && !exitSent && Date.now() - t0 < 15000) { exitSent = true; q.push(["quick_exit", ""]); }
    send();
  });
  setTimeout(send, 4000);
})();

// dark/light toggle in the header (◐): light by default, dark only when chosen (feedback 27.11.)
(function () {
  var b = document.getElementById("themebtn");
  if (!b) return;
  b.addEventListener("click", function () {
    var on = !document.documentElement.classList.contains("dark");
    try { localStorage.setItem("pl_theme", on ? "dark" : "light"); } catch (e) {}
    location.reload();  // the map style is chosen at load
  });
})();
