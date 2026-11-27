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
    if pc.startswith("02") and pc not in ("02700", "02701", "02705"):  # 027xx = Kauniainen
        return "espoo"
    return None
