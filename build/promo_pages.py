"""Nosto pages (27.11.2026): /mainosta/ (public numbers + calculator + checkout), /mainosta/kiitos/, /mainosta/ehdot/, /nosto/ (report)
and data/zones.json (the lunch areas of the area picker = the areas a Nosto is sold for). All pages noindex and outside the sitemap."""
import json, math, os, re


def zones(app_js, venues):
    """AREAS of app.js → [{slug, name, lat, lon, lists, share}] (lists = today's lists within 700 m)."""
    rows = re.findall(r'\["([^"]+)", ([0-9.]+), ([0-9.]+)\]', open(app_js).read().split("var AREAS = [", 1)[1].split("];", 1)[0])
    def slug(s):
        s = s.lower().replace("ä", "a").replace("ö", "o").replace("å", "a")
        return re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    out = []
    for n, la, lo in rows:
        la, lo = float(la), float(lo)
        near = [v for v in venues if v["menu"] and math.hypot((v["lat"] - la) * 111, (v["lon"] - lo) * 111 * math.cos(math.radians(la))) < 0.7]
        city = max(((sum(1 for v in near if v["city"] == c), c) for c in {v["city"] for v in near}), default=(0, "helsinki"))[1]
        out.append({"slug": slug(n), "name": n, "lat": la, "lon": lo, "lists": len(near), "city": city})
    tot = sum(z["lists"] for z in out) or 1
    for z in out:
        z["share"] = round(z["lists"] / tot, 4)
    return out


CALC = """<main class="content promo-page">
<p class="ptestnote" id="ptest" hidden>Testitila: maksuja ei veloiteta. Testikortti 4242 4242 4242 4242, mikä tahansa tuleva päiväys ja CVC.</p>
<h1>Nosta ravintolasi lounaskartalla</h1>
<p class="lead">Ravintolasi näkyy ensimmäisenä niille, jotka katsovat lounaita alueellasi juuri lounasaikaan. Hinta lasketaan oikeista näyttömääristä, ja maksat vain valitsemistasi päivistä.</p>
<ol class="psteps"><li><b>Valitse ravintola ja päivät.</b> Laskuri näyttää hinnan ja arvion näytöistä päivä kerrallaan.</li>
<li><b>Maksa kortilla tai MobilePaylla.</b> Kuitti ja ALV-lasku tulevat sähköpostiin.</li>
<li><b>Nosto näkyy heti.</b> Saat raporttilinkin, josta näet näytöt ja klikit.</li></ol>
<section class="box" id="pcalc">
<label>Ravintola<input id="pvname" list="pvlist" placeholder="Kirjoita ravintolan nimi" autocomplete="off"></label><datalist id="pvlist"></datalist>
<p class="pnote" id="pvnote"></p>
<label>Alue<select id="pzone"></select></label>
<p class="pnote">Päivät (enintään 2 nostoa per alue per päivä):</p>
<div class="pdays" id="pdays"></div><p class="pnote" id="pdemand"></p>
<p id="psum">Valitse päivät.</p>
<p><button type="button" class="btn" id="pbuy" disabled>Siirry maksamaan</button> <span id="pmsg" class="pnote"></span></p>
</section>
<h2>Miltä nosto näyttää</h2>
<p>Nosto on oma rivinsä listan ja puhelimen alalaatikon alussa: <b>Mainos · Ravintolan nimi</b>, tämän päivän annos ja hinta ravintolan omalta lounaslistalta. Mainosta ei koskaan näytetä kartan päällä eikä ilman merkintää. Vapaata mainostekstiä ei ole, joten nosto näyttää aina oikean päivän lounaan.</p>
<h2>Miten hinta lasketaan</h2>
<p>Hinta per päivä = arvioidut näytöt × {cpm} € / 1 000 näyttöä × alueen kysyntä. Näyttöarvio on alueen saman viikonpäivän toteutunut määrä (4 viikon mediaani); näyttö lasketaan vain, kun nosto on oikeasti ruudulla vähintään sekunnin. Kun alueen päivät täyttyvät, hinta nousee enintään 50 %. Pienin päivähinta {minday} €, pienin tilaus {minorder} € (alv 0 %). <b>Takuu:</b> jos näyttöjä tulee alle 80 % arviosta, nosto jatkuu automaattisesti seuraavina arkipäivinä.</p>
<h2>Luvut alueittain</h2>
<p class="pnote" id="psite"></p>
<table class="ptable"><thead><tr><th>Alue</th><th>Karttanäytöt 4 vk</th><th>Listoja tänään</th></tr></thead><tbody id="pstats"></tbody></table>
<p class="pnote">Laskurit alkoivat marraskuussa 2026, joten luvut ovat vielä pieniä – siksi hinnatkin ovat pieniä. Ei evästeitä, ei käyttäjätunnisteita.</p>
<p><a href="/mainosta/ehdot/">Mainosehdot</a> · Myyjä BR Entertainment</p>
</main><script src="/promo.js?v={ver}" defer></script>"""

THANKS = """<main class="content promo-page"><h1>Kiitos!</h1><div id="pthanks"><p>Tarkistetaan maksua…</p></div>
<p><a href="/">Takaisin lounaskartalle</a></p></main><script src="/promo.js?v={ver}" defer></script>"""

REPORT = """<main class="content promo-page"><h1>Noston raportti</h1><div id="preport"><p>Ladataan…</p></div>
<p class="pnote">Näyttö = nosto oli ruudulla vähintään sekunnin. Klikki = nostoa napautettiin. Luvut päivittyvät minuuttien viiveellä.</p>
<p><a href="/mainosta/">Osta lisää päiviä</a></p></main><script src="/promo.js?v={ver}" defer></script>"""

TERMS = """<main class="content promo-page"><h1>Mainosehdot – Nosto</h1>
<p>Päivitetty 27.11.2026. Myyjä: BR Entertainment (paivanlounas.fi).</p>
<h2>Mitä ostat</h2><p>Nosto on maksettu näkyvyys Päivän lounas -palvelussa valitulla lounasalueella valittuina arkipäivinä. Nosto näkyy listan ja puhelimen alalaatikon alussa merkinnällä ”Mainos” ja ravintolan nimellä. Sisältö on ravintolan tämän päivän lounas sen omalta listalta; jos listaa ei ole, näytetään ravintolan nimi ja tieto, ettei päivän listaa ole saatavilla.</p>
<h2>Hinta ja maksu</h2><p>Hinta lasketaan laskurissa ennen ostoa (alv 0 % + alv 25,5 %). Maksu veloitetaan heti Stripen kautta. Kuitti ja lasku lähetetään ostajan sähköpostiin.</p>
<h2>Näytöt ja takuu</h2><p>Laskuri näyttää arvion näytöistä. Jos toteutuneita näyttöjä tulee alle 80 % arviosta, nosto jatkuu automaattisesti seuraavina arkipäivinä (enintään 10 lisäpäivää), kun alueella on tilaa. Näytöt ja klikit näkyvät raporttilinkistä.</p>
<h2>Peruutus</h2><p>Ennen ensimmäistä päivää voit perua noston raporttisivulta ja saat koko maksun takaisin. Alkanutta nostoa ei voi perua.</p>
<h2>Poistaminen</h2><p>Päivän lounas voi poistaa noston, jos se on harhaanjohtava tai ravintola ei ole toiminnassa; käyttämättömät päivät palautetaan.</p>
<h2>Rajat</h2><p>Enintään kaksi nostoa per alue per päivä. Nosto ei vaikuta muiden ravintoloiden järjestykseen eikä niiden tietoihin. Mainoksia ei näytetä kartan päällä.</p>
</main>"""


def write(out, page, preview, add_url, venues, app_js, ver, consts):
    zs = zones(app_js, venues)
    json.dump(zs, open(f"{out}/data/zones.json", "w"), ensure_ascii=False)
    pages = {
        "/mainosta/": ("Nosta ravintolasi lounaskartalla | Päivän lounas", "Ravintolan nosto Päivän lounaassa: hinta oikeista näyttömääristä, osto heti.",
                       CALC.replace("{cpm}", str(consts["cpm"])).replace("{minday}", str(consts["min_day"])).replace("{minorder}", str(consts["min_order"]))),
        "/mainosta/kiitos/": ("Kiitos | Päivän lounas", "Noston maksu.", THANKS),
        "/mainosta/ehdot/": ("Mainosehdot | Päivän lounas", "Noston ehdot.", TERMS),
        "/nosto/": ("Noston raportti | Päivän lounas", "Noston näytöt ja klikit.", REPORT),
    }
    for path, (title, desc, body) in pages.items():
        os.makedirs(f"{out}{path}", exist_ok=True)
        add_url(path, False, None)  # never in the sitemap
        open(f"{out}{path}index.html", "w").write(page("fi", title, desc, path, None, body.replace("{ver}", ver), preview, index=False))
    return zs
