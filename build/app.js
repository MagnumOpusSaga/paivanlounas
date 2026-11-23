(function () {
  "use strict";
  var root = document.querySelector("main.app");
  var LG = root ? root.getAttribute("data-lang") : "fi";
  var S = {
    fi: { n: " ravintolaa", menu: " – lista", nomenu: "Ei listaa tälle päivälle.", site: "Ravintolan sivu", src: "Lähde", orig: "alkuperäinen",
          from: "alk.", wrong: "Väärä tieto?", wrongOk: "Kiitos ilmoituksesta!", onmap: "📍 Kartalla", more: "Näytä lisää", park: "🅿️ Parkki lähellä", venue: "/ravintola/", noloc: "Sijaintia ei saatu.",
          wd: ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"], pp: "https://parkpenny.com/" },
    en: { n: " restaurants", menu: " – with menu", nomenu: "No menu for this day.", site: "Restaurant website", src: "Source", orig: "original",
          from: "from", wrong: "Wrong info?", wrongOk: "Thanks for letting us know!", onmap: "📍 On map", more: "Show more", park: "🅿️ Parking nearby", venue: "/en/restaurant/", noloc: "Could not get your location.",
          wd: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"], pp: "https://parkpenny.com/en/" }
  }[LG];
  var state = { f: { menu: true }, q: "", me: null, data: [], day: null, days: [], markers: null, byId: {}, view: "map", limit: 60 };
  var main = document.querySelector("main.app");
  var params = new URLSearchParams(location.search);
  var map = L.map("map", { zoomControl: false }).setView([60.1699, 24.9384], 14);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
  state.markers = L.layerGroup().addTo(map);

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function slug(s) { return (s || "").toLowerCase().replace(/ä/g, "a").replace(/ö/g, "o").replace(/å/g, "a").normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
  function M(v) { return v.ms ? v.ms[state.day] : null; }
  function minPrice(v) {
    var m = M(v); if (!m) return null;
    var p = m.items.map(function (i) { return i.p; }).filter(function (x) { return x && x >= 4; });
    return p.length ? Math.min.apply(null, p) : null;
  }
  function km(a, b) { var dy = (a[0] - b[0]) * 111.0, dx = (a[1] - b[1]) * 111.0 * Math.cos(a[0] * Math.PI / 180); return Math.sqrt(dx * dx + dy * dy); }
  function today() { var d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function openNow(v) {
    var m = M(v); if (!m || !m.hours || state.day !== today()) return false;
    var r = m.hours.match(/(\d{1,2})[:.](\d{2})\s*[–-]\s*(\d{1,2})[:.](\d{2})/); if (!r) return false;
    var d = new Date(), t = d.getHours() * 60 + d.getMinutes();
    return t >= (+r[1]) * 60 + (+r[2]) && t < (+r[3]) * 60 + (+r[4]);
  }
  function hasDiet(v, d) { var m = M(v); return m && m.items.some(function (i) { return (i.diet || []).indexOf(d) >= 0; }); }
  function fmt(p) { return p ? p.toFixed(2).replace(".", ",") + " €" : ""; }
  function ppLink(v) { return S.pp + "?lat=" + v.y + "&lon=" + v.x + "&q=" + encodeURIComponent(v.n) + "&dur=60"; }
  function menuHtml(v) {
    var m = M(v);
    var s = !m ? '<p class="nomenu">' + S.nomenu + (v.w ? ' <a href="' + esc(v.w) + '" rel="nofollow noopener" target="_blank">' + S.site + "</a>" : "") + "</p>"
      : '<ul class="menu">' + m.items.map(function (i) {
        return "<li>" + (i.t ? "<b>" + esc(i.t) + "</b> " : "") + esc(i.d.join(" · ")) + " " +
          (i.diet || []).map(function (d) { return '<span class="diet">' + esc(d) + "</span>"; }).join("") +
          (i.p ? ' <span class="price">' + fmt(i.p) + "</span>" : "") + "</li>";
      }).join("") + "</ul>" + '<p class="src">' + S.src + ": " + esc(m.src) + (m.url ? ' – <a href="' + esc(m.url) + '" rel="nofollow noopener" target="_blank">' + S.orig + "</a>" : "") +
        ' · <a href="#" class="wrong" data-wrong="' + esc(v.i) + '" data-day="' + state.day + '" data-ok="' + esc(S.wrongOk) + '" rel="nofollow">' + S.wrong + "</a></p>";
    return s + '<p class="pp"><a href="' + ppLink(v) + '" target="_blank" rel="noopener">' + S.park + "</a></p>";
  }
  function card(v) {
    var p = minPrice(v), dist = state.me ? km(state.me, [v.y, v.x]) : null;
    return '<h3><a href="' + S.venue + esc(v.i) + '/">' + esc(v.n) + "</a>" + (v.o ? ' <span class="oiva">' + { A: "😃", B: "🙂", C: "😐", D: "☹️" }[v.o] + "</span>" : "") + "</h3>" +
      '<p class="addr">' + esc(v.a || "") + (v.d ? " · " + esc(v.d) : "") + (dist != null ? " · " + (dist < 1 ? Math.round(dist * 1000) + " m" : dist.toFixed(1).replace(".", ",") + " km") : "") +
      (p ? " · <b>" + S.from + " " + fmt(p) + "</b>" : "") + "</p>";
  }
  function filtered() {
    var q = state.q.toLowerCase(), f = state.f, dq = params.get("d");
    var out = state.data.filter(function (v) {
      var m = M(v);
      if (f.menu && !m) return false;
      if (f.open && !openNow(v)) return false;
      if (f.oivaA && v.o !== "A") return false;
      for (var d of ["Veg", "G", "L", "M"]) if (f[d] && !hasDiet(v, d)) return false;
      if (dq && slug(v.d) !== dq) return false;
      if (q) {
        var hay = (v.n + " " + (v.a || "") + " " + (v.d || "") + " " + (m ? m.items.map(function (i) { return i.d.join(" "); }).join(" ") : "")).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
    out.sort(function (a, b) {
      if (f.cheap) return (minPrice(a) || 99) - (minPrice(b) || 99);
      if (state.me) return km(state.me, [a.y, a.x]) - km(state.me, [b.y, b.x]);
      return (M(b) ? 1 : 0) - (M(a) ? 1 : 0) || a.n.localeCompare(b.n, "fi");
    });
    return out;
  }
  function render() {
    var list = filtered();
    document.getElementById("count").textContent = list.length + S.n + (state.f.menu ? S.menu : "");
    var dt = new Date(state.day + "T12:00:00");
    document.getElementById("dlabel").textContent = S.wd[dt.getDay()] + " " + dt.getDate() + "." + (dt.getMonth() + 1) + "." + dt.getFullYear();
    var lv = state.view === "list", n = lv ? state.limit : 200;
    document.getElementById("list").innerHTML = list.slice(0, n).map(function (v) {
      return '<li data-i="' + esc(v.i) + '">' + card(v) + (lv ? menuHtml(v).replace('<p class="pp">', '<p class="pp"><a href="#" class="onmap" data-go="' + esc(v.i) + '">' + S.onmap + "</a> ") : "") + "</li>";
    }).join("");
    var more = document.getElementById("more");
    more.hidden = !(lv && list.length > n); more.textContent = S.more + " (" + (list.length - n) + ")";
    state.markers.clearLayers(); state.byId = {};
    list.slice(0, 900).forEach(function (v) {
      var mk = L.circleMarker([v.y, v.x], { radius: M(v) ? 7 : 4, weight: 1, color: "#fff", fillColor: M(v) ? "#1f6f4a" : "#8a8f8c", fillOpacity: 0.95 });
      mk.bindPopup(function () { return '<div class="pop">' + card(v) + menuHtml(v) + "</div>"; }, { maxWidth: 320 });
      mk.addTo(state.markers); state.byId[v.i] = mk;
    });
  }
  function setView(v, keep) {
    state.view = v; main.classList.toggle("listview", v === "list");
    document.querySelectorAll(".views button").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-view") === v); });
    if (!keep) { try { localStorage.setItem("pl_view", v); } catch (e) {} }
    if (v === "map") setTimeout(function () { map.invalidateSize(); }, 0);
    state.limit = 60; render();
  }
  document.querySelectorAll(".views button").forEach(function (b) { b.addEventListener("click", function () { setView(b.getAttribute("data-view")); }); });
  document.getElementById("more").addEventListener("click", function () { state.limit += 60; render(); });
  document.getElementById("list").addEventListener("click", function (e) {
    var go = e.target.closest("[data-go]");
    if (go) {
      e.preventDefault(); var id = go.getAttribute("data-go"); setView("map");
      var m = state.byId[id]; if (m) { map.setView(m.getLatLng(), 17); m.openPopup(); }
      return;
    }
    if (state.view === "list") return;
    var li = e.target.closest("li[data-i]"); if (!li || e.target.tagName === "A") return;
    var mk = state.byId[li.getAttribute("data-i")]; if (mk) { map.flyTo(mk.getLatLng(), 17); mk.openPopup(); }
  });
  document.querySelectorAll(".chips button").forEach(function (b) {
    b.addEventListener("click", function () { var k = b.getAttribute("data-f"); state.f[k] = !state.f[k]; b.classList.toggle("on", !!state.f[k]); render(); });
  });
  document.querySelectorAll(".days button").forEach(function (b) {
    b.addEventListener("click", function () {
      state.day = b.getAttribute("data-day");
      document.querySelectorAll(".days button").forEach(function (x) { x.classList.toggle("on", x === b); });
      render();
    });
  });
  var qt;
  document.getElementById("q").addEventListener("input", function (e) { clearTimeout(qt); qt = setTimeout(function () { state.q = e.target.value.trim(); render(); }, 150); });
  document.getElementById("near").addEventListener("click", function () {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(function (p) {
      state.me = [p.coords.latitude, p.coords.longitude]; map.setView(state.me, 16);
      L.circleMarker(state.me, { radius: 8, color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 1 }).addTo(map); render();
    }, function () { document.getElementById("count").textContent = S.noloc; }, { enableHighAccuracy: true, timeout: 8000 });
  });
  fetch("/data/week.json").then(function (r) { return r.json(); }).then(function (d) {
    state.data = d.venues; state.days = d.days;
    var pv = params.get("view"); if (!pv) { try { pv = localStorage.getItem("pl_view"); } catch (e) {} }
    if (pv === "list" && !params.get("v")) { state.view = "list"; main.classList.add("listview");
      document.querySelectorAll(".views button").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-view") === "list"); }); }
    var t = today(); state.day = d.days.indexOf(t) >= 0 ? t : d.date;
    document.querySelectorAll(".days button").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-day") === state.day); });
    render();
    var v = params.get("v");
    if (v && !state.byId[v]) { state.f.menu = false; document.querySelector('[data-f="menu"]').classList.remove("on"); render(); }
    if (v && state.byId[v]) { map.setView(state.byId[v].getLatLng(), 17); state.byId[v].openPopup(); }
    if (params.get("d")) { var pts = filtered().map(function (x) { return [x.y, x.x]; }); if (pts.length) map.fitBounds(pts, { padding: [30, 30] }); }
  });
})();
