(function () {
  "use strict";
  var main = document.querySelector("main.app");
  var LG = main ? main.getAttribute("data-lang") : "fi";
  var S = {
    fi: { n: " ravintolaa", menu: " – lista", nomenu: "Ei listaa tälle päivälle.", site: "Ravintolan sivu", src: "Lähde", orig: "alkuperäinen",
          wrong: "Väärä tieto?", wrongOk: "Kiitos ilmoituksesta!", onmap: "Kartalla", more: "Näytä lisää", park: "Parkki lähellä",
          like: "Söin täällä – hyvä lounas", liked: "Kiitos! Merkitty suositukseksi", pop: " suosittelee", none: "Ei osumia tällä valinnalla. Kokeile toista suodatinta tai siirrä karttaa.", ad: "Mainos", shN: " lounasta lähellä", shNme: " lounasta lähelläsi", route2: "Reitti", open2: "Lista ja tiedot", venue: "/ravintola/", noloc: "Sijaintia ei saatu.", close: "Sulje", walk: " min kävely", until: "auki ", untilEnd: " asti", closes: "sulkeutuu ", closesEnd: " min päästä", ended: "lounas päättynyt", opens: "lounas ", t3me: "Kolme hyvää lähelläsi",
          t3map: "Kolme hyvää tällä alueella", route: "Reitti", loc: "Näytä sijaintini", fav: "Lisää suosikiksi", unfav: "Poista suosikeista", near: "lähintä näkyvissä", nofav: "Ei vielä suosikkeja – lisää niitä tähdestä ravintolan nimen vierestä.",
          wd: ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"], pp: "https://parkpenny.com/" },
    en: { n: " restaurants", menu: " – with menu", nomenu: "No menu for this day.", site: "Restaurant website", src: "Source", orig: "original",
          wrong: "Wrong info?", wrongOk: "Thanks for letting us know!", onmap: "On map", more: "Show more", park: "Parking nearby",
          like: "I ate here – good lunch", liked: "Thanks! Counted as a recommendation", pop: " recommend", none: "Nothing with this choice. Try another filter or move the map.", ad: "Advertisement", shN: " lunches nearby", shNme: " lunches near you", route2: "Directions", open2: "Menu and details", venue: "/en/restaurant/", noloc: "Could not get your location.", close: "Close", walk: " min walk", until: "open until ", untilEnd: "", closes: "closes in ", closesEnd: " min", ended: "lunch over", opens: "lunch ", t3me: "Three good picks near you",
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
  var touch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  var map = L.map("map", { zoomControl: false, doubleClickZoom: !touch }).setView([60.1680, 24.9400], 15);
  // double tap zooms in one step where you tap (iOS Safari does not pass double taps to the map reliably)
  if (touch) (function () {
    var last = 0, lp = null, el = map.getContainer();
    el.addEventListener("touchend", function (e) {
      if (e.touches.length || e.changedTouches.length !== 1) return;
      var t = e.changedTouches[0], now = Date.now(), p = L.point(t.clientX, t.clientY);
      if (now - last < 320 && lp && p.distanceTo(lp) < 30 && !e.target.closest(".leaflet-marker-icon,.leaflet-control")) {
        var r = el.getBoundingClientRect();
        map.setZoomAround(L.point(t.clientX - r.left, t.clientY - r.top), map.getZoom() + 1);
        last = 0; e.preventDefault(); return;
      }
      last = now; lp = p;
    }, { passive: false });
  })();
  L.control.zoom({ position: "topright" }).addTo(map);
  // basemap: clean OpenFreeMap vector style (free, commercial use ok); OSM raster only if it cannot load
  var dark = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  var ATTR = '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OSM</a>';
  map.attributionControl.setPrefix(false);
  function osm() { L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map); }
  function addScript(src, ok, bad) { var e = document.createElement("script"); e.src = src; e.onload = ok; e.onerror = bad; document.head.appendChild(e); }
  (function () {
    var css = document.createElement("link"); css.rel = "stylesheet"; css.href = "/vendor/maplibre/maplibre-gl.css"; document.head.appendChild(css);
    addScript("/vendor/maplibre/maplibre-gl.js", function () {
      addScript("/vendor/maplibre/leaflet-maplibre-gl.js", function () {
        try { L.maplibreGL({ style: "https://tiles.openfreemap.org/styles/" + (dark ? "dark" : "positron"), attribution: ATTR }).addTo(map); } catch (e) { osm(); }
      }, osm);
    }, osm);
  })();
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
  var CAT = {
    soup: /keitto|soppa|soup|borssi|borscht|ramen|pho\b|chowder|gulassi|goulash/i,
    fish: /kala|lohi|lohta|turska|kuha|siika|muikku|silakka|silli|tonnikala|kampela|ahven|hauki|seiti|katkarap|äyriäi|simpuk|fish|salmon|cod|tuna|shrimp|prawn|seafood|sushi|nigiri/i,
    chicken: /kana|broiler|chicken|pollo|kalkkun|turkey/i,
    meat: /härkä|härän|nauta|naudan|possu|porsa|sika|sian|liha|jauheli|pihvi|lammas|lampa|riista|poro|hirvi|makkara|kinkku|beef|pork|lamb|steak|meatball|bbq|ribs|brisket/i,
    pasta: /pasta|spaget|spaghet|lasagn|penne|tagliat|tortell|ravioli|gnocchi|carbonara|bolognese|risotto|makaroni/i,
    pizza: /pizza|pizz|calzone/i,
    burger: /burger|hampurilai/i,
    asian: /wok|curry|curr|sushi|ramen|pho\b|thai|tikka|masala|korma|nuudel|noodle|dumpling|gyoza|poke|bibimbap|teriyaki|bao\b|udon|katsu|tandoori|biryani|pad |kimchi|bulgogi|dal\b|paneer/i,
    salad: /salaat|salad/i,
    buffet: /buffet|noutopöy|seisova|lounaspöy/i
  };
  function itemText(i) { return (i.t ? i.t + " " : "") + i.d.join(" "); }
  function catHit(v) {  // index of the first dish in the chosen category, -1 if none
    var m = M(v), c = state.cat; if (!m || !c) return -1;
    for (var k = 0; k < m.items.length; k++) {
      var it = m.items[k];
      if (c === "veg" ? ((it.diet || []).some(function (d) { return d === "Veg" || d === "K" || d === "VE"; }) || /kasvis|vegaan|vegan|vegetar|härkis|tofu|seitan|halloumi|falafel/i.test(itemText(it))) : CAT[c].test(itemText(it))) return k;
    }
    return -1;
  }
  function dishLine(v) {  // the dish in the chosen category first, then the rest
    var m = M(v); if (!m) return "";
    var h = catHit(v), ds = m.items.map(function (i, k) {
      var d = i.d[0];
      if (k === h && state.cat !== "veg") for (var j = 0; j < i.d.length; j++) if (CAT[state.cat].test(i.d[j])) { d = i.d[j]; break; }
      return clean(d);
    });
    if (h > 0) ds = [ds[h]].concat(ds.slice(0, h), ds.slice(h + 1));
    return ds.slice(0, 3).join(" · ");
  }
  function timeTxt(v) {
    var h = hours(v); if (!h) return "";
    if (state.day !== today()) return S.until + h[2] + S.untilEnd;
    var d = new Date(), t = d.getHours() * 60 + d.getMinutes();
    if (t >= h[1]) return '<span class="late">' + S.ended + "</span>";
    if (t >= h[0] && h[1] - t <= 45) return '<span class="soon">' + S.closes + (h[1] - t) + S.closesEnd + "</span>";
    return S.until + h[2] + S.untilEnd;
  }
  function hasDiet(v, d) { var m = M(v); return m && m.items.some(function (i) { return (i.diet || []).indexOf(d) >= 0 || (d === "Veg" && (i.diet || []).indexOf("K") >= 0); }); }
  function fmt(p) { return p ? p.toFixed(2).replace(".", ",") + " €" : ""; }
  function dist(v) { return state.me ? km(state.me, [v.y, v.x]) : null; }
  function distTxt(d) { return d == null ? "" : d < 1 ? Math.round(d * 1000) + " m" : d.toFixed(1).replace(".", ",") + " km"; }
  function clean(d) { return String(d || "").replace(/^\s*(?:henkilökunta|henkilöstö|opiskelijat?|staff|students?)(?:\s*(?:&|ja|and|\/)\s*(?:henkilökunta|henkilöstö|opiskelijat?|staff|students?))*\s*:\s*/i, "").replace(/\s*\((?:[A-Za-z]{1,4}(?:[\s,+*\/]+|(?=\))))+\)/g, "").replace(/\s+(?:VL|VE|VEG|L|G|M|K|V|\*)(?:\s*[,\/]\s*(?:VL|VE|VEG|L|G|M|K|V|\*))+(?=\s|$)/g, "").replace(/[\s,;·]+$/, ""); }
  function firstDish(v) { var m = M(v); if (!m) return ""; var h = state.cat ? catHit(v) : 0; var it = m.items[h > 0 ? h : 0]; return it ? clean(it.d[0]) : ""; }
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
    return s + '<p class="pp">' + (withLinks ? '<a href="#" class="onmap" data-go="' + esc(v.i) + '">' + S.onmap + "</a> · " : "") +
      '<a href="' + routeLink(v) + '" target="_blank" rel="noopener">' + S.route + '</a> · <a href="' + ppLink(v) + '" target="_blank" rel="noopener">' + S.park + "</a></p>";
  }
  function head(v) {
    var p = minPrice(v), dk = dist(v);
    var meta = [dk == null ? "" : (dk < 2.5 ? Math.max(1, Math.round(dk * 1000 / 80)) + S.walk : distTxt(dk)), esc(v.d || ""), timeTxt(v)].filter(Boolean).join(" · ");
    var fv = isFav(v.i);
    return '<div class="row"><h3><button type="button" class="fav' + (fv ? " on" : "") + '" data-fav="' + esc(v.i) + '" aria-pressed="' + fv + '" title="' + (fv ? S.unfav : S.fav) + '" aria-label="' + (fv ? S.unfav : S.fav) + '">' + STAR + '</button><a href="' + S.venue + esc(v.i) + '/">' + esc(v.n) + "</a>" + (v.o === "A" ? '<span class="oiva">Oiva A</span>' : "") + "</h3>" +
      (p ? '<span class="from">' + fmt(p) + "</span>" : "") + "</div>" + '<p class="addr">' + (meta || esc(v.a || "")) + "</p>";
  }
  function filtered() {
    var q = state.q.toLowerCase(), f = state.f, dq = params.get("d");
    var out = state.data.filter(function (v) {
      var m = M(v);
      if (f.fav && !isFav(v.i)) return false;
      if (f.stu && !Object.keys(v.ms || {}).some(function (d) { return v.ms[d] && v.ms[d].stu; })) return false;
      if (state.cat && catHit(v) < 0) return false;
      if (f.menu && !m) return false;
      if (f.open && !openNow(v)) return false;
      if (f.oivaA && v.o !== "A") return false;
      if (f.u13) { var p = minPrice(v); if (!p || p >= 13) return false; }
      if (f.etu) { var p2 = minPrice(v); if (!p2 || p2 > 14) return false; }
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
      if (f.pop) return (b.lk || 0) - (a.lk || 0) || a._k - b._k;
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
  // reserved ad places, filled only when the page carries data-ads (AdSense approved + ad units): every 6th card, one list row
  var ADS = null; try { ADS = JSON.parse(document.documentElement.getAttribute("data-ads") || "null"); } catch (e) {}
  function adHtml(kind, tag) {
    if (!ADS || !ADS[kind]) return "";
    return "<" + tag + ' class="adslot ad-' + kind + '"><span class="adlbl">' + (S.ad || "Mainos") + '</span><ins class="adsbygoogle" style="display:block" data-ad-client="' + esc(ADS.c) + '" data-ad-slot="' + esc(ADS[kind]) + '" data-ad-format="' + (kind === "card" ? "fluid" : "auto") + '" data-full-width-responsive="true"></ins></' + tag + ">";
  }
  function fillAds(root) { if (!ADS) return; root.querySelectorAll("ins.adsbygoogle:not([data-adsbygoogle-status])").forEach(function () { try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (e) {} }); }
  function renderList(list) {
    var lv = state.view === "list", n = state.limit, t3 = state.t3 || {}, total = list.length;
    list = list.filter(function (v) { return !t3[v.i]; });  // the three picks are already shown above
    $("count").textContent = total + S.n + (state.f.menu ? S.menu : "") + (list.length > n && !state.f.cheap ? " · " + n + " " + S.near : "");
    if (state.f.fav && !list.length) $("count").textContent = S.nofav;
    $("list").innerHTML = list.slice(0, n).map(function (v, k) {
      var m = M(v);
      return '<li data-i="' + esc(v.i) + '"' + (state.sel === v.i ? ' class="sel"' : "") + ">" + head(v) +
        (lv ? menuHtml(v, true) : (m ? '<p class="dish">' + esc(dishLine(v)) + "</p>" : "")) + "</li>" + (k === 4 ? adHtml("list", "li") : "");
    }).join("");
    fillAds($("list"));
    var more = $("more");
    more.hidden = !(list.length > n); more.textContent = S.more + " (" + (list.length - n) + ")";
  }
  function render() {
    var list = filtered();
    var dt = new Date(state.day + "T12:00:00");
    $("dlabel").textContent = S.wd[dt.getDay()] + " " + dt.getDate() + "." + (dt.getMonth() + 1) + "." + dt.getFullYear();
    renderTop3(list);
    renderList(list);
    renderSheet(list);
    layer.clearLayers(); state.byId = {};
    list.slice(0, 900).forEach(function (v) {
      var mk = pinFor(v);
      if (wide.matches) {
        mk.bindPopup(function () { return '<div class="pop">' + head(v) + menuHtml(v, false) + "</div>"; }, { maxWidth: 320, autoPanPadding: [40, 40] });
        mk.on("popupopen", function () { select(v.i); });
      } else mk.on("click", function () { if (sheetOn()) { setSheet("full"); setTimeout(function () { toCard(v.i); }, 60); } else showCard(v); });
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
  function showCard(v) {
    var c = $("sel");
    c.innerHTML = '<button type="button" class="x" aria-label="' + S.close + '">×</button>' + head(v) + menuHtml(v, true);
    c.hidden = false; select(v.i);
    if (state.view === "map") setView("split");
    var r = c.getBoundingClientRect();
    if (r.top < 0 || r.top > innerHeight * 0.6) c.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function hideCard() { $("sel").hidden = true; state.sel = null; document.querySelectorAll(".pin.sel,.list>li.sel").forEach(function (x) { x.classList.remove("sel"); }); }
  $("sel").addEventListener("click", function (e) {
    if (e.target.closest(".x")) { hideCard(); return; }
    var go = e.target.closest("[data-go]"); if (go) { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  });
  function openOnMap(id) {
    if (state.view === "list") setView(wide.matches ? "split" : "map");
    var m = state.byId[id]; if (!m) return;
    goTo(m.getLatLng(), Math.max(map.getZoom(), 16));
    if (wide.matches) m.openPopup();
    else if (sheetOn()) { setSheet("full"); setTimeout(function () { toCard(id); }, 60); }
    else { var v = state.data.find(function (x) { return x.i === id; }); if (v) showCard(v); }
  }
  // ---- phone: map with a bottom sheet; pulled up it becomes a card carousel (design 3 + 2, Branu 26.11.) ----
  var sheet = $("sheet"), cardsEl = $("cards"), hdr = document.querySelector(".top");
  function setHdr() { document.documentElement.style.setProperty("--hdr", (hdr ? hdr.offsetHeight : 56) + "px"); }
  setHdr(); addEventListener("resize", setHdr);
  function sheetOn() { return !wide.matches && state.view === "split"; }
  function sheetH(px) { document.documentElement.style.setProperty("--sheet-h", px + "px"); }
  function peekH() { return Math.min(256, Math.round(innerHeight * 0.34)); }
  function fullH() { return Math.round(innerHeight - (hdr ? hdr.offsetHeight : 56) - 130); }
  function syncMode() {
    var on = sheetOn();
    main.classList.toggle("sheetmode", on);
    document.documentElement.classList.toggle("sheet-on", on);
    if (on) { sheetH(state.sheet === "full" ? fullH() : peekH()); window.scrollTo(0, 0); }
    else { main.classList.remove("sheetfull", "filters"); }
    setTimeout(fixMapSize, 30);
  }
  function fixMapSize() {
    map.invalidateSize();
    map.eachLayer(function (l) { if (l.getMaplibreMap) { try { l.getMaplibreMap().resize(); } catch (e) {} } });
  }
  addEventListener("resize", function () { if (sheetOn()) sheetH(state.sheet === "full" ? fullH() : peekH()); setTimeout(fixMapSize, 50); });
  function setSheet(st) {
    state.sheet = st; main.classList.toggle("sheetfull", st === "full");
    sheetH(st === "full" ? fullH() : peekH());
    if (st === "full") renderCards(state.lastList || []);
  }
  function walkTxt(v) { var d = dist(v); return d == null ? (v.d || "") : (d < 2.5 ? Math.max(1, Math.round(d * 1000 / 80)) + S.walk : distTxt(d)); }
  function priceTxt(v) { return fmt(minPrice(v)); }
  function renderSheet(list) {
    state.lastList = list;
    if (!sheetOn()) return;
    $("shTitle").textContent = list.length + (state.me ? S.shNme : S.shN);
    $("shRows").innerHTML = list.slice(0, 2).map(function (v, k) {
      return '<li><button type="button" data-k="' + k + '"><span class="r1"><b>' + esc(v.n) + "</b><b>" + priceTxt(v) + '</b></span><span class="r2">' +
        esc(firstDish(v)) + '</span><span class="r3">' + walkTxt(v) + "</span></button></li>";
    }).join("");
    if (state.sheet === "full") renderCards(list);
  }
  function renderCards(list) {
    var LL = list.slice(0, 30); state.cards = LL;
    if (!LL.length) { cardsEl.innerHTML = '<p class="cempty">' + S.none + "</p>"; $("cardPos").textContent = ""; return; }
    cardsEl.innerHTML = LL.map(function (v, k) {
      var m = M(v), more = m && m.items.length > 1 ? m.items.slice(1, 3).map(function (i) { return clean(i.d[0]); }).join(" · ") : "";
      return '<article class="card" data-i="' + esc(v.i) + '"><p class="c1">' + walkTxt(v) + (timeTxt(v) ? " · " + timeTxt(v) : "") + "</p>" +
        '<h3 class="c2">' + esc(firstDish(v) || v.n) + "</h3>" +
        '<p class="c3"><button type="button" class="fav' + (isFav(v.i) ? " on" : "") + '" data-fav="' + esc(v.i) + '" aria-label="' + (isFav(v.i) ? S.unfav : S.fav) + '">' + STAR + "</button>" + esc(v.n) + "</p>" +
        (more ? '<p class="c4">' + esc(more) + "</p>" : "") +
        '<p class="c6">' + (v.lk ? '<span class="popn">' + v.lk + S.pop + "</span>" : "") + '<button type="button" class="likebtn" data-like="' + esc(v.i) + '" data-done="' + S.liked + '">' + S.like + "</button></p>" +
        '<div class="c5"><span class="cp">' + priceTxt(v) + '</span><span class="cb"><a class="btn ghost" href="' + S.venue + esc(v.i) + '/">' + S.open2 + '</a><a class="btn" href="' + routeLink(v) + '" rel="nofollow noopener">' + S.route2 + "</a></span></div></article>" +
        (k % 6 === 5 ? adHtml("card", "article") : "");
    }).join("");
    fillAds(cardsEl); if (window.plMarkLiked) window.plMarkLiked(cardsEl);
    cardsEl.scrollLeft = 0; cardPos(0);
  }
  function cardPos(k) {
    var LL = state.cards || [];
    $("cardPos").textContent = LL.length ? (k + 1) + " / " + LL.length : "";
    var v = LL[k]; if (!v) return;
    select(v.i);
    var m = state.byId[v.i];
    if (m && state.sheet === "full") {
      var strip = Math.max(60, innerHeight - sheet.offsetHeight - (hdr ? hdr.offsetHeight : 56));
      var pt = map.latLngToContainerPoint(m.getLatLng()), want = L.point(map.getSize().x / 2, strip / 2);
      state.quiet = true; map.panBy(pt.subtract(want), { animate: true });
    }
  }
  function toCard(id) {
    var LL = state.cards || [], k = LL.findIndex(function (v) { return v.i === id; });
    if (k < 0) { var v = state.data.find(function (x) { return x.i === id; }); if (!v) return; renderCardsFrom([v].concat(LL.slice(0, 29))); k = 0; }
    var el = cardsEl.querySelector('[data-i="' + CSS.escape(id) + '"]'); if (el) cardsEl.scrollTo({ left: el.offsetLeft - 16, behavior: "smooth" });
    cardPos(k);
  }
  function renderCardsFrom(L) { var keep = state.lastList; renderCards(L); state.lastList = keep; }
  var ct;
  cardsEl.addEventListener("scroll", function () {
    clearTimeout(ct); ct = setTimeout(function () {
      var w = cardsEl.firstElementChild ? cardsEl.firstElementChild.offsetWidth + 12 : 1, el = cardsEl.children[Math.round(cardsEl.scrollLeft / w)];
      if (el && el.getAttribute("data-i")) cardPos((state.cards || []).findIndex(function (v) { return v.i === el.getAttribute("data-i"); }));
    }, 120);
  });
  $("grab").addEventListener("click", function () { setSheet(state.sheet === "full" ? "peek" : "full"); });
  $("shTitle").addEventListener("click", function () { setSheet(state.sheet === "full" ? "peek" : "full"); });
  $("shRows").addEventListener("click", function (e) {
    var b = e.target.closest("[data-k]"); if (!b) return;
    var v = (state.lastList || [])[+b.getAttribute("data-k")]; setSheet("full"); if (v) setTimeout(function () { toCard(v.i); }, 50);
  });
  var y0 = null, h0 = 0, moved = false;
  sheet.addEventListener("touchstart", function (e) {
    if (e.target.closest(".cards,.pills,a,.likebtn")) { y0 = null; return; }
    var inRows = e.target.closest(".shrows"); if (inRows && inRows.scrollTop > 0) { y0 = null; return; }
    y0 = e.touches[0].clientY; h0 = sheet.offsetHeight; moved = false;
  }, { passive: true });
  sheet.addEventListener("touchmove", function (e) {
    if (y0 == null) return;
    var dy = e.touches[0].clientY - y0; if (Math.abs(dy) < 6 && !moved) return;
    moved = true; sheet.classList.add("dragging");
    sheetH(Math.max(120, Math.min(fullH(), h0 - dy)));
    e.preventDefault();
  }, { passive: false });
  sheet.addEventListener("touchend", function (e) {
    if (y0 == null) return; y0 = null; sheet.classList.remove("dragging");
    if (!moved) return;
    var h = sheet.offsetHeight;
    if (state.sheet === "full") setSheet(h < fullH() - 60 ? "peek" : "full");
    else setSheet(h > peekH() + 50 ? "full" : "peek");
  }, { passive: true });
  document.querySelectorAll("[data-pill]").forEach(function (b) {
    b.addEventListener("click", function () {
      var k = b.getAttribute("data-pill");
      document.querySelectorAll("[data-pill]").forEach(function (x) { x.classList.toggle("on", x === b); });
      state.f.cheap = k === "cheap"; state.f.stu = k === "stu"; state.f.pop = k === "pop"; state.cat = k === "veg" ? "veg" : null;
      document.querySelectorAll("[data-f]").forEach(function (x) { var f = x.getAttribute("data-f"); if (f === "cheap" || f === "stu") x.classList.toggle("on", !!state.f[f]); });
      document.querySelectorAll("[data-cat]").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-cat") === state.cat); });
      render(); if (state.sheet === "full") renderCards(state.lastList || []);
    });
  });
  $("asList").addEventListener("click", function () { setSheet("peek"); setView("list"); window.scrollTo(0, 0); });
  $("mfilt").addEventListener("click", function () { main.classList.add("filters"); window.scrollTo(0, 0); });
  $("pdone").addEventListener("click", function () { main.classList.remove("filters"); setTimeout(function () { map.invalidateSize(); }, 50); });
  $("q2").addEventListener("input", function () { var q = $("q"); q.value = this.value; q.dispatchEvent(new Event("input", { bubbles: true })); });
  if (wide.addEventListener) wide.addEventListener("change", function () { syncMode(); if (state.data.length) render(); setTimeout(function () { map.invalidateSize(); }, 50); });
  function setView(v, keep) {
    state.view = v;
    main.classList.toggle("listview", v === "list");
    main.classList.toggle("mapview", v === "map");
    document.querySelectorAll("[data-view]").forEach(function (b) {
      var bv = b.getAttribute("data-view");
      b.classList.toggle("on", bv === v || (bv === "split" && v === "map"));
    });
    if (bigBtn) bigBtn.textContent = mapEl.getAttribute(v === "map" ? "data-back" : "data-big");
    syncMode();
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
    if (favs[id]) delete favs[id]; else { favs[id] = 1; if (window.plFavSent) window.plFavSent(id); }
    saveFavs();
    document.querySelectorAll('[data-fav="' + CSS.escape(id) + '"]').forEach(function (x) {
      var on = !!favs[id]; x.classList.toggle("on", on); x.setAttribute("aria-pressed", on);
      x.title = on ? S.unfav : S.fav; x.setAttribute("aria-label", x.title);
    });
    var mk = state.byId[id], el = mk && mk.getElement && mk.getElement();
    if (el && el.firstChild && el.firstChild.classList) el.firstChild.classList.toggle("fv", !!favs[id]);
    if (state.f.fav) render();
  }, true);
  document.querySelectorAll("[data-cat]").forEach(function (b) {
    b.addEventListener("click", function () {
      var k = b.getAttribute("data-cat"); state.cat = state.cat === k ? null : k;
      document.querySelectorAll("[data-cat]").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-cat") === state.cat); x.setAttribute("aria-pressed", x.getAttribute("data-cat") === state.cat); });
      state.limit = state.view === "list" ? 40 : 30; render();
    });
  });
  $("more").addEventListener("click", function () { state.limit += 40; renderList(filtered()); });
  $("list").addEventListener("click", function (e) {
    var go = e.target.closest("[data-go]");
    if (go) { e.preventDefault(); openOnMap(go.getAttribute("data-go")); return; }
    if (state.view === "list" || e.target.closest("a")) return;
    var li = e.target.closest("li[data-i]"); if (!li) return;
    var id = li.getAttribute("data-i");
    if (wide.matches) { openOnMap(id); return; }
    var open = li.classList.contains("open");
    document.querySelectorAll(".list>li.open").forEach(function (x) { x.classList.remove("open"); var d = x.querySelector(".more-menu"); if (d) d.remove(); });
    if (open) return;
    var v = state.data.find(function (x) { return x.i === id; }); if (!v) return;
    li.classList.add("open"); li.insertAdjacentHTML("beforeend", '<div class="more-menu">' + menuHtml(v, true) + "</div>");
    select(id); var m = state.byId[id]; if (m) goTo(m.getLatLng(), Math.max(map.getZoom(), 15));
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
  function resort() { if (state.me || !state.data.length) return; clearTimeout(mt); mt = setTimeout(function () { var l = filtered(); renderTop3(l); if (state.view !== "list") renderList(l); if (state.sheet !== "full") renderSheet(l); }, 250); }
  map.on("dragend", resort);
  map.on("zoomend", function () { if (state.quiet) return; resort(); });
  map.on("moveend", function () { state.quiet = false; });
  function goTo(ll, z) { state.quiet = true; map.setView(ll, z); }
  var meDot = null, locBtn;
  function locate(fromList) {
    if (!navigator.geolocation) { $("count").textContent = S.noloc; return; }
    if (locBtn) locBtn.classList.add("busy"); $("locfab").classList.add("busy");
    navigator.geolocation.getCurrentPosition(function (p) {
      if (locBtn) locBtn.classList.remove("busy"); $("locfab").classList.remove("busy"); $("locfab").classList.add("on");
      state.me = [p.coords.latitude, p.coords.longitude]; goTo(state.me, 16);
      if (meDot) meDot.setLatLng(state.me);
      else meDot = L.circleMarker(state.me, { radius: 8, color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }).addTo(map);
      state.quiet = true; render();
      if (fromList && !sheetOn()) { var t = $("top3s").hidden ? $("count") : $("top3s"); t.scrollIntoView({ behavior: "smooth", block: "start" }); }
    }, function () { if (locBtn) locBtn.classList.remove("busy"); $("locfab").classList.remove("busy"); $("count").textContent = S.noloc; }, { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 });
  }
  $("near").addEventListener("click", function () { locate(true); });
  $("locfab").addEventListener("click", function () { locate(false); });
  // phones: find the user right away (the browser asks once); the list then starts from where you are
  if (touch && navigator.geolocation) setTimeout(function () { locate(false); }, 300);
  var Loc = L.Control.extend({ options: { position: "topright" }, onAdd: function () {
    var d = L.DomUtil.create("div", "leaflet-bar leaflet-control");
    locBtn = L.DomUtil.create("a", "locbtn", d); locBtn.href = "#"; locBtn.setAttribute("role", "button");
    locBtn.title = S.loc; locBtn.setAttribute("aria-label", S.loc);
    locBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="currentColor"/><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 1v4M12 19v4M1 12h4M19 12h4" stroke="currentColor" stroke-width="2"/></svg>';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.on(locBtn, "click", function (e) { L.DomEvent.preventDefault(e); locate(false); });
    return d; } });
  new Loc().addTo(map);
  fetch("/data/week.json").then(function (r) { return r.json(); }).then(function (d) {
    state.data = d.venues; state.days = d.days;
    var nPop = d.venues.filter(function (v) { return v.lk; }).length;
    document.querySelectorAll('[data-pill="pop"]').forEach(function (b) { b.hidden = nPop < 5; });
    var t = today(); state.day = d.days.indexOf(t) >= 0 ? t : d.date;
    document.querySelectorAll(".days button").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-day") === state.day); });
    var pv = params.get("view"); if (!pv) { try { pv = localStorage.getItem("pl_view"); } catch (e) {} }
    var v = params.get("v");
    setView(pv === "list" && !v ? "list" : "split", true);
    if (v && !state.byId[v]) { state.f.menu = false; document.querySelector('[data-f="menu"]').classList.remove("on"); render(); }
    if (v && state.byId[v]) openOnMap(v);
    // links from articles: ?q=hernekeitto (search), ?f=stu or ?f=etu (filter chips)
    var pq = params.get("q");
    if (pq) { ["q", "q2"].forEach(function (id) { var e = $(id); if (e) e.value = pq; }); var qe = $("q"); if (qe) qe.dispatchEvent(new Event("input", { bubbles: true })); }
    (params.get("f") || "").split(",").forEach(function (k) {
      var b = k && document.querySelector('[data-f="' + k + '"]');
      if (b && !b.classList.contains("on")) b.click();
    });
    if (params.get("d")) { var pts = filtered().map(function (x) { return [x.y, x.x]; }); if (pts.length) map.fitBounds(pts, { padding: [30, 30] }); }
  });
})();
