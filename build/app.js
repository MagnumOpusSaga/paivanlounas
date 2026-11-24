(function () {
  "use strict";
  var main = document.querySelector("main.app");
  var LG = main ? main.getAttribute("data-lang") : "fi";
  var S = {
    fi: { n: " ravintolaa", menu: " – lista", nomenu: "Ei listaa tälle päivälle.", site: "Ravintolan sivu", src: "Lähde", orig: "alkuperäinen",
          wrong: "Väärä tieto?", wrongOk: "Kiitos ilmoituksesta!", onmap: "Kartalla", more: "Näytä lisää", park: "Parkki lähellä",
          venue: "/ravintola/", noloc: "Sijaintia ei saatu.", walk: " min kävely", until: "auki ", untilEnd: " asti", t3me: "Kolme hyvää lähelläsi",
          t3map: "Kolme hyvää tällä alueella", route: "Reitti", loc: "Näytä sijaintini", fav: "Lisää suosikiksi", unfav: "Poista suosikeista", near: "lähintä näkyvissä", nofav: "Ei vielä suosikkeja – lisää niitä tähdestä ravintolan nimen vierestä.",
          wd: ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"], pp: "https://parkpenny.com/" },
    en: { n: " restaurants", menu: " – with menu", nomenu: "No menu for this day.", site: "Restaurant website", src: "Source", orig: "original",
          wrong: "Wrong info?", wrongOk: "Thanks for letting us know!", onmap: "On map", more: "Show more", park: "Parking nearby",
          venue: "/en/restaurant/", noloc: "Could not get your location.", walk: " min walk", until: "open until ", untilEnd: "", t3me: "Three good picks near you",
          t3map: "Three good picks in this area", route: "Directions", loc: "Show my location", fav: "Add to favourites", unfav: "Remove from favourites", near: "nearest shown", nofav: "No favourites yet – add them with the star next to a restaurant name.",
          wd: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"], pp: "https://parkpenny.com/en/" }
  }[LG];
  var favs = {}; try { (JSON.parse(localStorage.getItem("pl_fav") || "[]")).forEach(function (k) { favs[k] = 1; }); } catch (e) {}
  function isFav(id) { return !!favs[id]; }
  function saveFavs() { try { localStorage.setItem("pl_fav", JSON.stringify(Object.keys(favs))); } catch (e) {} }
  var STAR = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2l-5.7 3.1 1.2-6.4-4.7-4.4 6.4-.8z"/></svg>';
  var state = { f: { menu: true }, q: "", me: null, data: [], day: null, days: [], byId: {}, view: "split", limit: 30, sel: null };
  var params = new URLSearchParams(location.search);
  var wide = window.matchMedia("(min-width: 900px)");
  var map = L.map("map", { zoomControl: false }).setView([60.1680, 24.9400], 15);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
  var layer = L.layerGroup().addTo(map);
  // mobile: one small button on the map itself (full-screen map / back to list) instead of a floating bar over the content
  var mapEl = document.getElementById("map"), bigBtn;
  var Ctl = L.Control.extend({ options: { position: "topleft" }, onAdd: function () {
    var d = L.DomUtil.create("div", "mapctl leaflet-control");
    bigBtn = L.DomUtil.create("button", "mapbtn", d); bigBtn.type = "button"; bigBtn.textContent = mapEl.getAttribute("data-big");
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.on(bigBtn, "click", function () { setView(state.view === "map" ? "split" : "map"); if (state.view === "split") window.scrollTo(0, 0); });
    return d; } });
  new Ctl().addTo(map);

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function slug(s) { return (s || "").toLowerCase().replace(/ä/g, "a").replace(/ö/g, "o").replace(/å/g, "a").normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
  function M(v) { return v.ms ? v.ms[state.day] : null; }
  function minPrice(v) {
    var m = M(v); if (!m) return null;
    var p = m.items.map(function (i) { return i.p; }).filter(function (x) { return x && x >= 5 && x <= 25; });
    return p.length ? Math.min.apply(null, p) : null;
  }
  function km(a, b) { var dy = (a[0] - b[0]) * 111.0, dx = (a[1] - b[1]) * 111.0 * Math.cos(a[0] * Math.PI / 180); return Math.sqrt(dx * dx + dy * dy); }
  function today() { var d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function hours(v) { var m = M(v); var r = m && m.hours && m.hours.match(/(\d{1,2})[:.](\d{2})\s*[–-]\s*(\d{1,2})[:.](\d{2})/); return r ? [(+r[1]) * 60 + (+r[2]), (+r[3]) * 60 + (+r[4]), r[3] + "." + r[4]] : null; }
  function openNow(v) {
    var h = hours(v); if (!h || state.day !== today()) return false;
    var d = new Date(), t = d.getHours() * 60 + d.getMinutes(); return t >= h[0] && t < h[1];
  }
  function hasDiet(v, d) { var m = M(v); return m && m.items.some(function (i) { return (i.diet || []).indexOf(d) >= 0 || (d === "Veg" && (i.diet || []).indexOf("K") >= 0); }); }
  function fmt(p) { return p ? p.toFixed(2).replace(".", ",") + " €" : ""; }
  function dist(v) { return state.me ? km(state.me, [v.y, v.x]) : null; }
  function distTxt(d) { return d == null ? "" : d < 1 ? Math.round(d * 1000) + " m" : d.toFixed(1).replace(".", ",") + " km"; }
  function clean(d) { return String(d || "").replace(/\s*\((?:[A-Za-z]{1,4}[\s,+*\/]*)+\)/g, "").replace(/[\s,;·]+$/, ""); }
  function firstDish(v) { var m = M(v); var it = m && m.items[0]; return it ? clean(it.d[0]) : ""; }
  function ppLink(v) { return S.pp + "?lat=" + v.y + "&lon=" + v.x + "&q=" + encodeURIComponent(v.n) + "&dur=60"; }
  function routeLink(v) { return "https://www.google.com/maps/dir/?api=1&destination=" + v.y + "," + v.x; }

  function menuHtml(v, withLinks) {
    var m = M(v);
    var s = !m ? '<p class="nomenu">' + S.nomenu + (v.w ? ' <a href="' + esc(v.w) + '" rel="nofollow noopener" target="_blank">' + S.site + "</a>" : "") + "</p>"
      : '<ul class="menu">' + m.items.map(function (i) {
        return "<li>" + (i.t ? "<b>" + esc(i.t) + "</b> " : "") + esc(i.d.join(" · ")) +
          (i.diet || []).map(function (d) { return '<span class="diet">' + esc(d) + "</span>"; }).join("") +
          (i.p ? ' <span class="price">' + fmt(i.p) + "</span>" : "") + "</li>";
      }).join("") + "</ul>" + '<p class="src">' + S.src + ": " + esc(m.src) + (m.url ? ' – <a href="' + esc(m.url) + '" rel="nofollow noopener" target="_blank">' + S.orig + "</a>" : "") +
        ' · <a href="#" class="wrong" data-wrong="' + esc(v.i) + '" data-day="' + state.day + '" data-ok="' + esc(S.wrongOk) + '" rel="nofollow">' + S.wrong + "</a></p>";
    return s + '<p class="pp">' + (withLinks ? '<a href="#" class="onmap" data-go="' + esc(v.i) + '">' + S.onmap + "</a>" : "") +
      '<a href="' + routeLink(v) + '" target="_blank" rel="noopener">' + S.route + '</a> · <a href="' + ppLink(v) + '" target="_blank" rel="noopener">' + S.park + "</a></p>";
  }
  function head(v) {
    var p = minPrice(v), h = hours(v);
    var meta = [distTxt(dist(v)), v.d, h ? S.until + h[2] + S.untilEnd : ""].filter(Boolean).join(" · ");
    var fv = isFav(v.i);
    return '<div class="row"><h3><button type="button" class="fav' + (fv ? " on" : "") + '" data-fav="' + esc(v.i) + '" aria-pressed="' + fv + '" title="' + (fv ? S.unfav : S.fav) + '" aria-label="' + (fv ? S.unfav : S.fav) + '">' + STAR + '</button><a href="' + S.venue + esc(v.i) + '/">' + esc(v.n) + "</a>" + (v.o === "A" ? '<span class="oiva">Oiva A</span>' : "") + "</h3>" +
      (p ? '<span class="from">' + fmt(p) + "</span>" : "") + "</div>" + '<p class="addr">' + esc(meta || v.a || "") + "</p>";
  }
  function filtered() {
    var q = state.q.toLowerCase(), f = state.f, dq = params.get("d");
    var out = state.data.filter(function (v) {
      var m = M(v);
      if (f.fav && !isFav(v.i)) return false;
      if (f.menu && !m) return false;
      if (f.open && !openNow(v)) return false;
      if (f.oivaA && v.o !== "A") return false;
      if (f.u13) { var p = minPrice(v); if (!p || p >= 13) return false; }
      for (var d of ["Veg", "G", "L", "M"]) if (f[d] && !hasDiet(v, d)) return false;
      if (dq && slug(v.d) !== dq) return false;
      if (q) {
        var hay = (v.n + " " + (v.a || "") + " " + (v.d || "") + " " + (m ? m.items.map(function (i) { return i.d.join(" "); }).join(" ") : "")).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
    var ref = state.me || [map.getCenter().lat, map.getCenter().lng];
    out.forEach(function (v) { v._k = km(ref, [v.y, v.x]); });
    out.sort(function (a, b) {
      var fa = isFav(a.i) ? 0 : 1, fb = isFav(b.i) ? 0 : 1;
      if (fa !== fb) return fa - fb;
      if (f.cheap) return (minPrice(a) || 99) - (minPrice(b) || 99);
      return a._k - b._k;
    });
    return out;
  }
  // three good picks: menu with a price, open now when the day is today, nearest to you (or to the map centre)
  function renderTop3(list) {
    var box = $("top3s");
    state.t3 = {};
    if (state.f.fav || (state.view === "list" && !state.me)) { box.hidden = true; return; }
    var ref = state.me || [map.getCenter().lat, map.getCenter().lng];
    var isToday = state.day === today();
    var c = list.filter(function (v) { return M(v) && minPrice(v) && (!isToday || !hours(v) || openNow(v)); })
      .map(function (v) { return [km(ref, [v.y, v.x]), v]; }).filter(function (x) { return x[0] < 1.5; })
      .sort(function (a, b) { return a[0] - b[0]; }).slice(0, 3);
    if (c.length < 3) { box.hidden = true; return; }
    c.forEach(function (x) { state.t3[x[1].i] = 1; });
    $("t3h").textContent = state.me ? S.t3me : S.t3map;
    $("top3").innerHTML = c.map(function (x) {
      var v = x[1], h = hours(v), mins = Math.max(1, Math.round(x[0] * 1000 / 80));
      return '<a href="' + S.venue + esc(v.i) + '/" data-t3="' + esc(v.i) + '"><span class="tm"><span>' + esc(v.n) + "</span><span>" + (state.me ? mins + S.walk : distTxt(x[0])) + "</span></span>" +
        '<span class="td">' + esc(firstDish(v)) + '</span><span class="tp"><span>' + (h ? S.until + h[2] + S.untilEnd : esc(v.d || "")) + "</span><b>" + fmt(minPrice(v)) + "</b></span></a>";
    }).join("");
    box.hidden = false;
  }
  function pinFor(v) {
    var p = minPrice(v), m = M(v);
    if (m && p) return L.marker([v.y, v.x], { icon: L.divIcon({ className: "", html: '<span class="pin' + (isFav(v.i) ? " fv" : "") + '">' + fmt(p).replace(" €", "") + "</span>", iconSize: [0, 0] }), riseOnHover: true });
    return L.circleMarker([v.y, v.x], { radius: m ? 6 : 4, weight: 1.5, color: "#fff", fillColor: m ? "#c2410c" : "#9b8e86", fillOpacity: 0.95 });
  }
  function renderList(list) {
    var lv = state.view === "list", n = state.limit, t3 = state.t3 || {}, total = list.length;
    list = list.filter(function (v) { return !t3[v.i]; });  // the three picks are already shown above
    $("count").textContent = total + S.n + (state.f.menu ? S.menu : "") + (list.length > n && !state.f.cheap ? " · " + n + " " + S.near : "");
    if (state.f.fav && !list.length) $("count").textContent = S.nofav;
    $("list").innerHTML = list.slice(0, n).map(function (v) {
      var m = M(v);
      return '<li data-i="' + esc(v.i) + '"' + (state.sel === v.i ? ' class="sel"' : "") + ">" + head(v) +
        (lv ? menuHtml(v, true) : (m ? '<p class="dish">' + esc(m.items.slice(0, 3).map(function (i) { return clean(i.d[0]); }).join(" · ")) + "</p>" : "")) + "</li>";
    }).join("");
    var more = $("more");
    more.hidden = !(list.length > n); more.textContent = S.more + " (" + (list.length - n) + ")";
  }
  function render() {
    var list = filtered();
    var dt = new Date(state.day + "T12:00:00");
    $("dlabel").textContent = S.wd[dt.getDay()] + " " + dt.getDate() + "." + (dt.getMonth() + 1) + "." + dt.getFullYear();
    renderTop3(list);
    renderList(list);
    layer.clearLayers(); state.byId = {};
    list.slice(0, 900).forEach(function (v) {
      var mk = pinFor(v);
      mk.bindPopup(function () { return '<div class="pop">' + head(v) + menuHtml(v, false) + "</div>"; }, { maxWidth: 320 });
      mk.on("popupopen", function () { select(v.i); });
      mk.addTo(layer); state.byId[v.i] = mk;
    });
  }
  function select(id) {
    state.sel = id;
    document.querySelectorAll(".list>li.sel").forEach(function (x) { x.classList.remove("sel"); });
    var li = document.querySelector('.list>li[data-i="' + CSS.escape(id) + '"]');
    if (li) { li.classList.add("sel"); if (wide.matches) li.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    document.querySelectorAll(".pin.sel").forEach(function (x) { x.classList.remove("sel"); });
    var mk = state.byId[id], el = mk && mk.getElement && mk.getElement();
    if (el && el.firstChild && el.firstChild.classList) el.firstChild.classList.add("sel");
  }
  function openOnMap(id) {
    if (state.view === "list") setView(wide.matches ? "split" : "map");
    var m = state.byId[id]; if (!m) return;
    map.setView(m.getLatLng(), Math.max(map.getZoom(), 16)); m.openPopup();
    if (!wide.matches && state.view === "split") window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function setView(v, keep) {
    state.view = v;
    main.classList.toggle("listview", v === "list");
    main.classList.toggle("mapview", v === "map");
    document.querySelectorAll("[data-view]").forEach(function (b) {
      var bv = b.getAttribute("data-view");
      b.classList.toggle("on", bv === v || (bv === "split" && v === "map"));
    });
    if (bigBtn) bigBtn.textContent = mapEl.getAttribute(v === "map" ? "data-back" : "data-big");
    if (!keep) { try { localStorage.setItem("pl_view", v === "list" ? "list" : "split"); } catch (e) {} }
    setTimeout(function () { map.invalidateSize(); }, 0);
    state.limit = v === "list" ? 40 : 30; render();
  }
  document.querySelectorAll("[data-view]").forEach(function (b) {
    b.addEventListener("click", function () {
      var v = b.getAttribute("data-view");
      if (v === state.view && !wide.matches) v = "split";
      setView(v);
    });
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-fav]"); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var id = b.getAttribute("data-fav");
    if (favs[id]) delete favs[id]; else favs[id] = 1;
    saveFavs();
    document.querySelectorAll('[data-fav="' + CSS.escape(id) + '"]').forEach(function (x) {
      var on = !!favs[id]; x.classList.toggle("on", on); x.setAttribute("aria-pressed", on);
      x.title = on ? S.unfav : S.fav; x.setAttribute("aria-label", x.title);
    });
    var mk = state.byId[id], el = mk && mk.getElement && mk.getElement();
    if (el && el.firstChild && el.firstChild.classList) el.firstChild.classList.toggle("fv", !!favs[id]);
    if (state.f.fav) render();
  }, true);
  $("more").addEventListener("click", function () { state.limit += 40; renderList(filtered()); });
  $("list").addEventListener("click", function (e) {
    var go = e.target.closest("[data-go]");
    if (go) { e.preventDefault(); openOnMap(go.getAttribute("data-go")); return; }
    if (state.view === "list" || e.target.closest("a")) return;
    var li = e.target.closest("li[data-i]"); if (li) openOnMap(li.getAttribute("data-i"));
  });
  $("top3").addEventListener("click", function (e) {
    var a = e.target.closest("[data-t3]"); if (!a || !wide.matches) return;
    e.preventDefault(); openOnMap(a.getAttribute("data-t3"));
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
  var qt, mt;
  $("q").addEventListener("input", function (e) { clearTimeout(qt); qt = setTimeout(function () { state.q = e.target.value.trim(); render(); }, 150); });
  map.on("moveend", function () { if (state.me || !state.data.length) return; clearTimeout(mt); mt = setTimeout(function () { var l = filtered(); renderTop3(l); if (state.view !== "list") renderList(l); }, 250); });
  var meDot = null, locBtn;
  function locate() {
    if (!navigator.geolocation) { $("count").textContent = S.noloc; return; }
    if (locBtn) locBtn.classList.add("busy");
    navigator.geolocation.getCurrentPosition(function (p) {
      if (locBtn) locBtn.classList.remove("busy");
      state.me = [p.coords.latitude, p.coords.longitude]; map.setView(state.me, 16);
      if (meDot) meDot.setLatLng(state.me);
      else meDot = L.circleMarker(state.me, { radius: 8, color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }).addTo(map);
      render();
    }, function () { if (locBtn) locBtn.classList.remove("busy"); $("count").textContent = S.noloc; }, { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 });
  }
  $("near").addEventListener("click", locate);
  var Loc = L.Control.extend({ options: { position: "topright" }, onAdd: function () {
    var d = L.DomUtil.create("div", "leaflet-bar leaflet-control");
    locBtn = L.DomUtil.create("a", "locbtn", d); locBtn.href = "#"; locBtn.setAttribute("role", "button");
    locBtn.title = S.loc; locBtn.setAttribute("aria-label", S.loc);
    locBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="currentColor"/><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4" stroke="currentColor" stroke-width="2"/></svg>';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.on(locBtn, "click", function (e) { L.DomEvent.preventDefault(e); locate(); });
    return d; } });
  new Loc().addTo(map);
  fetch("/data/week.json").then(function (r) { return r.json(); }).then(function (d) {
    state.data = d.venues; state.days = d.days;
    var t = today(); state.day = d.days.indexOf(t) >= 0 ? t : d.date;
    document.querySelectorAll(".days button").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-day") === state.day); });
    var pv = params.get("view"); if (!pv) { try { pv = localStorage.getItem("pl_view"); } catch (e) {} }
    var v = params.get("v");
    setView(pv === "list" && !v ? "list" : "split", true);
    if (v && !state.byId[v]) { state.f.menu = false; document.querySelector('[data-f="menu"]').classList.remove("on"); render(); }
    if (v && state.byId[v]) { map.setView(state.byId[v].getLatLng(), 17); state.byId[v].openPopup(); }
    if (params.get("d")) { var pts = filtered().map(function (x) { return [x.y, x.x]; }); if (pts.length) map.fitBounds(pts, { padding: [30, 30] }); }
  });
})();
