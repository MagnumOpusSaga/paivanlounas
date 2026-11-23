(function () {
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
