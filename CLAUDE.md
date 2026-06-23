# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python CLI tool that converts YAML-defined VTP (Czech Annual Physical Fitness Test) 12-week training plans into structured Garmin Connect workouts and schedules them on a Garmin smartwatch. Optionally exports the plan as an `.ics` file for Google Calendar.

## Commands

**Install dependencies:**
```bash
pip install garminconnect pyyaml garth
```

**Preview (no upload, no credentials needed):**
```bash
python push_plan.py --dry-run
```

**Upload full plan (first run — credentials cached to `~/.garmin_tokens` after this):**
```bash
python push_plan.py --plan muzi --email user@example.com --password secret --start 2026-06-16
```

**Subsequent runs (token auto-loaded):**
```bash
python push_plan.py --plan muzi --start 2026-06-16
```

**Upload only first N weeks (pilot test):**
```bash
python push_plan.py --plan muzi --weeks 2 --email user@example.com --password secret
```

**Export to Google Calendar (all-day events):**
```bash
python push_plan.py --plan muzi --start 2026-06-16 --ics
```

**Export with timed events (6:30 AM start, durations estimated):**
```bash
python push_plan.py --plan muzi --start 2026-06-16 --ics --time 06:30
```

**Delete all VTP-T\* workouts from Garmin:**
```bash
python push_plan.py --delete --email user@example.com --password secret
```

**Validate YAML plans (mirrors GitHub Actions CI):**
```bash
python -c "
import yaml
for path in ['plan/vtp-plan-muzi.yaml', 'plan/vtp-plan-zeny.yaml']:
    with open(path, encoding='utf-8') as f:
        d = yaml.safe_load(f)
    assert d['meta']['pocet_tydnu'] == 12
    assert len(d['tydny']) == 12
    print(f'OK {path}')
"
```

## Architecture

Everything lives in a single script `push_plan.py` (~917 lines). There are no modules, packages, or classes — the code is structured as top-level functions called sequentially by `push_plan()`.

### Function map

| Function | Role |
|---|---|
| `push_plan()` | Entry point: loads YAML, builds workouts, uploads, schedules |
| `_connect()` | OAuth login via `garth`; reads cached token from `~/.garmin_tokens` |
| `day_to_workout()` | Dispatcher: routes a YAML day to the correct builder by `typ` field |
| `build_running_workout()` | Builds running workouts with structured steps |
| `build_strength_workout()` | Builds strength workouts with rep/timed sets |
| `build_combo_workout()` | Builds cardio workouts mixing exercises and running segments |
| `build_test_workout()` | Builds the control test (12-min run + sit-ups + push-ups) |
| `_run_steps()` | Recursively converts YAML `kroky` into Garmin step dicts (handles `opakovat` repeat groups) |
| `_cvik_steps()` | Converts a single exercise definition into Garmin step dicts using `EXERCISE_MAP` |
| `delete_vtp_workouts()` | Fetches all workouts, deletes those matching `VTP-T*` |
| `generate_ics()` | Produces RFC 5545 `.ics` content from the plan |

### YAML plan schema

Plans live in `plan/vtp-plan-muzi.yaml` and `plan/vtp-plan-zeny.yaml`.

```yaml
meta:
  pocet_tydnu: 12
  start_datum: null        # set via --start; must be a Monday

tydny:
  - tyden: 1
    dny:
      po:                  # Monday (po/ut/st/ct/pa/so/ne)
        typ: silovy        # silovy | beh | kombinace | kontrolni_test | volno | aktivni_odpocinek
        popis: "..."
        cviky:             # used by silovy/kombinace
          - nazev: klik
            serie: 3
            opakovani: 15
            pauza_s: 60
        kroky:             # used by beh/kombinace
          - typ: rozklusani
            cas_min: 10
```

### Workout naming convention

`VTP-T{week:02d}-{day_upper}-{type_abbrev}` — e.g. `VTP-T01-PO-SIL`, `VTP-T03-ST-BEH`, `VTP-T12-PA-TEST`.

Upload is idempotent: before creating a workout, the script checks for and deletes an existing workout with the same name.

### Exercise mapping

`EXERCISE_MAP` dict in `push_plan.py` maps ~40 Czech exercise names to `(garmin_category, garmin_key, is_timed)` tuples. Check `docs/garmin-mapovani-cviku.md` for the full reference table before adding new exercises.

### Running step types (`kroky[].typ`)

`rozklusani` (warmup) · `beh` (interval) · `klus` (recovery jog) · `pauza` (rest) · `vyklusani` (cooldown) · `opakovat` (repeat group, contains nested `kroky`) · `pyramida`

### OAuth / credentials

First login requires `--email` + `--password`; the token is saved to `~/.garmin_tokens` (excluded from git). Subsequent runs load the token automatically. Use `--no-save` to suppress caching.

## Key constraints

- **Unofficial API**: `garminconnect` reverse-engineers Garmin's private API — it can break on Garmin-side changes.
- `--start` must be a Monday; the script validates this and exits with an error otherwise.
- `volno` and `aktivni_odpocinek` day types are silently skipped (no workout created).
- All workout descriptions and step labels are in Czech.
- ICS duration estimation assumes ~150 m/min running pace when no explicit `cas_min` is set.
