# Garmin VTP tréninky

Automatické nahrávání 12týdenního VTP tréninkového plánu AČR do Garmin Connect. Hodinky (Fénix, Epix, …) každý den samy nabídnou naplánovaný trénink.

Dostupné plány:
- **Muži** — [zdroj](https://doarmady.mo.gov.cz/priprava/vyrocni-telesne-prezkouseni/treninkovy-plan-pro-vyrocni-telesne-prezkouseni/muzi)
- **Ženy** — [zdroj](https://doarmady.mo.gov.cz/priprava/vyrocni-telesne-prezkouseni/treninkovy-plan-pro-vyrocni-telesne-prezkouseni/zeny)

## Jak to funguje

```
plan/vtp-plan-muzi.yaml  →  push_plan.py  →  Garmin Connect (workouts + kalendář)  →  hodinky
                                          ↘  .ics soubor  →  Google Kalendář
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
| `--start YYYY-MM-DD` | Datum začátku (pondělí 1. týdne), přepíše `start_datum` v YAML |
| `--weeks N` | Nahrát jen prvních N týdnů |
| `--dry-run` | Jen výpis JSON, nic nenahrávat |
| `--ics [soubor]` | Vygenerovat `.ics` pro Google Kalendář (výchozí: `vtp-plan.ics`) |
| `--delete` | Smazat všechny `VTP-T*` workouty z Garmin Connect |
| `--email` / `--password` | Přihlašovací údaje Garmin Connect |

Skript je **idempotentní** — spustíš-li ho znovu, stávající workouty se smažou a nahrají znovu.

## Export do Google Kalendáře

Pokud chceš mít tréninky i v Google Kalendáři (přehled v telefonu, sdílení, notifikace):

### 1. Vygeneruj ICS soubor

```bash
python push_plan.py --plan muzi --start 2026-06-16 --ics
```

Vznikne soubor `vtp-plan.ics` — jeden celodeňní záznam na každý tréninkový den s popisem cvičení.

### 2. Importuj do Google Kalendáře

1. Otevři [calendar.google.com](https://calendar.google.com)
2. Vlevo dole klikni na **+** vedle „Další kalendáře" → **Vytvořit nový kalendář** (např. „VTP Trénink") — tréninky tak budeš mít odděleně a půjdou snadno skrýt nebo smazat
3. Klikni na ozubené kolečko **⚙️** vpravo nahoře → **Nastavení**
4. V levém menu vyber **Importovat a exportovat → Importovat**
5. Klikni **Vybrat soubor**, vyber `vtp-plan.ics`
6. V rozbalovacím menu zvol „VTP Trénink" (nebo jiný cílový kalendář)
7. Klikni **Importovat**

> **Poznámka:** ICS soubor se negeneruje automaticky při nahrávání do Garmin — spusť `--ics` zvlášť, kdykoli chceš kalendář aktualizovat.

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
