# Implementační plán — zapracování VTP plánu do Garminu

Cíl: z `plan/vtp-plan-muzi.yaml` dostat všech 12 týdnů do Garmin Connect kalendáře tak, aby hodinky každý tréninkový den nabídly konkrétní trénink (Trénink → Tréninky → Do Workout).

## Krok 1 — Prostředí

- Python 3.11+, `pip install garminconnect garth pyyaml`
- Knihovny: https://github.com/cyberjunky/python-garminconnect (typed workout třídy, `upload_running_workout`, `schedule_workout`, `unschedule_workout`, `delete_workout`)
- Přihlášení: garth OAuth tokeny, při prvním loginu projde i MFA. Tokeny se cachují do `~/.garmin_tokens` — nikdy do adresáře s repozitářem.
- Test: přihlásit se a vypsat `get_workouts()`.

## Krok 2 — Validace mapování cviků

- Stáhnout aktuální seznam exercise types z Garmin API (workout-service) a porovnat s `docs/garmin-mapovani-cviku.md`.
- Klíče v mapovacím souboru jsou kvalifikovaný odhad — před generováním silových tréninků ověřit, neexistující klíč = workout se nenahraje nebo se cvik zobrazí jako generický.

## Krok 3 — Push skript (`push_plan.py`)

Vstup: YAML plán + `start_datum` (pondělí 1. týdne).

Logika:
1. Načti YAML, zvaliduj schéma.
2. Pro každý den s typem `beh` / `fartlek` / `indiansky_beh` → sestav running workout (warmup / repeat / interval / cooldown kroky, cíle tempo nebo % SFmax).
3. Pro `silovy` / `kruhovy` / `kombinace` → strength workout s rep/time kroky a pauzami dle YAML (alternativně cardio workout, pokud strength přes API zlobí).
4. `kontrolni_test` → workout VTP-TEST (12 min běh; leh-sedy a kliky se měří ručně, minima jsou v YAML jako poznámka).
5. `volno` / `aktivni_odpocinek` → přeskočit.
6. Nahraj workout, pak `schedule_workout(workout_id, datum)`.

Idempotence: před nahráním smazat workouts se stejným názvem (konvence `VTP-T{TT}-{DEN}-{typ}`), aby šel plán bezpečně přegenerovat.

Konfigurace: `GARMIN_EMAIL` / `GARMIN_PASSWORD` z env nebo Credential Manageru. Žádné credentials v kódu ani v repu.

## Krok 4 — Alternativa: MCP server místo skriptu

https://github.com/brunosantos/garmin-workouts-mcp — MCP server nad garminconnect/garth, umí vytvářet workouts a hromadně je plánovat do kalendáře (`schedule_workouts`). Po připojení do Claude Desktop jde plán nahrávat konverzačně („nahraj týden 3 od 6. 7."). Skript a MCP se nevylučují — MCP je pohodlnější na úpravy za pochodu, skript na hromadný initial load.

## Krok 5 — Pilot

1. Nahrát pouze týden 1 (skript s parametrem `--week 1`).
2. Synchronizovat hodinky, ověřit: tréninky viditelné v kalendáři GC, v daný den se nabízejí na hodinkách, kroky a pauzy dávají smysl při reálném cvičení.
3. Doladit (hlavně silové kroky — odpočinek mezi sériemi vs. koly), pak nahrát zbytek.

## Známá omezení

- Neoficiální reverzované API — po změnách na straně Garminu může krátkodobě vypadnout, sledovat issues v repu python-garminconnect.
- Kroky typu „max. opakování" Garmin neumí jako cíl — řeší se časovým krokem (např. 30 s max úsilí) nebo krokem ukončeným lap tlačítkem.
- „Indiánský běh" a fartlek = běžecký workout s repeat bloky chůze/klus/běh.
- Aktivní odpočinek (turistika, kolo, plavání) se nedá rozumně strukturovat — nechat volné.
