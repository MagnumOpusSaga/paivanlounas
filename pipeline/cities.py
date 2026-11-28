"""Cities covered by Päivän lounas (Branu 27.11.2026: expand to all of Finland, slowly and carefully, a little every day).
Helsinki is the original registry (registry_helsinki.json, kaupunginosat.json). Every other city is built by
pipeline/build_city.py into data/registry_<key>.json + data/areas_<key>.json.

name_in: "Lounas Espoossa", name_gen: "Espoon lounaslistat"."""

CITIES = {
    "helsinki": {"name": "Helsinki", "name_in": "Helsingissä", "name_gen": "Helsingin", "kunta": "091"},
    "espoo": {
        "name": "Espoo", "name_in": "Espoossa", "name_gen": "Espoon", "kunta": "049",
        "postal": [f"02{n:03d}" for n in range(100, 1000, 10)],
        # Helsinki region open data (kartta.hel.fi): address points and statistical areas cover Espoo too
        "addr_wfs": "PKS_osoiteluettelo", "addr_city": "Espoo",
        "areas_wfs": "Seutukartta_aluejako_tilastoalue",
        # statistical area names → the names people search for ("lounas Tapiola", "lounas Keilaniemi")
        "area_names": {"Kanta-Tapiola": "Tapiola", "Kanta-Leppävaara": "Leppävaara", "Kanta-Espoo": "Espoon keskus",
                       "Kanta-Espoonlahti": "Espoonlahti", "Kanta-Kauklahti": "Kauklahti", "Otaniemi": "Otaniemi-Keilaniemi"},
        # lunch hubs (offices, campuses) – the website finder looks near these first
        "hubs": [(60.1765, 24.8290), (60.1860, 24.8270), (60.1755, 24.8050), (60.2190, 24.8130), (60.2050, 24.6560),
                 (60.1600, 24.7380), (60.1545, 24.6560)],
        "center": (60.1990, 24.7760),
    },
    # Vantaa and Kauniainen (Branu 28.11.: "laajennetaan joka päivä", capital region first) – on the map, noindex until "avaa <kaupunki>"
    "vantaa": {
        "name": "Vantaa", "name_in": "Vantaalla", "name_gen": "Vantaan", "kunta": "092",
        "postal": [f"01{n:03d}" for n in range(200, 800, 10)],
        "addr_wfs": "PKS_osoiteluettelo", "addr_city": "Vantaa",
        "areas_wfs": "Seutukartta_aluejako_tilastoalue",
        "area_names": {},
        # Aviapolis, airport, Tikkurila, Myyrmäki, Kivistö, Koivukylä
        "hubs": [(60.3040, 24.9560), (60.3170, 24.9630), (60.2920, 25.0440), (60.2610, 24.8540), (60.3150, 24.8450),
                 (60.3230, 25.0610)],
        "center": (60.2934, 24.9700),
    },
    "kauniainen": {
        "name": "Kauniainen", "name_in": "Kauniaisissa", "name_gen": "Kauniaisten", "kunta": "235",
        "postal": ["02700", "02701", "02705"],
        "addr_wfs": "PKS_osoiteluettelo", "addr_city": "Kauniainen",
        "areas_wfs": "Seutukartta_aluejako_tilastoalue",
        "area_names": {},
        "hubs": [(60.2110, 24.7290)],
        "center": (60.2110, 24.7290),
    },
}


def city_of(v):
    return v.get("city") or "helsinki"


def city_of_postal(pc):
    """City by postal code (Branu 27.11.: the official address decides; the map only when there is no postal code).
    None = no postal code or a municipality we do not cover yet."""
    pc = (pc or "").strip()
    if len(pc) != 5 or not pc.isdigit():
        return None
    if pc.startswith("00"):
        return "helsinki"
    if pc in ("02700", "02701", "02705"):
        return "kauniainen"
    if pc.startswith("02"):
        return "espoo"
    if pc.startswith("01") and "01200" <= pc < "01800":  # 012xx–017xx Vantaa (011xx Sipoo, 018xx+ Nurmijärvi…)
        return "vantaa"
    return None
