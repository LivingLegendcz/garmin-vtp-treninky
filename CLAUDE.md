# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python CLI tool that converts YAML-defined VTP (Czech Annual Physical Fitness Test) 12-week training plans into structured Garmin Connect workouts and schedules them on a Garmin smartwatch. Optionally exports the plan as an `.ics` file for Google Calendar.

## Environment — run this from Windows, not WSL

**Anything that talks to Garmin must be run by the user from a Windows terminal.** The repo lives on a OneDrive path reachable from both Windows and WSL, but only the Windows Python is set up:

- **WSL is not provisioned and deliberately stays that way.** Its `python3` has `pyyaml` but not `garminconnect` / `garth`, and it is `EXTERNALLY-MANAGED`, so `pip install` needs a venv. Don't set one up unless asked.
- **The Garmin token lives in the Windows home directory.** `TOKEN_DIR = Path.home() / ".garmin_tokens"` (`push_plan.py:40`) resolves to `C:\Users\<user>\.garmin_tokens\garmin_tokens.json` — WSL's `$HOME` is a different place and has no token, so a WSL run would demand a fresh login.

Practical split:

| Works anywhere (incl. WSL / agents) | Windows only — ask the user to run it |
|---|---|
| YAML validation, reading code | `--fetch-cviky`, `--ics-garmin`, `--delete` |
| `--validate-cviky` (offline, needs the JSON) | any upload run (`push_plan()`) |
| — | `--dry-run` and `--ics` (no login, but still need the libs) |

So don't try to verify a change by running the script — hand the user the exact command and ask for the output.

## Commands

**Install dependencies:**
```bash
pip install -r requirements.txt      # garminconnect, garth, pyyaml
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

**Export the REAL Garmin calendar (after manual rescheduling on Garmin; from today onward, `--start`/`--weeks` ignored):**
```bash
python push_plan.py --ics-garmin
```

**Delete all VTP-T\* workouts from Garmin:**
```bash
python push_plan.py --delete --email user@example.com --password secret
```

**Upload only from week N onward (skip weeks already on the watch):**
```bash
python push_plan.py --plan muzi --start 2026-06-16 --od-tydne 5
```

**Scale every rest interval (strength/combo only; running untouched):**
```bash
python push_plan.py --plan muzi --pauza-faktor 0.5
```

**Resolve `% SFmax` targets to bpm without logging in (`--dry-run`/`--ics` don't authenticate):**
```bash
python push_plan.py --plan muzi --dry-run --max-hr 190
```

**Refresh and verify the Garmin exercise catalogue against `EXERCISE_MAP`:**
```bash
python push_plan.py --fetch-cviky                       # needs login → cviky-garmin.json
python push_plan.py --validate-cviky cviky-garmin.json  # offline diff, prints OK/ERR per exercise
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

Everything lives in a single script `push_plan.py` (~1430 lines). There are no modules, packages, or classes — the code is structured as top-level functions called sequentially by `push_plan()`.

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
| `_cvik_steps()` | Converts a single exercise definition into Garmin step dicts using `EXERCISE_MAP`; scales `pauza_s` by `pauza_faktor` |
| `delete_vtp_workouts()` | Fetches all workouts, deletes those matching `VTP-T*` |
| `generate_ics()` | Produces RFC 5545 `.ics` content from the YAML plan |
| `generate_ics_from_garmin()` | Produces `.ics` from the workouts actually scheduled on the Garmin calendar (`/calendar-service`), from today onward; descriptions looked up from YAML by workout name |

**HR target resolution** (`% SFmax` in YAML → bpm + Garmin zone):

| Function | Role |
|---|---|
| `_parse_target()` | Parses a YAML `cil` string into a target kind + numeric range (`% SFmax`, `% rychlosti`, `% úsilí`) |
| `_zone_for_pct()` | Maps a `% SFmax` value onto Garmin zone number 1–5 |
| `_resolve_hr_pct()` | Converts a percent range to `(bpm_low, bpm_high, zone)`; warns once if no HR source exists |
| `_get_hr_zones()` | Reads real zone floors + max HR from `/biometric-service/heartRateZones` |
| `_load_hr_state()` | Populates module globals `HR_ZONES` / `MAX_HR`; `--max-hr` overrides Connect values |
| `_apply_max_hr()` | Sets `MAX_HR` alone — used by `--ics`, which never authenticates |

**Exercise catalogue tooling:**

| Function | Role |
|---|---|
| `fetch_garmin_cviky()` | Downloads categories + exercise names from `/workout-service/workout/exercise/*` into JSON |
| `validate_exercise_map()` | Diffs `EXERCISE_MAP` against that JSON offline; suggests the closest key per failed lookup |

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
          - { cvik: klik, serie: 3, opakovani: 15, pauza_s: 60 }
          - { cvik: plank_vydrz, serie: 5, cas_s: 30, pauza_s: 60, popis: "..." }
        kroky:             # used by beh/kombinace
          - typ: rozklusani
            cas_min: 10
```

The exercise key is `cvik` (not `nazev`) and must exist in `EXERCISE_MAP`. Use `opakovani` for rep-based sets or `cas_s` / `cas_min` for timed ones; `popis` overrides the auto-generated Czech label.

### Workout naming convention

`VTP-T{week:02d}-{day_upper}-{type_abbrev}` — e.g. `VTP-T01-PO-SIL`, `VTP-T03-ST-BEH`, `VTP-T12-PA-TEST`.

Upload is idempotent: before creating a workout, the script checks for and deletes an existing workout with the same name.

### Exercise mapping

`EXERCISE_MAP` dict in `push_plan.py` maps 37 Czech exercise keys to `(garmin_category, garmin_key)` pairs; unknown keys fall back to `("OTHER", key.upper())`. Check `docs/garmin-mapovani-cviku.md` for the full reference table before adding new exercises, then verify against the live catalogue with `--fetch-cviky` + `--validate-cviky`.

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
- **HR targets need a source.** YAML expresses intensity as `% SFmax`. Priority: `--max-hr` > HR zones fetched from Connect after login > nothing (targets are dropped with a single `[WARN]`). `--dry-run` and `--ics` never authenticate, so pass `--max-hr` there or the output has no HR targets.
- `--pauza-faktor` only affects `silovy` and `kombinace` days (both `pauza_s` and `pauza_mezi_koly_s`); running and test workouts are untouched. Scaled rests are clamped to a 1 s minimum — Garmin rejects a REST step with a zero end condition.
- `--validate-cviky` runs offline but needs a JSON produced by `--fetch-cviky`; an empty `cviky-garmin.json` means the fetch never ran successfully.
