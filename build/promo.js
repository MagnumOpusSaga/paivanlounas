// /mainosta/ (calculator + public numbers), /mainosta/kiitos/ and /nosto/ (report). Prices always come from the server.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function eur(c) { return (c / 100).toFixed(2).replace(".", ",") + " €"; }
  function dd(d) { var p = d.split("-"); return +p[2] + "." + +p[1] + "."; }
  var WD = ["su", "ma", "ti", "ke", "to", "pe", "la"];
  function wd(d) { return WD[new Date(d + "T12:00:00Z").getUTCDay()]; }
  function km(a, b) { var dy = (a[0] - b[0]) * 111, dx = (a[1] - b[1]) * 111 * Math.cos(a[0] * Math.PI / 180); return Math.sqrt(dx * dx + dy * dy); }
  var qs = new URLSearchParams(location.search);

  // ---------- /mainosta/
  if ($("pcalc")) {
    var CFG = null, ZONES = [], VEN = [], Q = null, pick = {}, venue = null;
    Promise.all([
      fetch("/api/promo/config").then(function (r) { return r.json(); }).catch(function () { return { enabled: false }; }),
      fetch("/data/zones.json").then(function (r) { return r.json(); }),
      fetch("/data/week.json").then(function (r) { return r.json(); }),
    ]).then(function (a) {
      CFG = a[0]; ZONES = a[1]; VEN = a[2].venues;
      // test mode: the calculator only works for whoever opened /mainosta/?nostotesti=1 (or /?nostotesti=1) on this device
      var tst = false; try { if (qs.get("nostotesti") === "1") localStorage.setItem("pl_nostotesti", "1"); tst = localStorage.getItem("pl_nostotesti") === "1"; } catch (e) {}
      if (CFG.test && !tst) CFG.enabled = false;
      $("ptest").hidden = !CFG.test;
      $("pzone").innerHTML = ZONES.map(function (z) { return '<option value="' + z.slug + '">' + esc(z.name) + "</option>"; }).join("");
      $("pvlist").innerHTML = VEN.map(function (v) { return '<option value="' + esc(v.n + " – " + (v.a || "")) + '">'; }).join("");
      var v0 = qs.get("v"); if (v0) setVenue(VEN.find(function (v) { return v.i === v0; }));
      if (qs.get("z")) $("pzone").value = qs.get("z");
      loadQuote();
      stats();
    });
    function setVenue(v) {
      venue = v || null;
      $("pvname").value = v ? v.n + " – " + (v.a || "") : "";
      if (v) {  // the nearest area to the restaurant
        var best = null, bd = 9;
        ZONES.forEach(function (z) { var d = km([v.y, v.x], [z.lat, z.lon]); if (d < bd) { bd = d; best = z; } });
        if (best) $("pzone").value = best.slug;
        $("pvnote").textContent = bd > 1.5 ? "Lähin lounasalue on " + bd.toFixed(1).replace(".", ",") + " km päässä. Nosto näkyy niille, jotka katsovat lounaita sillä alueella." : "";
      }
    }
    $("pvname").addEventListener("change", function () {
      var val = this.value; setVenue(VEN.find(function (v) { return v.n + " – " + (v.a || "") === val; })); loadQuote();
    });
    $("pzone").addEventListener("change", loadQuote);
    function loadQuote() {
      pick = {};
      fetch("/api/promo/quote?zone=" + $("pzone").value).then(function (r) { return r.json(); }).then(function (q) {
        Q = q; var hasFree = false;
        $("pdays").innerHTML = (q.days || []).map(function (d) {
          var off = d.free <= 0; if (!off) hasFree = true;
          return '<button type="button" class="pday" data-d="' + d.day + '"' + (off ? " disabled" : "") + '><b>' + wd(d.day) + " " + dd(d.day) + "</b><span>" +
            (off ? "varattu" : eur(d.cents) + "<small> · ~" + d.imps + " näyttöä</small>") + "</span></button>";
        }).join("");
        $("pdemand").textContent = q.demand > 1 ? "Alueen kysyntä nostaa hintaa nyt " + Math.round((q.demand - 1) * 100) + " %." : "";
        sum();
      });
    }
    $("pdays").addEventListener("click", function (e) {
      var b = e.target.closest(".pday"); if (!b || b.disabled) return;
      var d = b.getAttribute("data-d"); if (pick[d]) delete pick[d]; else pick[d] = 1;
      b.classList.toggle("on", !!pick[d]); sum();
    });
    function sum() {
      var ds = (Q && Q.days || []).filter(function (d) { return pick[d.day]; });
      var net = ds.reduce(function (s, d) { return s + d.cents; }, 0), imps = ds.reduce(function (s, d) { return s + d.imps; }, 0);
      var vat = Math.round(net * (CFG && CFG.vat || 0.255));
      $("psum").innerHTML = ds.length ? ds.length + " arkipäivää · arvio " + imps + " näyttöä<br>" + eur(net) + " + alv 25,5 % " + eur(vat) + " = <b>" + eur(net + vat) + "</b>" : "Valitse päivät.";
      var minOk = net >= (CFG && CFG.min_order || 3) * 100;
      $("pbuy").disabled = !(CFG && CFG.enabled && venue && ds.length && minOk);
      $("pmsg").textContent = !CFG || !CFG.enabled ? "Maksut avataan pian." : !venue ? "Valitse ensin ravintola." : ds.length && !minOk ? "Pienin tilaus on " + CFG.min_order + " € (alv 0 %)." : "";
    }
    $("pbuy").addEventListener("click", function () {
      var b = this; b.disabled = true; $("pmsg").textContent = "Avataan maksua…";
      fetch("/api/promo/checkout", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ venue: venue.i, zone: $("pzone").value, days: Object.keys(pick) }) })
        .then(function (r) { return r.json(); }).then(function (j) {
          if (j.url) { location.href = j.url; return; }
          $("pmsg").textContent = j.error || "Jokin meni vikaan."; b.disabled = false; loadQuote();
        }).catch(function () { $("pmsg").textContent = "Yhteys katkesi. Yritä uudelleen."; b.disabled = false; });
    });
    function stats() {
      fetch("/api/promo/stats").then(function (r) { return r.json(); }).then(function (s) {
        var rows = s.zones.slice().sort(function (a, b) { return b.views28 - a.views28 || b.lists - a.lists; });
        $("pstats").innerHTML = rows.map(function (z) {
          return "<tr><td>" + esc(z.name) + "</td><td>" + z.views28 + "</td><td>" + z.lists + "</td></tr>";
        }).join("");
        $("psite").textContent = s.site_views28 + " sivunäyttöä " + s.site_days + " päivässä (" + dd(s.since) + " alkaen).";
      });
    }
  }

  // ---------- /mainosta/kiitos/
  if ($("pthanks")) {
    var tries = 0;
    (function poll() {
      fetch("/api/promo/status?s=" + encodeURIComponent(qs.get("s") || "")).then(function (r) { return r.json(); }).then(function (j) {
        if (j.status === "paid" && j.token) {
          var u = "/nosto/?t=" + j.token;
          $("pthanks").innerHTML = "<p><b>Kiitos! Nosto on maksettu.</b> " + esc(j.venue) + " näkyy merkinnällä ”Mainos” valittuina päivinä: " +
            j.days.map(dd).join(", ") + "</p><p>Tallenna tämä raporttilinkki, siitä näet näytöt ja klikit:<br><a href=\"" + u + "\">" + location.origin + u + "</a></p>" +
            "<p>Kuitti ja lasku tulevat Stripeltä antamaasi sähköpostiin.</p>";
        } else if (tries++ < 15) setTimeout(poll, 2000);
        else $("pthanks").innerHTML = "<p>Maksun vahvistus viipyy. Kuitti tulee sähköpostiisi; raporttilinkki tulee näkyviin tälle sivulle, kun päivität sen hetken päästä.</p>";
      });
    })();
  }

  // ---------- /nosto/?t= (report)
  if ($("preport")) {
    var t = qs.get("t") || "";
    fetch("/api/promo/report?t=" + encodeURIComponent(t)).then(function (r) { return r.json(); }).then(function (j) {
      if (j.error) { $("preport").textContent = j.error; return; }
      var all = j.days.concat(j.extra);
      var st = { paid: "Voimassa", refunded: "Peruttu, rahat palautettu", removed: "Poistettu" }[j.status] || j.status;
      $("preport").innerHTML = (j.test ? '<p class="ptestnote">Testitila – oikeaa maksua ei tehty.</p>' : "") +
        "<h2>" + esc(j.venue) + "</h2><p>Tila: <b>" + esc(st) + "</b> · alue " + esc(j.zone) + "</p>" +
        "<p>Näyttöjä <b>" + j.delivered + "</b> / luvattu " + j.promised + " · klikkejä <b>" + j.clicks + "</b>" +
        (j.extra.length ? " · jatkopäiviä takuun takia " + j.extra.length : "") + "</p>" +
        "<table class=\"ptable\"><tr><th>Päivä</th><th>Näytöt</th><th>Klikit</th></tr>" + all.map(function (d) {
          var p = j.per[d] || { imp: 0, click: 0 }; return "<tr><td>" + wd(d) + " " + dd(d) + "</td><td>" + p.imp + "</td><td>" + p.click + "</td></tr>";
        }).join("") + "</table><p>Hinta " + eur(j.net) + " + alv " + eur(j.vat) + ".</p>" +
        (j.can_cancel ? '<p><button type="button" class="btn ghost" id="pcancel">Peru nosto ja palauta maksu</button></p>' : "");
      var c = $("pcancel");
      if (c) c.addEventListener("click", function () {
        if (!c.dataset.sure) { c.dataset.sure = "1"; c.textContent = "Vahvista: peru nosto ja palauta maksu"; return; }  // two clicks, no dialog
        {
          c.disabled = true;
          fetch("/api/promo/cancel", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ t: t }) })
            .then(function (r) { return r.json(); }).then(function (k) { c.outerHTML = "<b>" + (k.ok ? "Peruttu. Rahat palautuvat kortille muutamassa päivässä." : esc(k.error)) + "</b>"; });
        }
      });
    });
  }
})();
