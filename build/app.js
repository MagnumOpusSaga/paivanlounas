(function () {
  "use strict";
  var state = { f: { menu: true }, q: "", me: null, data: [], markers: null, byId: {} };
  var OIVA = { A: "😃 Oivallinen", B: "🙂 Hyvä", C: "😐 Korjattavaa", D: "☹️ Huono" };
  var params = new URLSearchParams(location.search);
  var map = L.map("map", { zoomControl: false }).setView([60.1699, 24.9384], 14);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "© OpenStreetMap"
  }).addTo(map);
  state.markers = L.layerGroup().addTo(map);

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function slug(s) { return (s || "").toLowerCase().replace(/ä/g, "a").replace(/ö/g, "o").replace(/å/g, "a").normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
  function minPrice(v) {
    if (!v.m) return null;
    var p = v.m.items.map(function (i) { return i.p; }).filter(function (x) { return x && x >= 4; });
    return p.length ? Math.min.apply(null, p) : null;
  }
  function km(a, b) {
    var dy = (a[0] - b[0]) * 111.0, dx = (a[1] - b[1]) * 111.0 * Math.cos(a[0] * Math.PI / 180);
    return Math.sqrt(dx * dx + dy * dy);
  }
  function openNow(v) {
    if (!v.m || !v.m.hours) return false;
    var m = v.m.hours.match(/(\d{1,2})[:.](\d{2})\s*[–-]\s*(\d{1,2})[:.](\d{2})/);
    if (!m) return false;
    var d = new Date(), t = d.getHours() * 60 + d.getMinutes();
    return t >= (+m[1]) * 60 + (+m[2]) && t < (+m[3]) * 60 + (+m[4]);
  }
  function hasDiet(v, d) {
    return v.m && v.m.items.some(function (i) { return (i.diet || []).indexOf(d) >= 0; });
  }
  function fmt(p) { return p ? p.toFixed(2).replace(".", ",") + " €" : ""; }
  function menuHtml(v) {
    if (!v.m) return '<p class="nomenu">Ei tämän päivän listaa.' + (v.w ? ' <a href="' + esc(v.w) + '" rel="nofollow noopener" target="_blank">Ravintolan sivu</a>' : "") + "</p>";
    var s = '<ul class="menu">' + v.m.items.map(function (i) {
      return "<li>" + (i.t ? "<b>" + esc(i.t) + "</b> " : "") + esc(i.d.join(" · ")) + " " +
        (i.diet || []).map(function (d) { return '<span class="diet">' + esc(d) + "</span>"; }).join("") +
        (i.p ? ' <span class="price">' + fmt(i.p) + "</span>" : "") + "</li>";
    }).join("") + "</ul>";
    return s + '<p class="src">Lähde: ' + esc(v.m.src) + (v.m.url ? ' – <a href="' + esc(v.m.url) + '" rel="nofollow noopener" target="_blank">alkuperäinen</a>' : "") + "</p>";
  }
  function card(v) {
    var p = minPrice(v), dist = state.me ? km(state.me, [v.y, v.x]) : null;
    return '<h3><a href="/ravintola/' + esc(v.i) + '/">' + esc(v.n) + "</a>" + (v.o ? ' <span class="oiva" title="Oiva">' + OIVA[v.o].split(" ")[0] + "</span>" : "") + "</h3>" +
      '<p class="addr">' + esc(v.a || "") + (v.d ? " · " + esc(v.d) : "") + (dist != null ? " · " + (dist < 1 ? Math.round(dist * 1000) + " m" : dist.toFixed(1).replace(".", ",") + " km") : "") +
      (p ? ' · <b>alk. ' + fmt(p) + "</b>" : "") + "</p>";
  }
  function filtered() {
    var q = state.q.toLowerCase(), f = state.f, dq = params.get("d");
    var out = state.data.filter(function (v) {
      if (f.menu && !v.m) return false;
      if (f.open && !openNow(v)) return false;
      if (f.oivaA && v.o !== "A") return false;
      for (var d of ["Veg", "G", "L", "M"]) if (f[d] && !hasDiet(v, d)) return false;
      if (dq && slug(v.d) !== dq) return false;
      if (q) {
        var hay = (v.n + " " + (v.a || "") + " " + (v.d || "") + " " + (v.m ? v.m.items.map(function (i) { return i.d.join(" "); }).join(" ") : "")).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
    out.sort(function (a, b) {
      if (f.cheap) return (minPrice(a) || 99) - (minPrice(b) || 99);
      if (state.me) return km(state.me, [a.y, a.x]) - km(state.me, [b.y, b.x]);
      return (b.m ? 1 : 0) - (a.m ? 1 : 0) || a.n.localeCompare(b.n, "fi");
    });
    return out;
  }
  function render() {
    var list = filtered();
    document.getElementById("count").textContent = list.length + " ravintolaa" + (state.f.menu ? " – lista tänään" : "");
    var ol = document.getElementById("list");
    ol.innerHTML = list.slice(0, 200).map(function (v) { return '<li data-i="' + esc(v.i) + '">' + card(v) + "</li>"; }).join("");
    state.markers.clearLayers();
    list.slice(0, 900).forEach(function (v) {
      var mk = L.circleMarker([v.y, v.x], { radius: v.m ? 7 : 4, weight: 1, color: "#fff", fillColor: v.m ? "#1f6f4a" : "#8a8f8c", fillOpacity: 0.95 });
      mk.bindPopup(function () { return '<div class="pop">' + card(v) + menuHtml(v) + "</div>"; }, { maxWidth: 320 });
      mk.addTo(state.markers);
      state.byId[v.i] = mk;
    });
  }
  document.getElementById("list").addEventListener("click", function (e) {
    var li = e.target.closest("li[data-i]");
    if (!li || e.target.tagName === "A") return;
    var mk = state.byId[li.getAttribute("data-i")];
    if (mk) { map.flyTo(mk.getLatLng(), 17); mk.openPopup(); }
  });
  document.querySelectorAll(".chips button").forEach(function (b) {
    b.addEventListener("click", function () {
      var k = b.getAttribute("data-f"); state.f[k] = !state.f[k]; b.classList.toggle("on", !!state.f[k]); render();
    });
  });
  var qt;
  document.getElementById("q").addEventListener("input", function (e) { clearTimeout(qt); qt = setTimeout(function () { state.q = e.target.value.trim(); render(); }, 150); });
  document.getElementById("near").addEventListener("click", function () {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(function (p) {
      state.me = [p.coords.latitude, p.coords.longitude];
      map.setView(state.me, 16);
      L.circleMarker(state.me, { radius: 8, color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 1 }).addTo(map);
      render();
    }, function () { alertless("Sijaintia ei saatu."); }, { enableHighAccuracy: true, timeout: 8000 });
  });
  function alertless(t) { document.getElementById("count").textContent = t; }
  fetch("/data/today.json").then(function (r) { return r.json(); }).then(function (d) {
    state.data = d.venues;
    render();
    var v = params.get("v");
    if (v && state.byId[v] === undefined) { state.f.menu = false; document.querySelector('[data-f="menu"]').classList.remove("on"); render(); }
    if (v && state.byId[v]) { map.setView(state.byId[v].getLatLng(), 17); state.byId[v].openPopup(); }
    if (params.get("d")) {
      var pts = filtered().map(function (x) { return [x.y, x.x]; });
      if (pts.length) map.fitBounds(pts, { padding: [30, 30] });
    }
  });
})();
