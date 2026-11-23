# Päivän lounas – paivanlounas.fi

Helsingin lounaslistat kartalla. Listat haetaan joka arkiaamu automaattisesti ketjujen rajapinnoista (Compass, Sodexo, UniCafe), Raflaamon julkiselta lounassivulta ja ravintoloiden omilta sivuilta.

## Päivittäinen ajo
`.github/workflows/daily.yml` ajaa ma–pe klo 04:07 ja 08:37 UTC:
`pipeline/daily.py` → `build/build_site.py` → `wrangler pages deploy` (Cloudflare Pages -projekti `paivanlounas`).

Tarvitaan:
- Salaisuus `CLOUDFLARE_API_TOKEN` (Cloudflare Pages: Edit)
- Muuttuja `CLOUDFLARE_ACCOUNT_ID`
- Muuttuja `PUBLIC=1`, kun esikatselutila (noindex) poistetaan.

Käsin ajo: Actions → Daily update → Run workflow.

## Paikallisesti
```
npm install --no-save leaflet@1.9.4
python3 -I pipeline/daily.py 2026-11-24
npx wrangler@3 pages deploy dist --project-name paivanlounas --branch main
```

## Data
- `data/registry_helsinki.json` – 3 233 lounaspaikkaa (Oiva + OpenStreetMap + ketjut), rakennetaan `pipeline/build_registry.py`:llä.
- Oiva / Ruokavirasto, Helsingin kaupunki (osoitteet, kaupunginosat, CC BY 4.0), © OpenStreetMapin tekijät (ODbL).
- lounaat.infon tietoja ei käytetä.

## Website discovery
`pipeline/find_websites.py data/registry_helsinki.json data/websites_found.json` tries likely domains (name.fi, name.com, ravintola-name.fi …) for venues without a website and keeps a site only if its front page shows the venue's street or postal code and its name. Results were merged into the registry (field `website_found: "guess"`).
