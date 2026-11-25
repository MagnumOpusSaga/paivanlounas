"""Daily share images: "Halvimmat lounaat tänään – Kallio" as a 1080x1350 PNG for WhatsApp / Instagram / link previews."""
import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(__file__)
FS = os.path.join(HERE, "..", "node_modules", "@fontsource")
FONTS = {
    "reg": f"{FS}/inter/files/inter-latin-400-normal.woff",
    "bold": f"{FS}/inter/files/inter-latin-700-normal.woff",
    "disp": f"{FS}/bricolage-grotesque/files/bricolage-grotesque-latin-800-normal.woff",
}
BG, INK, MUT, LINE, P, TINT = "#FFFBF7", "#22150F", "#6B5B52", "#EADFD6", "#C2410C", "#FDEBDD"
W, H = 1080, 1350
_ttf = {}


def _font(kind, size):
    """Pillow can't read woff directly: convert once to a temporary ttf with fontTools."""
    if kind not in _ttf:
        from fontTools.ttLib import TTFont
        f = TTFont(FONTS[kind])
        f.flavor = None
        path = os.path.join(tempfile.gettempdir(), f"pl-{kind}.ttf")
        f.save(path)
        _ttf[kind] = path
    return ImageFont.truetype(_ttf[kind], size)


def _fit(d, text, font, maxw):
    if d.textlength(text, font=font) <= maxw:
        return text
    while text and d.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text.rstrip(" ,·-") + "…"


def make(path, kicker, title, date_txt, rows, url_txt):
    """rows: [(name, dish, price_text)] – up to 5."""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    logo = os.path.join(HERE, "icon-192.png")
    if os.path.exists(logo):
        lg = Image.open(logo).convert("RGBA").resize((88, 88))
        im.paste(lg, (72, 72), lg)
    d.text((180, 86), "Päivän lounas", font=_font("disp", 46), fill=INK)
    d.text((182, 140), date_txt, font=_font("reg", 30), fill=MUT)
    d.text((72, 236), kicker, font=_font("bold", 38), fill=P)
    tf = _font("disp", 92)
    title = _fit(d, title, tf, W - 144)
    d.text((70, 284), title, font=tf, fill=INK)
    y = 430
    nf, df, pf = _font("bold", 40), _font("reg", 30), _font("disp", 52)
    for name, dish, price in rows[:5]:
        d.line((72, y, W - 72, y), fill=LINE, width=3)
        pw = d.textlength(price, font=pf)
        d.text((W - 72 - pw, y + 30), price, font=pf, fill=P)
        d.text((72, y + 26), _fit(d, name, nf, W - 200 - pw), font=nf, fill=INK)
        d.text((72, y + 82), _fit(d, dish, df, W - 200 - pw), font=df, fill=MUT)
        y += 140
    d.line((72, y, W - 72, y), fill=LINE, width=3)
    d.rounded_rectangle((72, H - 170, W - 72, H - 72), radius=26, fill=TINT)
    uf = _font("bold", 36)
    uw = d.textlength(url_txt, font=uf)
    d.text(((W - uw) / 2, H - 143), url_txt, font=uf, fill=P)
    im.save(path, optimize=True)
