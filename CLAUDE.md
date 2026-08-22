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
To re-sync a shared Google Calendar after this (delete stale events, re-import), see
[`docs/google-kalendar-sync.md`](docs/google-kalendar-sync.md).

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

**Download real performance + fitness data for offline analysis (needs login):**
```bash
python push_plan.py --fetch-vykon --plan muzi --start 2026-06-01 --pauza-faktor 0.5
```
Writes `vykon-garmin.json` (gitignored — personal health data). Without `--start` it
takes 140 days back. Pass the same `--pauza-faktor` used when uploading, so the planned
rest steps it records match what was actually on the watch. Re-running is cheap: details
of activities already in the file are recycled, so only new activities are fetched — this
also lets a run interrupted by a rate limit be finished by simply running it again.

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
| `_connect()` | OAuth login; reads cached token from `~/.garmin_tokens`. MFA goes through the library's `prompt_mfa` callback — **not** the `login()` return value, which never signals MFA. Exits with a readable message instead of a traceback when the token is stale |
| `day_to_workout()` | Dispatcher: routes a YAML day to the correct builder by `typ` field |
| `build_running_workout()` | Builds running workouts with structured steps |
| `build_strength_workout()` | Builds strength workouts with rep/timed sets |
| `build_combo_workout()` | Builds cardio workouts mixing exercises and running segments |
| `build_test_workout()` | Builds the control test (12-min run + sit-ups + push-ups); optional `cil_beh_m` puts a pace target on the 12-min step |
| `_run_steps()` | Recursively converts YAML `kroky` into Garmin step dicts (handles `opakovat` repeat groups) |
| `_cvik_steps()` | Converts a single exercise definition into Garmin step dicts using `EXERCISE_MAP`; scales `pauza_s` by `pauza_faktor` |
| `delete_vtp_workouts()` | Fetches all workouts, deletes those matching `VTP-T*` |
| `generate_ics()` | Produces RFC 5545 `.ics` content from the YAML plan |
| `generate_ics_from_garmin()` | Produces `.ics` from the workouts actually scheduled on the Garmin calendar (`/calendar-service`), from today onward; descriptions looked up from YAML by workout name |

**HR target resolution** (`% SFmax` in YAML → bpm + Garmin zone):

| Function | Role |
|---|---|
| `_parse_target()` | Parses a YAML `cil` string into a target kind + numeric range. Takes an optional `vzdalenost_m`: `"X:YY/km"` is a pace per km, but `"do X:YY"` / `"NN s/kolo"` (no `/km`) is the **total time for that segment**, so the pace is `vzdalenost_m / total_s`. `% rychlosti` / `% úsilí` yield no target |
| `_zone_for_pct()` | Maps a `% SFmax` value onto Garmin zone number 1–5 |
| `_resolve_hr_pct()` | Converts a percent range to `(bpm_low, bpm_high, zone)`; warns once if no HR source exists |
| `_resolve_hr_abs()` | Same for an absolute bpm target (`"průměrná SF 120 tep/min"`) — finds the zone the bpm falls into |
| `_get_hr_zones()` | Reads real zone floors + max HR from `/biometric-service/heartRateZones` |
| `_load_hr_state()` | Populates module globals `HR_ZONES` / `MAX_HR`; `--max-hr` overrides Connect values |
| `_apply_max_hr()` | Sets `MAX_HR` alone — used by `--ics`, which never authenticates |

**Exercise catalogue tooling:**

| Function | Role |
|---|---|
| `fetch_garmin_cviky()` | Downloads categories + exercise names from `/workout-service/workout/exercise/*` into JSON |
| `validate_exercise_map()` | Diffs `EXERCISE_MAP` against that JSON offline; suggests the closest key per failed lookup |

**Performance data tooling** (`--fetch-vykon`):

| Function | Role |
|---|---|
| `fetch_garmin_vykon()` | Orchestrator: activities + laps/sets + weight + fitness metrics → one JSON. Attaches each activity's matched plan day and its planned steps (via `day_to_workout`), so planned vs actual is directly comparable — both paces are in **m/s** |
| `_vtp_name_in()` | Extracts the `VTP-T08-CT-BEH` code from anywhere in an activity name. **Required**: Garmin prefixes run activities with the location (`Praha - VTP-T08-CT-BEH`), so exact-name matching silently misses every run |
| `_api_try()` | Wraps one Garmin call so a single failure prints `[WARN]` and continues instead of killing the collection |
| `_trim_laps()` / `_trim_sets()` / `_trim_plan_steps()` | Field allowlists that keep the JSON small enough for an LLM to read in one pass |
| `_pick()` / `_num()` | Tolerate Garmin's inconsistent field names; round numbers down to keep size sane |

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
      ne:
        typ: kontrolni_test
        minima: { beh_12min_m: 2800, lehsedy_1min: 43, kliky_30s: 26 }
        cil_beh_m: 2450    # optional: distance to pace the 12-min run for
```

`minima` is the requirement to report; `cil_beh_m` is what the **watch** paces at, and the
two are deliberately separate. `minima` in these plans is their source's own progression
(2200→3000), not the official AZVP table — the real test is a points total capped by age
(see `https://azvp.cz/vyberove-rizeni/`, point 5), where the 12-min run scores
2800 m = 0 pts, 2600 = 1, 2400 = 2, 2200 = 3, and 1800 m is the floor that cannot be
missed. Fewer points is better. Because scoring is bracketed, set `cil_beh_m` slightly
**above** a bracket boundary (2450, not 2400) — landing at 2395 m costs a whole point.

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
- **No trailing rest.** The last set of an exercise, the last round of a `kola > 1` workout, the last segment of a `pyramida` and the last repetition of an `opakovat` block all end without a following rest step — a workout must not finish on a pause. Rounds/repeats are built as `(N-1 in the repeat group) + (1 unrolled without the rest)`.
- **`do X:YY` is a segment total, not a pace per km** (only `X:YY/km` is a per-km pace). For a 500 m rep, `max do 1:50` means covering it in 1:50, i.e. 3:40/km — historically this was read as 3:40/km regardless of distance, which produced absurd targets on any segment that wasn't 1000 m.
- `--fetch-vykon` writes personal health data (weight, HR, HRV) to `vykon-garmin.json`, which is gitignored — keep it that way, and don't paste its contents into shared output.
