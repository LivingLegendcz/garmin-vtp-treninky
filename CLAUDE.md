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
| `--zkontroluj-plan`, `--dry-run`, `--ics` — need only `pyyaml` | `--fetch-vykon` |

`garminconnect` is imported lazily inside `_connect()` (`_import_garmin()`), so every
offline mode runs with `pyyaml` alone — that is what lets the lint run in GitHub Actions,
and it also means `--dry-run` / `--ics` / `--zkontroluj-plan` now work from WSL and from
an agent. Only paths that actually log in need the library.

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

**Check the YAML → Garmin conversion (offline, no login, runs in CI):**
```bash
python push_plan.py --plan muzi --zkontroluj-plan        # alias: --lint
```
Builds every day with the real builders and reports what would silently degrade on the
watch — **type-agnostic**, the same checks run for `beh`/`silovy`/`kombinace`/
`kontrolni_test`: a day that produces **zero steps**, a step (exercise *or* running)
ending on `lap.button` with no countdown and no rep count, a rest whose value looks
like a distance rather than seconds, a `cvik` missing from `EXERCISE_MAP`, and —
generically, for *any* day type — a YAML key that no builder ever reads while
constructing that day's workout (`_TrackedDict`/`_track_unused`: the effective day data
is wrapped in a dict subclass that records every key actually accessed via
`__getitem__`/`get`/`__contains__`, then anything left untouched is a silently dropped
value). `podtyp`, `rezim` and `lint_ok` are allowlisted — the first two are always just
a human-readable duplicate of already-structured data (`interval`/`kola`/`sestupne`),
and `lint_ok` itself is read only by the lint, never by a builder. Exit code 1 on any
finding. Range values (`"3-5"`) are reported as `INFO` and don't fail. A step that is
*deliberately* open-ended ("max opakování", a two-movement superset, a jog-back with no
fixed distance) is annotated in the YAML with `lint_ok: "reason"` — on a `cvik`/`bloky`/
`po_treninku` item or on a `kroky` item (including nested inside `opakovat`) — and the
lint skips it entirely; that annotation is the only way to keep the lint at zero
findings, so don't add it to hide a real problem.

**Run the plan with (or without) personal changes:**
```bash
python push_plan.py --plan muzi --start 2026-07-06        # overlay auto-loads if present
python push_plan.py --plan muzi --start 2026-07-06 --bez-vlastnich   # pure army plan
python push_plan.py --plan muzi --vlastni jiny-overlay.yaml
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

Everything lives in a single script `push_plan.py` (~2430 lines). There are no modules, packages, or classes — the code is structured as top-level functions called sequentially by `push_plan()`.

### Function map

| Function | Role |
|---|---|
| `push_plan()` | Entry point: loads YAML, builds workouts, uploads, schedules |
| `_import_garmin()` | Imports `garminconnect` on first login only, so offline modes need just `pyyaml` |
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

**Overlay — personal changes kept out of the army transcript:**

| Function | Role |
|---|---|
| `load_overlay()` | Reads `plan/vlastni-treninky.yaml` (auto if it exists, `--vlastni` to override, `--bez-vlastnich` to ignore). Missing conventional file = silently no overlay; missing explicit path = error |
| `apply_overlay()` | Merges the overlay into the plan and returns `(effective_plan, orphan_names)`. A moved or cancelled day becomes `{"typ": "volno"}` — an already-supported value, so **no builder, ICS branch or dispatcher needs a new day type**. Supports `prohodit` (swap two days), `presun` (move, target must be free), `zrusit`, `pridat` (own extra workout) |
| `vlastni_ics_events()` | Turns recurring own sessions (handball every Thursday) into calendar events from a **date range**, not from week numbers — so it also works in `--ics-garmin`, where the Garmin calendar is the authority and week 1 is never computed |

Why the overlay exists: `plan/vtp-plan-*.yaml` must stay a faithful transcript of the
army source, so it can be audited against the original and restarted from week 1 after
an injury. Anything personal — the standing Thursday handball practice, the day moves
around it — lives in the overlay and is merged at runtime, right after `yaml.safe_load`
in `push_plan()`, `generate_ics()`, `generate_ics_from_garmin()`, `fetch_garmin_vykon()`
and `lint_plan()`.

**Orphan cleanup matters here:** workout names come from the weekday
(`_vtp_name()` → `VTP-T10-ST-SIL`), so moving Wednesday's session to Monday renames it.
`push_plan()` therefore deletes the orphan names `apply_overlay()` reports, regardless of
`--od-tydne` — otherwise the old workout keeps sitting on the Garmin calendar forever and
shows up as a phantom event in `--ics-garmin`.

**Plan lint:**

| Function | Role |
|---|---|
| `lint_plan()` | Walks the effective plan, builds each day, reports degradations; returns the finding count (`main()` turns that into the exit code) |
| `_lint_flat()` | Flattens repeat groups so steps can be inspected pairwise |
| `_lint_polozky()` / `_lint_rozsahy()` | Collects a day's exercise/block/step items (including nested inside `opakovat`) / finds `"3-5"` range values that silently resolve to their maximum |
| `_TrackedDict` / `_track_wrap()` / `_track_unused()` | Generic, type-agnostic "was this YAML key ever read?" detector — wraps the effective day data, runs it through the real builder, then reports every key no builder touched (except the `podtyp`/`rezim`/`lint_ok` allowlist) |

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
        cviky:             # used by silovy (and by kombinace via `bloky`)
          - { cvik: klik, serie: 3, opakovani: 15, pauza_s: 60 }
          - { cvik: plank_vydrz, serie: 5, cas_s: 30, pauza_s: 60, popis: "..." }
        kroky:             # used by beh/kombinace — the key is `krok`, not `typ`
          - krok: rozklusani
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

`kombinace` days keep their content in **`bloky`**, not `cviky` — a `bloky` entry is
either an exercise (`cvik: …`, handled by `_cvik_steps`), a run (`krok: beh` with
`vzdalenost_m` / `vzdalenost_km` / `cas_s` / `cas_min`), or `krok: pauza`.
`build_strength_workout()` falls back to `bloky` when `cviky` is absent, so a
`silovy` day written with `bloky` still produces steps.

**Keys that exist so that structure never has to live in free text.** The source plan
writes prescriptions as Czech prose ("20 s zátěž / 10 s pauza", "1:1", "70 s - pauza
3 min - 50 s …"), and the builders cannot read prose — an unparsed prescription silently
became an open `lap.button` step, or a workout with no steps at all. Free-text `rezim` /
`popis` / `poznamka` stay for the human; the machine-readable twin is one of:

| Key | Where | Meaning |
|---|---|---|
| `interval: { zatez_s, pauza_s }` | day **or** exercise (exercise wins) | Tabata / circuit mode. Applied only to an exercise with no `cas_s`/`cas_min`/`opakovani`; emits work + rest per series. `serie: 10` + `interval` = "10× (20 s / 10 s)" |
| `sestupne: [{cas_s\|opakovani, pauza_s, popis}, …]` | exercise | Explicit per-set list — descending pyramids and any set sequence with differing durations/rests. Each item may carry its own `popis`; the last one gets no trailing rest |
| `pauza_pomer: 1` | `krok: pyramida` | Rest between segments is a **distance** equal to `segment × ratio` (1 = 1:1, jogged back). `pauza_cas_s` is the explicit time-based alternative |
| `lint_ok: "reason"` | exercise / `bloky` item | "This step is meant to end on the lap button" — silences that one lint finding |

**Rests from `interval` and `sestupne` are part of the prescription, so `--pauza-faktor`
deliberately does NOT scale them.** A Tabata's 10 s is the exercise, not a rest you may
shorten; `pauza_s` between plain series and `pauza_mezi_koly_s` are still scaled.

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
- `--pauza-faktor` only affects `silovy` and `kombinace` days (both `pauza_s` and `pauza_mezi_koly_s`); running and test workouts are untouched, and rests coming from `interval` / `sestupne` are exempt because they are the prescription itself. Scaled rests are clamped to a 1 s minimum — Garmin rejects a REST step with a zero end condition.
- **A pyramid rest is a distance, not a time.** `_run_steps()` emits `recovery` + `distance` for the 1:1 rest between segments. It used to pass the segment's metres into a `time` end condition, so a 1600 m rep was followed by a 1600 **second** (26:40) rest on the watch. `lint_plan()` keeps a regression check for exactly that shape: a time-based rest whose value equals the preceding distance step's value.
- `--validate-cviky` runs offline but needs a JSON produced by `--fetch-cviky`; an empty `cviky-garmin.json` means the fetch never ran successfully.
- **No trailing rest.** The last set of an exercise, the last round of a `kola > 1` workout, the last segment of a `pyramida` and the last repetition of an `opakovat` block all end without a following rest step — a workout must not finish on a pause. Rounds/repeats are built as `(N-1 in the repeat group) + (1 unrolled without the rest)`. In circuit mode a rest follows *every* exercise, so `build_strength_workout()` / `build_combo_workout()` pop any trailing rest/recovery off the round before wrapping it.
- **`typ` values the uploader skips silently:** `volno` and `aktivni_odpocinek`. Anything else unknown prints `[WARN] Neznámý typ`. There is deliberately **no** day type for handball — a calendar-only session is injected straight into the ICS by `vlastni_ics_events()` instead, so no builder had to learn a type that produces no workout.
- **`do X:YY` is a segment total, not a pace per km** (only `X:YY/km` is a per-km pace). For a 500 m rep, `max do 1:50` means covering it in 1:50, i.e. 3:40/km — historically this was read as 3:40/km regardless of distance, which produced absurd targets on any segment that wasn't 1000 m.
- `--fetch-vykon` writes personal health data (weight, HR, HRV) to `vykon-garmin.json`, which is gitignored — keep it that way, and don't paste its contents into shared output.
