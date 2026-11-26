"""Data articles (Finnish only, one page per question). Every number on these pages is computed from the day's lunch lists
at build time; rules, prices and limits come from the official source linked next to them (checked date in SRC).
A sentence is only printed when its number exists, so nothing here is filler that stays the same day after day."""
import datetime
import json
import os
import re
import statistics
from zoneinfo import ZoneInfo

CHECKED = "26.11.2026"  # when the official figures below were last checked – update together with the figures
SRC = {
    "vero26": ("Verohallinnon päätös luontoisetujen laskentaperusteista 2026, 10, 13 ja 14 §",
               "https://vero.fi/syventavat-vero-ohjeet/paatokset/47380/verohallinnon-paatos-vuodelta-2026-toimitettavassa-verotuksessa-noudatettavista-luontoisetujen-laskentaperusteista/"),
    "vero27": ("Verohallinnon päätös luontoisetujen laskentaperusteista 2027, 10, 13 ja 14 §",
               "https://www.vero.fi/syventavat-vero-ohjeet/paatokset/47380/verohallinnon-paatos-vuodelta-2027-toimitettavassa-verotuksessa-noudatettavista-luontoisetujen-laskentaperusteista/"),
    "kela": ("Kela: Ateriatuki", "https://www.kela.fi/ateriatuki"),
    "yle_herne": ("Yle: Miksi me syömme edelleen hernekeittoa torstaisin? (2018)", "https://yle.fi/a/3-10086553"),
    "yle_pv": ("Yle: Puolustusvoimissa tehdään torstaisin yli 20 000 annosta hernekeittoa (2020)", "https://yle.fi/a/3-11643692"),
}
ETU = {"2026": (8.80, 14.00), "2027": (9.00, 14.40)}
KELA = {"tuki": 2.80, "max": 3.10}
PEA = re.compile(r"hernekeit|hernerok|hernesop|ärtsoppa|pea soup|split pea", re.I)
PANCAKE = re.compile(r"pannukak|pannari|ugnspannkak|pancake", re.I)
PATHS = {"etu": "/lounasetu-helsinki/", "hinta": "/lounaan-hinta-helsinki/", "stu": "/opiskelijalounas-helsinki/", "herne": "/hernekeitto-torstai-helsinki/"}


def fi_num(x, d=0):
    s = f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def pct(a, b):
    return round(100 * a / b) if b else 0


def src_link(k):
    n, u = SRC[k]
    return f'<a href="{u}" rel="noopener">{n}</a> (tarkistettu {CHECKED})'


def write_articles(ctx):
    """ctx: out, preview, venues, show_day, days, likes, page, add_url, esc, fmt_price, lunch_price, clean_dish, datestr, ad_block, gate."""
    out, venues, day = ctx["out"], ctx["venues"], ctx["show_day"]
    esc, fp, lp, page, add_url = ctx["esc"], ctx["fmt_price"], ctx["lunch_price"], ctx["page"], ctx["add_url"]
    now = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
    upd = f"{now.day}.{now.month}.{now.year} klo {now.hour}.{now.minute:02d}"
    ds = ctx["datestr"](day, "fi")
    with_m = [v for v in venues if v["menu"]]
    priced = [(v, lp(v["menu"])) for v in with_m]
    priced = [(v, p) for v, p in priced if p]
    ps = sorted(p for _, p in priced)
    n_m, n_p = len(with_m), len(ps)
    own = f'Lähde: Päivän lounaan keräämät lounaslistat, {ds}: {n_m} ravintolan lista, joista {n_p}:ssä hinta. Päivitetty {upd}.'
    written = {}

    def meta(extra=""):
        return f'<p class="artmeta">{own}{" " + extra if extra else ""} Julkaisija BR Entertainment.</p>'

    def emit(key, title, desc, h1, body, ok, sig, crumb):
        path = PATHS[key]
        html = (f'<main class="content article"><nav class="crumbs"><a href="/">Lounas Helsinki</a> › {esc(crumb)}</nav>'
                f'<h1>{esc(h1)}</h1>{body}</main>')
        os.makedirs(f"{out}{path}", exist_ok=True)
        ix = add_url(path, ok, sig)
        open(f"{out}{path}index.html", "w").write(page("fi", title, desc, path, None, html, ctx["preview"], index=ix))
        written[path] = ix

    def area_stats(min_n=5):
        by = {}
        for v, p in priced:
            if v.get("district"):
                by.setdefault((v["dslug"], v["district"]), []).append(p)
        return {k: (statistics.median(x), len(x), x) for k, x in by.items() if len(x) >= min_n}

    def area_a(k):
        return f'<a href="/lounas/{k[0]}/">{esc(k[1])}</a>'

    # price history: one row per day (kept between runs in the gate cache), used for "hinta nousi / laski" once there is history
    hist_p = ctx["history_path"]
    hist = {}
    try:
        hist = json.load(open(hist_p))
    except Exception:
        pass
    if n_p >= 50:
        hist[day] = {"med": round(statistics.median(ps), 2), "n": n_p,
                     "le14": sum(1 for p in ps if p <= 14.0), "le1440": sum(1 for p in ps if p <= 14.40)}
        try:
            json.dump(hist, open(hist_p, "w"), separators=(",", ":"))
        except Exception:
            pass

    # ---------- 1. Lounasetu ----------
    if n_p:
        le14 = sum(1 for p in ps if p <= 14.00)
        le1440 = sum(1 for p in ps if p <= 14.40)
        lt88 = sum(1 for p in ps if p < 8.80)
        over = [(v, p) for v, p in priced if p > 14.00]
        A = area_stats()
        a_share = sorted(((k, sum(1 for p in x if p <= 14.0) / n, n) for k, (_, n, x) in A.items()), key=lambda z: z[1])
        rows = "".join(f'<tr><td>{area_a(k)}</td><td>{pct(s * n, n)} %</td><td>{n}</td></tr>' for k, s, n in a_share[:5])
        rows_hi = "".join(f'<tr><td>{area_a(k)}</td><td>{pct(s * n, n)} %</td><td>{n}</td></tr>' for k, s, n in a_share[::-1][:5])
        share = pct(le14, n_p)
        verdict = "Kyllä, useimmiten" if share >= 75 else ("Osittain" if share >= 40 else "Ei useimmiten")
        y27 = f"Vuoden 2027 alusta yläraja on 14,40 euroa, jolla saisi tämän päivän lounaista {pct(le1440, n_p)} %." if le1440 != le14 else "Vuoden 2027 alusta yläraja nousee 14,40 euroon; tämän päivän hinnoilla se ei toisi yhtään lounasta lisää rajan alle."
        body = f"""<p class="lead">{verdict}: työnantaja voi ladata lounasetua vuonna 2026 enintään 14,00 euroa työpäivää kohden, ja
<b>{pct(le14, n_p)} % Helsingin lounaista ({le14}/{n_p})</b> maksaa tänään enintään sen verran. {y27}</p>
{meta('Hinta on ravintolan edullisin lounasvaihtoehto.')}
<h2>Lounasedun rajat 2026 ja 2027</h2>
<table class="facts"><tr><th></th><th>2026</th><th>2027</th></tr>
<tr><td>Ravintoedun verotusarvo, kun työnantajan kustannus on rajojen välissä</td><td>8,80 €</td><td>9,00 €</td></tr>
<tr><td>Ladattava enimmäismäärä työpäivää kohden (maksuväline, esim. lounaskortti)</td><td>14,00 €</td><td>14,40 €</td></tr>
<tr><td>Lounassetelin arvostus enintään 14,00 € / 14,40 € nimellisarvoon asti</td><td colspan="2">75 % nimellisarvosta, vähintään verotusarvo</td></tr></table>
<p class="src">Lähteet: {src_link('vero26')}; {src_link('vero27')}. Ladattu saldo koskee vain todellisia työpäiviä, joina työnantaja ei muuten järjestä ruokailua.</p>
<h2>Riittääkö 14 € tänään?</h2>
<ul class="stats"><li><b>{le14}</b> lounasta {n_p}:stä maksaa enintään 14,00 € ({pct(le14, n_p)} %).</li>
<li><b>{n_p - le14}</b> lounasta on yli 14,00 €; niissä erotus maksetaan itse.</li>
{f'<li><b>{lt88}</b> lounasta maksaa alle 8,80 €.</li>' if lt88 else ''}
<li>Mediaanilounas maksaa <b>{fp(statistics.median(ps))}</b>.</li></ul>
<p><a class="btn" href="/?f=etu">Näytä kartalla lounaat, joihin 14 € riittää</a></p>
{ctx['ad_block']('content', 'fi')}
{f'<h2>Missä 14 € riittää huonoiten</h2><p>Alueet, joilla on tänään vähintään 5 hinnoiteltua lounasta. Osuus = enintään 14,00 € maksavien lounaiden osuus.</p><table class="facts"><tr><th>Alue</th><th>≤ 14 €</th><th>Lounaita</th></tr>{rows}</table><h2>Missä 14 € riittää parhaiten</h2><table class="facts"><tr><th>Alue</th><th>≤ 14 €</th><th>Lounaita</th></tr>{rows_hi}</table>' if len(a_share) >= 6 else ''}
<h2>Näin luvut on laskettu</h2>
<p>Luvut lasketaan joka arkiaamu niistä Helsingin ravintoloista, joiden lounaslista ja hinta löytyvät tälle päivälle. Kunkin ravintolan hinnaksi otetaan
listan edullisin 5–25 euron lounasvaihtoehto. Osuus on siksi <b>arvio</b>: kalliimpi annos samassa paikassa voi ylittää rajan, ja ravintolat, joiden listalla ei ole hintaa, puuttuvat laskusta.
Vero- ja rajatiedot ovat Verohallinnon päätöksistä, eivät tämän sivun omia arvioita.</p>
<p>Koko hintajakauma alueittain: <a href="{PATHS['hinta']}">Lounaan hinta Helsingissä</a>.</p>"""
        emit("etu", "Lounasetu 2026 ja 2027 – riittääkö 14 € lounaaseen Helsingissä? | Päivän lounas",
             f"Lounasedun yläraja on 14,00 € (2027: 14,40 €). Tänään {pct(le14, n_p)} % Helsingin lounaista maksaa enintään 14 €. Luvut päivittyvät joka arkiaamu.",
             "Lounasetu 2026 – riittääkö 14 € Helsingissä?", body, n_p >= 50, [le14, le1440, n_p, [(k, round(s, 2)) for k, s, _ in a_share]], "Lounasetu")

    # ---------- 2. Lounaan hinta ----------
    if n_p:
        med = statistics.median(ps)
        q1, _, q3 = statistics.quantiles(ps, n=4) if n_p >= 4 else (ps[0], 0, ps[-1])
        buckets = [("alle 11 €", 0, 11), ("11–12,99 €", 11, 13), ("13–14,99 €", 13, 15), ("15–16,99 €", 15, 17), ("17 € tai yli", 17, 99)]
        brow = "".join(f'<tr><td>{n}</td><td>{sum(1 for p in ps if lo <= p < hi)}</td><td>{pct(sum(1 for p in ps if lo <= p < hi), n_p)} %</td></tr>' for n, lo, hi in buckets)
        A = area_stats()
        by_med = sorted(A.items(), key=lambda kv: kv[1][0])
        cheap_a = "".join(f'<tr><td>{area_a(k)}</td><td>{fp(m)}</td><td>{n}</td></tr>' for k, (m, n, _) in by_med[:5])
        dear_a = "".join(f'<tr><td>{area_a(k)}</td><td>{fp(m)}</td><td>{n}</td></tr>' for k, (m, n, _) in by_med[::-1][:5])
        lo_v, hi_v = min(priced, key=lambda x: x[1]), max(priced, key=lambda x: x[1])
        # week: median per day so far this week
        wk = []
        for d in ctx["days"]:
            pd = [lp(v["ms"][d]) for v in venues if v["ms"].get(d)]
            pd = [p for p in pd if p]
            if len(pd) >= 50:
                wk.append((d, statistics.median(pd), len(pd)))
        wrow = "".join(f'<tr><td>{ctx["datestr"](d, "fi")}</td><td>{fp(m)}</td><td>{n}</td></tr>' for d, m, n in wk)
        # history line only once there are at least 28 days between the first and the latest stored day
        hk = sorted(hist)
        trend = ""
        if hk and (datetime.date.fromisoformat(hk[-1]) - datetime.date.fromisoformat(hk[0])).days >= 28:
            m0, m1 = hist[hk[0]]["med"], hist[hk[-1]]["med"]
            trend = (f'<p>Mediaanihinta oli {fp(m0)} {ctx["datestr"](hk[0], "fi")} ja on nyt {fp(m1)} '
                     f'({"+" if m1 >= m0 else "−"}{fi_num(abs(m1 - m0), 2)} €, {len(hk)} mittauspäivää).</p>')
        body = f"""<p class="lead">Lounas maksaa Helsingissä tänään tyypillisesti <b>{fp(med)}</b> (mediaani). Puolet lounaista maksaa {fp(q1)}–{fp(q3)};
halvin on {fp(lo_v[1])} ja kallein {fp(hi_v[1])}.</p>
{meta('Hinta on ravintolan edullisin lounasvaihtoehto.')}
{trend}
<h2>Hintajakauma tänään</h2>
<table class="facts"><tr><th>Hinta</th><th>Lounaita</th><th>Osuus</th></tr>{brow}</table>
<p><a class="btn" href="/halvin-lounas-helsinki/">Halvimmat lounaat tänään</a> <a class="btn ghost" href="/?f=u13">Alle 13 € kartalla</a></p>
{ctx['ad_block']('content', 'fi')}
{f'<h2>Edullisimmat alueet</h2><p>Alueen mediaanihinta, alueilla joilla on tänään vähintään 5 hinnoiteltua lounasta.</p><table class="facts"><tr><th>Alue</th><th>Mediaani</th><th>Lounaita</th></tr>{cheap_a}</table><h2>Kalleimmat alueet</h2><table class="facts"><tr><th>Alue</th><th>Mediaani</th><th>Lounaita</th></tr>{dear_a}</table>' if len(by_med) >= 6 else ''}
{f'<h2>Tämä viikko</h2><table class="facts"><tr><th>Päivä</th><th>Mediaani</th><th>Lounaita</th></tr>{wrow}</table>' if len(wk) >= 2 else ''}
<h2>Näin luvut on laskettu</h2>
<p>Mukana ovat Helsingin ravintolat, joiden tämän päivän lounaslista ja hinta löytyvät. Kunkin ravintolan hinnaksi otetaan listan edullisin 5–25 euron vaihtoehto, joten
luvut kuvaavat edullisinta tapaa syödä lounas kussakin paikassa. Opiskelija- ja henkilökuntahinnat eivät ole mukana. Hintakehitys näytetään, kun mittauksia on kertynyt vähintään 4 viikolta.</p>
<p>Lounasedun 14 euron raja suhteessa näihin hintoihin: <a href="{PATHS['etu']}">Lounasetu – riittääkö 14 €</a>.</p>"""
        emit("hinta", "Lounaan hinta Helsingissä 2026 – mitä lounas maksaa tänään | Päivän lounas",
             f"Lounaan mediaanihinta Helsingissä tänään on {fp(med)} ({n_p} ravintolaa). Hintajakauma, edullisimmat ja kalleimmat alueet, päivittyy joka arkiaamu.",
             "Lounaan hinta Helsingissä", body, n_p >= 50, [round(med, 2), round(q1, 2), round(q3, 2), n_p, [(k, m) for k, (m, _, _) in by_med]], "Lounaan hinta")

    # ---------- 3. Opiskelijalounas ----------
    stu = [v for v in with_m if v["menu"].get("stu")]
    if stu:
        uni = [v for v in stu if (v["menu"].get("src") or "").lower().startswith("unicafe") or v["name"].lower().startswith("unicafe")]
        by_a = {}
        for v in stu:
            by_a.setdefault(v.get("district") or "Muu", []).append(v)
        secs = "".join(
            f'<h3>{esc(a)}</h3><ul class="picks">' + "".join(
                f'<li><a href="/ravintola/{v["slug"]}/">{esc(v["name"])}</a> <span class="mdish">{esc(ctx["clean_dish"](v["menu"]["items"][0]["d"][0]))}</span></li>' for v in sorted(vs, key=lambda x: x["name"])) + "</ul>"
            for a, vs in sorted(by_a.items(), key=lambda kv: (-len(kv[1]), kv[0])))
        body = f"""<p class="lead">Opiskelijalounas maksaa enintään <b>3,10 €</b>, kun ravintola kuuluu Kelan ateriatuen piiriin (tuki 2,80 € ateriaa kohden).
Tänään opiskelijahinta löytyy Helsingissä <b>{len(stu)} ravintolasta</b>, joista {len(uni)} on UniCafeja.</p>
{meta('Opiskelijahinnan tunnistus on arvio, ks. alla.')}
<table class="facts"><tr><td>Kelan ateriatuki</td><td>2,80 € / ateria</td></tr><tr><td>Opiskelijan hinta tuen jälkeen</td><td>enintään 3,10 €</td></tr>
<tr><td>Kalliimmista raaka-aineista tehdyt erikoisateriat</td><td>4,50–5,90 €</td></tr></table>
<p class="src">Lähde: {src_link('kela')}. Hinta edellyttää opiskelijastatusta; ravintola kertoo, miten sen voi osoittaa.</p>
<p><a class="btn" href="/?f=stu">Näytä opiskelijahintaiset kartalla</a></p>
{ctx['ad_block']('content', 'fi')}
<h2>Opiskelijahintaiset lounaat tänään alueittain</h2>
{secs}
<h2>Näin luku on laskettu</h2>
<p>Ravintola lasketaan opiskelijahintaiseksi, jos se on UniCafe tai sen oma hintatieto mainitsee opiskelijat tai Kelan, tai jos listalla on Kela-tasoinen (enintään 4 €) hinta tavallisen hinnan rinnalla.
Luku on <b>arvio</b>: osa ateriatukea antavista ravintoloista ei kerro opiskelijahintaa listallaan, joten todellinen määrä voi olla suurempi.</p>"""
        emit("stu", "Opiskelijalounas Helsinki 2026 – hinta 3,10 € ja paikat tänään | Päivän lounas",
             f"Opiskelijalounas maksaa enintään 3,10 € (Kelan ateriatuki 2,80 €). Tänään opiskelijahinta {len(stu)} Helsingin ravintolassa.",
             "Opiskelijalounas Helsingissä", body, len(stu) >= 5, [v["slug"] for v in stu], "Opiskelijalounas")

    # ---------- 4. Hernekeitto torstaina ----------
    def has_pea(m):
        return bool(m) and any(PEA.search(" ".join(i["d"]) + " " + (i.get("t") or "")) for i in m["items"])

    def has_pan(m):
        return bool(m) and any(PANCAKE.search(" ".join(i["d"])) for i in m["items"])

    per_day = []
    for d in ctx["days"]:
        n_any = sum(1 for v in venues if v["ms"].get(d))
        per_day.append((d, sum(1 for v in venues if has_pea(v["ms"].get(d))), n_any))
    thu = ctx["days"][3]
    pea_thu = [v for v in venues if has_pea(v["ms"].get(thu))]
    tot = sum(n for _, n, _ in per_day)
    thu_n = len(pea_thu)
    if thu_n:
        likes = ctx["likes"]
        liked = sum(1 for v in pea_thu if likes.get(v["slug"]))
        by_likes = liked >= 5
        order = sorted(pea_thu, key=lambda v: (-(likes.get(v["slug"]) or 0) if by_likes else 0, lp(v["ms"][thu]) or 99, v["name"]))
        lis = []
        for v in order[:40]:
            m = v["ms"][thu]
            pr = lp(m)
            dish = next((x for i in m["items"] for x in i["d"] if PEA.search(x)), None) or next(i["d"][0] for i in m["items"] if PEA.search(" ".join(i["d"]) + " " + (i.get("t") or "")))
            extra = " + pannukakku" if has_pan(m) else ""
            lk = f' <small>· {likes[v["slug"]]} tykkäystä</small>' if by_likes and likes.get(v["slug"]) else ""
            lis.append(f'<li><a href="/ravintola/{v["slug"]}/">{esc(v["name"])}</a> <span class="mdish">{esc(ctx["clean_dish"](dish))}{extra}</span>'
                       f'<span class="price">{fp(pr) if pr else ""}</span><small>{esc(v.get("district") or "")}</small>{lk}</li>')
        n_pan = sum(1 for v in pea_thu if has_pan(v["ms"][thu]))
        drow = "".join(f'<tr{" class=on" if d == thu else ""}><td>{ctx["datestr"](d, "fi")}</td><td>{n}</td><td>{pct(n, a)} %</td></tr>' for d, n, a in per_day if a)
        is_today = day == thu
        when = "tänään" if is_today else f"torstaina {int(thu[8:])}.{int(thu[5:7])}."
        body = f"""<p class="lead">Hernekeittoa syödään torstaisin, koska perjantai oli katolisena aikana paastopäivä: torstaina syötiin jotain täyttävää ja ravitsevaa ennen paastoa.
Tapa on edelleen voimissaan – Helsingissä hernekeittoa on {when} <b>{thu_n} ravintolan</b> listalla, kun koko tämän viikon aikana sitä on tarjottu {tot} kertaa{f' ({pct(thu_n, tot)} % torstaina)' if tot else ''}.</p>
{meta()}
<h2>Hernekeitto Helsingissä {when}</h2>
<p>{'Järjestys: lukijoiden tykkäykset, sitten hinta.' if by_likes else 'Järjestys: hinta edullisimmasta alkaen.'}{f' Pannukakku jälkiruokana {n_pan} paikassa.' if n_pan else ''}</p>
<ul class="picks">{''.join(lis)}</ul>
<p><a class="btn" href="/?q=hernekeitto">Hae hernekeitto kartalta</a></p>
{ctx['ad_block']('content', 'fi')}
<h2>Hernekeittoa tällä viikolla päivittäin</h2>
<table class="facts"><tr><th>Päivä</th><th>Listoja, joilla hernekeitto</th><th>Osuus päivän listoista</th></tr>{drow}</table>
<h2>Miksi juuri torstaina?</h2>
<p>Perinne ulottuu aikaan ennen uskonpuhdistusta, jolloin Suomi oli katolinen ja perjantai paastopäivä. Hernekeitto oli halpaa ja täyttävää ruokaa paastoa edeltäväksi päiväksi.
Ravintolakulttuuria tutkinut Merja Sillanpää ei Ylen haastattelussa osannut sanoa, miksi juuri torstai on säilynyt hernekeittopäivänä näin pitkään. Puolustusvoimissa torstai on yhä hernekeittopäivä, ja keittoa tehdään torstaisin yli 20 000 annosta.</p>
<p class="src">Lähteet: <a href="{SRC['yle_herne'][1]}" rel="noopener">{SRC['yle_herne'][0]}</a>; <a href="{SRC['yle_pv'][1]}" rel="noopener">{SRC['yle_pv'][0]}</a>.</p>
<h2>Näin luvut on laskettu</h2>
<p>Lasketaan Helsingin ravintolat, joiden lounaslistalla kyseisenä päivänä on hernekeitto (myös hernerokka ja ärtsoppa). Lista päivittyy joka arkiaamu ravintoloiden omista listoista.
Lukijoiden tykkäykset tulevat ravintolasivujen ”Söin täällä – hyvä lounas” -napista, ja niillä järjestetään lista, kun tykkäyksiä on vähintään viidellä paikalla.</p>"""
        emit("herne", "Hernekeitto torstaina Helsingissä – missä tänään ja miksi torstaisin | Päivän lounas",
             f"Miksi hernekeittoa syödään torstaisin, ja missä sitä saa Helsingissä {when}: {thu_n} ravintolaa hintoineen. Päivittyy joka arkiaamu.",
             "Hernekeitto torstaina Helsingissä", body, thu_n >= 5, [[(v["slug"], lp(v["ms"][thu])) for v in pea_thu], per_day], "Hernekeitto torstaina")
    return written
