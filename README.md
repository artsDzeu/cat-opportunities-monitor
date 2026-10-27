# Cat Opportunities Monitor

Repo public pentru scanare autonomă de opțiuni de venit (bug bounty + micro-taskuri).

## Ce face

- `scan_and_report.py` — rulează `opportunities.py --all` pe GitHub Actions la fiecare 6 ore
- Salvează `latest_scan.json` în repo (date brute pentru cron local)
- `opportunities_state.json` — starea scanner-ului (ce e deja văzut)
- Commit automat dacă au apărut schimbări

## Cum funcționează alerta pe Discord

Cron-ul local (`scripts/opportunities.py` rulează deja pe host) citește starea locală și livrează opțiunile noi pe Discord prin `hermes cron create --deliver discord:...`.

Acest repo e o copie de siguranță și o sursă publică — permite rularea scanării pe infrastructure gratuită de GitHub, indiferent de starea host-ului local.

## Reguli

- Fără chei API, fără conturi, zero cost
- Cod public — nu pune secrete în repo
- Fiecare rulare e autonomă, fără intervenție umană
