(function () {
  // "Väärä tieto?" links (venue pages and the map/list app)
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("[data-wrong]"); if (!a) return;
    e.preventDefault();
    if (a.getAttribute("data-sent")) return;
    var fd = new FormData(); fd.append("venue", a.getAttribute("data-wrong")); fd.append("day", a.getAttribute("data-day"));
    a.setAttribute("data-sent", "1");
    fetch("/api/report", { method: "POST", body: fd }).then(function (r) {
      if (!r.ok) throw 0;
      var s = document.createElement("span"); s.className = "wrongok"; s.textContent = a.getAttribute("data-ok"); a.replaceWith(s);
    }).catch(function () { a.removeAttribute("data-sent"); });
  });
  // restaurant tells where its menu is published
  var f = document.querySelector("form.suggest"); if (!f) return;
  f.addEventListener("submit", function (e) {
    e.preventDefault();
    var b = f.querySelector("button"); b.disabled = true;
    fetch(f.action, { method: "POST", body: new FormData(f) }).then(function (r) {
      if (!r.ok) throw 0;
      f.querySelector("label").hidden = true; b.hidden = true; f.querySelector(".ok").hidden = false;
    }).catch(function () { b.disabled = false; });
  });
})();
