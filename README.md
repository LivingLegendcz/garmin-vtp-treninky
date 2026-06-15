# Garmin VTP tréninky

Automatické nahrávání 12týdenního VTP tréninkového plánu AČR do Garmin Connect. Hodinky (Fénix, Epix, …) každý den samy nabídnou naplánovaný trénink.

Dostupné plány:
- **Muži** — [zdroj](https://doarmady.mo.gov.cz/priprava/vyrocni-telesne-prezkouseni/treninkovy-plan-pro-vyrocni-telesne-prezkouseni/muzi)
- **Ženy** — [zdroj](https://doarmady.mo.gov.cz/priprava/vyrocni-telesne-prezkouseni/treninkovy-plan-pro-vyrocni-telesne-prezkouseni/zeny)

## Jak to funguje

```
plan/vtp-plan-muzi.yaml  →  push_plan.py  →  Garmin Connect (workouts + kalendář)  →  hodinky
```

- Běhy → structured running workouts (rozklusání, intervaly, tempo/SF cíle, výklus)
- Silové tréninky → strength workouts s českými názvy cviků a počty sérií
- Kombinované tréninky → cardio workouts
- Kontrolní testy → running workout s popisem minimálních norem
- Volno a aktivní odpočinek se neplánují

## Instalace

```bash
pip install garminconnect pyyaml
```

## Použití

### 1. Nastav datum začátku

Otevři `plan/vtp-plan-muzi.yaml` (nebo `zeny`) a doplň:

```yaml
start_datum: "2026-06-16"   # pondělí 1. týdne
```

### 2. Ověř bez nahrávání

```bash
python push_plan.py --plan muzi --dry-run
python push_plan.py --plan zeny --dry-run
```

### 3. Nahraj pilot (týden 1)

```bash
python push_plan.py --plan muzi --email tvuj@email.cz --password TveHeslo --weeks 1
```

Po ověření na hodinkách / Garmin Connect webu nahraj celý plán:

```bash
python push_plan.py --plan muzi --email tvuj@email.cz --password TveHeslo
```

### Přehled parametrů

| Parametr | Popis |
|---|---|
| `--plan muzi` / `--plan zeny` | Který plán nahrát (výchozí: `muzi`) |
| `--weeks N` | Nahrát jen prvních N týdnů |
| `--dry-run` | Jen výpis JSON, nic nenahrávat |
| `--email` / `--password` | Přihlašovací údaje Garmin Connect |

Skript je **idempotentní** — spustíš-li ho znovu, stávající workouty se smažou a nahrají znovu.

## Struktura repozitáře

| Soubor | Obsah |
|---|---|
| `push_plan.py` | Hlavní skript |
| `plan/vtp-plan-muzi.yaml` | Kompletní 12týdenní plán (muži) |
| `plan/vtp-plan-zeny.yaml` | Kompletní 12týdenní plán (ženy) |
| `docs/garmin-mapovani-cviku.md` | Mapování českých cviků na Garmin exercise keys |
| `docs/implementacni-plan.md` | Technické poznámky k implementaci |

## Bezpečnost

Heslo zadávej přes `--password` pouze v terminálu — nikdy ho neukládej do souborů v tomto repozitáři. Pro opakované spuštění bez zadávání hesla si ulož Garmin token:

```bash
# První přihlášení uloží token do ~/.garmin_tokens
python push_plan.py --email tvuj@email.cz --password TveHeslo --dry-run

# Další spuštění token načte automaticky
python push_plan.py --plan muzi
```
