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
pip install -r requirements.txt      # garminconnect, garth, pyyaml
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
| `--ics [soubor]` | Vygenerovat `.ics` pro Google Kalendář z YAML plánu (výchozí: `vtp-plan.ics`) |
| `--ics-garmin [soubor]` | Vygenerovat `.ics` ze **skutečně naplánovaných** tréninků na Garmin kalendáři, od dneška dál (výchozí: `vtp-garmin.ics`) |
| `--time HH:MM` | Čas začátku tréninku v ICS (bez toho jsou události celodenní) |
| `--delete` | Smazat všechny `VTP-T*` workouty z Garmin Connect |
| `--email` / `--password` | Přihlašovací údaje Garmin Connect |
| `--no-save` | Neukládat Garmin token na disk (jednorázové spuštění) |
| `--od-tydne N` | Začít nahrávat až od týdne N (přeskočí týdny 1..N-1) |
| `--pauza-faktor FLOAT` | Násobitel všech pauz (výchozí `1.0`) |
| `--max-hr N` | Ruční max. SF pro výpočet HR cílů (override / fallback pro `--dry-run`) |
| `--fetch-cviky [soubor]` | Stáhnout katalog cviků z Garminu do JSON (výchozí: `cviky-garmin.json`) |
| `--validate-cviky soubor` | Ověřit `EXERCISE_MAP` proti staženému JSON |

Skript je **idempotentní** — spustíš-li ho znovu, stávající workouty se smažou a nahrají znovu.

### Pokročilé přepínače

#### `--od-tydne N` — nahrát jen zbytek plánu

Když už máš prvních pár týdnů na hodinkách a nechceš je přepisovat, nahraj jen zbytek:

```bash
python push_plan.py --plan muzi --start 2026-06-16 --od-tydne 5   # týdny 5–12
```

Datum se pořád počítá od `--start` (pondělí 1. týdne), takže dny sedí správně. Kombinovatelné s `--weeks`.

#### `--pauza-faktor FLOAT` — zkrátit nebo prodloužit pauzy

Vynásobí **všechny** pauzy v silových a kombinovaných trénincích — jak `pauza_s` u jednotlivých cviků, tak `pauza_mezi_koly_s`. Běhy a kontrolní testy zůstávají beze změny.

```bash
python push_plan.py --plan muzi --pauza-faktor 0.5   # poloviční pauzy
python push_plan.py --plan muzi --pauza-faktor 1.5   # delší pauzy
```

Výchozí je `1.0` (pauzy přesně dle YAML). Pauza se nikdy nezkrátí pod 1 sekundu — Garmin odmítá REST krok s nulovou délkou.

#### `--max-hr N` — HR cíle v tepech místo procent

Plány zadávají intenzitu jako `% SFmax` (např. `70-80 % SFmax`). Skript to překládá na konkrétní bpm a Garmin zónu. Priorita zdrojů:

1. **`--max-hr N`** — ruční hodnota, přebije všechno ostatní
2. **HR zóny z Garmin Connectu** — načtou se automaticky po přihlášení (`/biometric-service/heartRateZones`); použijí se skutečné hranice zón
3. **Nic** — HR cíle se vynechají a skript jednou vypíše varování

Protože `--dry-run` a `--ics` se do Garminu nepřihlašují, bez `--max-hr` tam HR cíle chybí:

```bash
python push_plan.py --plan muzi --dry-run --max-hr 190
python push_plan.py --plan muzi --start 2026-06-16 --ics --max-hr 190
```

#### `--fetch-cviky` / `--validate-cviky` — ověření mapování cviků

`EXERCISE_MAP` v `push_plan.py` mapuje ~40 českých názvů cviků na Garmin klíče. Garmin katalog se občas mění; těmito dvěma příkazy si ověříš, že mapování pořád platí:

```bash
python push_plan.py --fetch-cviky                       # stáhne katalog → cviky-garmin.json
python push_plan.py --validate-cviky cviky-garmin.json  # porovná s EXERCISE_MAP
```

`--fetch-cviky` vyžaduje přihlášení (stahuje z `/workout-service/workout/exercise/*`), `--validate-cviky` běží offline nad staženým souborem. Validace vypíše `OK` / `ERR` pro každý cvik a u chyb navrhne nejbližší kandidáta z dané kategorie. Referenční tabulka je v `docs/garmin-mapovani-cviku.md`.

## Export do Google Kalendáře

Pokud chceš mít tréninky i v Google Kalendáři (přehled v telefonu, sdílení, notifikace):

### 1. Vygeneruj ICS soubor

```bash
# Celodenní události (bez pevného času)
python push_plan.py --plan muzi --start 2026-06-16 --ics

# S pevným časem začátku a odhadovanou délkou (doporučeno — fungují notifikace)
python push_plan.py --plan muzi --start 2026-06-16 --ics --time 06:30
```

Vznikne soubor `vtp-plan.ics` — jeden záznam na každý tréninkový den s popisem cvičení. S `--time` má každá událost i odhadovanou délku tréninku (Google Calendar pak nabídne nastavit notifikaci).

### 2. Importuj do Google Kalendáře

1. Otevři [calendar.google.com](https://calendar.google.com)
2. Vlevo dole klikni na **+** vedle „Další kalendáře" → **Vytvořit nový kalendář** (např. „VTP Trénink") — tréninky tak budeš mít odděleně a půjdou snadno skrýt nebo smazat
3. Klikni na ozubené kolečko **⚙️** vpravo nahoře → **Nastavení**
4. V levém menu vyber **Importovat a exportovat → Importovat**
5. Klikni **Vybrat soubor**, vyber `vtp-plan.ics`
6. V rozbalovacím menu zvol „VTP Trénink" (nebo jiný cílový kalendář)
7. Klikni **Importovat**

> **Poznámka:** ICS soubor se negeneruje automaticky při nahrávání do Garmin — spusť `--ics` zvlášť, kdykoli chceš kalendář aktualizovat.

### Export skutečného Garmin kalendáře (`--ics-garmin`)

Pokud sis tréninky na Garminu ručně přeházel (posunuté týdny, přesunuté dny), `--ics` z YAML plánu už neodpovídá realitě. Použij `--ics-garmin` — přihlásí se do Garmin Connect, načte **skutečně naplánované** `VTP-T*` tréninky od dneška dál a vygeneruje z nich `vtp-garmin.ics`:

```bash
python push_plan.py --ics-garmin
python push_plan.py --ics-garmin --time 06:30   # s pevným časem a odhadovanou délkou
```

Autoritou pro data je Garmin kalendář — `--start` a `--weeks` se ignorují. Popisy cvičení se dohledávají z YAML plánu podle názvu workoutu; HR cíle se přepočtou z reálných zón v Connectu. Import do Google Kalendáře je stejný jako výše (krok 2).

## Struktura repozitáře

| Soubor | Obsah |
|---|---|
| `push_plan.py` | Hlavní skript |
| `plan/vtp-plan-muzi.yaml` | Kompletní 12týdenní plán (muži) |
| `plan/vtp-plan-zeny.yaml` | Kompletní 12týdenní plán (ženy) |
| `docs/garmin-mapovani-cviku.md` | Mapování českých cviků na Garmin exercise keys |
| `docs/implementacni-plan.md` | Technické poznámky k implementaci |
| `cviky-garmin.json` | Katalog cviků stažený z Garminu (výstup `--fetch-cviky`) |

## Bezpečnost

Heslo zadávej přes `--password` pouze v terminálu — nikdy ho neukládej do souborů v tomto repozitáři. Pro opakované spuštění bez zadávání hesla si ulož Garmin token:

```bash
# První přihlášení uloží token do ~/.garmin_tokens
python push_plan.py --email tvuj@email.cz --password TveHeslo --dry-run

# Další spuštění token načte automaticky
python push_plan.py --plan muzi
```
