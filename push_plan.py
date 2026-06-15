#!/usr/bin/env python3
"""
VTP Tréninkový plán -> Garmin Connect

Nahraje tréninky z plan/vtp-plan-muzi.yaml do Garmin Connect kalendáře.

Použití:
    python push_plan.py --dry-run               # jen výpis JSON, nic nenahraje
    python push_plan.py --weeks 1               # pilot: jen týden 1
    python push_plan.py                         # celý plán (všechny týdny)

První přihlášení (uloží token do ~/.garmin_tokens):
    python push_plan.py --email vas@email.cz --password VaseHeslo --weeks 1

Další spuštění (token se načte automaticky):
    python push_plan.py --weeks 1
"""

import argparse
import datetime
import io
import json
import re
import sys
from pathlib import Path

# Zajistíme UTF-8 výstup na Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import yaml

try:
    from garminconnect import Garmin
except ImportError:
    print("Chybí knihovny. Spusť: pip install garminconnect pyyaml")
    sys.exit(1)

PLAN_DIR  = Path(__file__).parent / "plan"
TOKEN_DIR = Path.home() / ".garmin_tokens"

# ── Mapování cviků --> (Garmin category, Garmin exerciseName) ─────────────────
EXERCISE_MAP = {
    "klik":                              ("PUSH_UP",        "PUSH_UP"),
    "klik_na_kolenou":                   ("PUSH_UP",        "KNEELING_PUSH_UP"),
    "klik_negativni":                    ("PUSH_UP",        "PUSH_UP"),
    "klik_diamant":                      ("PUSH_UP",        "DIAMOND_PUSH_UP"),
    "klik_siroky":                       ("PUSH_UP",        "WIDE_GRIP_PUSH_UP"),
    "klik_tleskaci":                     ("PUSH_UP",        "CLAPPING_PUSH_UP"),
    "klik_hand_release":                 ("PUSH_UP",        "HAND_RELEASE_PUSH_UP"),
    "leh_sed":                           ("SIT_UP",         "SIT_UP"),
    "sklapovacky":                       ("SIT_UP",         "V_UP"),
    "sklapovacky_plus_klik":             ("SIT_UP",         "V_UP"),
    "jizda_na_kole_vsede":               ("CRUNCH",         "BICYCLE_CRUNCH"),
    "rotace_trupu_vsede":                ("CORE",           "RUSSIAN_TWIST"),
    "nuzky_vleze":                       ("CORE",           "FLUTTER_KICK"),
    "prednozeni_vleze":                  ("CRUNCH",         "TOE_TOUCH"),
    "plank_vydrz":                       ("PLANK",          "PLANK"),
    "plank":                             ("PLANK",          "PLANK"),
    "plank_na_boku":                     ("PLANK",          "SIDE_PLANK"),
    "plank_plus_lehsed":                 ("PLANK",          "PLANK"),
    "extenze_zad":                       ("HYPEREXTENSION", "BACK_EXTENSION"),
    "drep":                              ("SQUAT",          "BODY_WEIGHT_SQUAT"),
    "drep_do_vyponu":                    ("SQUAT",          "SQUAT_TO_CALF_RAISE"),
    "drep_s_vyskokem":                   ("PLYO",           "JUMP_SQUAT"),
    "vyskok_z_podrepu":                  ("PLYO",           "JUMP_SQUAT"),
    "podrep_vydrz":                      ("SQUAT",          "WALL_SIT"),
    "vypad":                             ("LUNGE",          "LUNGE"),
    "chuze_do_vypadu":                   ("LUNGE",          "WALKING_LUNGE"),
    "zabak":                             ("PLYO",           "BROAD_JUMP"),
    "vyskok_na_bednu":                   ("PLYO",           "BOX_JUMP"),
    "anglicak":                          ("TOTAL_BODY",     "BURPEE"),
    "panak":                             ("CARDIO",         "JUMPING_JACKS"),
    "veslovani_vsede":                   ("ROW",            "SEATED_ROW"),
    "shyb":                              ("PULL_UP",        "PULL_UP"),
    "shyb_negativni":                    ("PULL_UP",        "NEGATIVE_PULL_UP"),
    "shyb_negativni_plus_klik":          ("PULL_UP",        "NEGATIVE_PULL_UP"),
    "vis_pasivni":                       ("PULL_UP",        "DEAD_HANG"),
    "vis_pritahovani_kolen":             ("CORE",           "HANGING_KNEE_RAISE"),
    "vis_pritahovani_kolen_plus_lehsed": ("CORE",           "HANGING_KNEE_RAISE"),
}

DEN_CODE  = {"po": "PO", "ut": "UT", "st": "ST", "ct": "CT",
             "pa": "PA", "so": "SO", "ne": "NE"}
DEN_DELTA = {"po": 0, "ut": 1, "st": 2, "ct": 3, "pa": 4, "so": 5, "ne": 6}
TYP_CODE  = {"beh": "BEH", "silovy": "SIL", "kombinace": "KOM", "kontrolni_test": "TEST"}

# České názvy cviků pro popisky kroků na hodinkách
CVIK_CS = {
    "klik":                              "Kliky",
    "klik_na_kolenou":                   "Kliky na kolenou",
    "klik_negativni":                    "Negativni kliky (3s brzdit)",
    "klik_diamant":                      "Kliky diamant",
    "klik_siroky":                       "Kliky siroky",
    "klik_tleskaci":                     "Kliky s tlesknutim",
    "klik_hand_release":                 "Kliky hand release",
    "leh_sed":                           "Leh-sedy",
    "sklapovacky":                       "Sklapovacky",
    "sklapovacky_plus_klik":             "Sklapovacky + kliky",
    "jizda_na_kole_vsede":               "Jizda na kole v sedu",
    "rotace_trupu_vsede":                "Rotace trupu vsede",
    "nuzky_vleze":                       "Nuzky vleze",
    "prednozeni_vleze":                  "Prednozeni vleze",
    "plank_vydrz":                       "Plank vydrz",
    "plank":                             "Plank",
    "plank_na_boku":                     "Plank na boku",
    "plank_plus_lehsed":                 "Plank + leh-sed",
    "extenze_zad":                       "Extenze zad",
    "drep":                              "Drepy",
    "drep_do_vyponu":                    "Drep do vyponu",
    "drep_s_vyskokem":                   "Drep s vyskokem",
    "vyskok_z_podrepu":                  "Vyskok z podrepu",
    "podrep_vydrz":                      "Vydrz v podrepu",
    "vypad":                             "Vypady",
    "chuze_do_vypadu":                   "Chuze do vypadu",
    "zabak":                             "Zabaky",
    "vyskok_na_bednu":                   "Vyskok na bednu",
    "anglicak":                          "Anglicaky",
    "panak":                             "Panak",
    "veslovani_vsede":                   "Veslovani vsede",
    "shyb":                              "Shyby",
    "shyb_negativni":                    "Negativni shyby",
    "shyb_negativni_plus_klik":          "Neg. shyb + klik",
    "vis_pasivni":                       "Vis pasivni",
    "vis_pritahovani_kolen":             "Vis + pritahovani kolen",
    "vis_pritahovani_kolen_plus_lehsed": "Vis kolena + leh-sed",
}

PODTYP_CS = {
    "indiansky_beh": "Indiansky beh",
    "fartlek":       "Fartlek",
    "kruhovy":       "Kruhovy trenink",
    "kruhovy_tabata":"Tabata kruh",
    "pyramida":      "Pyramida",
    "hiit_beh_sila": "HIIT beh+sila",
    "sestupna_pyramida": "Sestupna pyramida",
}

# ── Garmin API konstanty ───────────────────────────────────────────────────────
_SPORT = {
    "running":           {"sportTypeId": 1, "sportTypeKey": "running",           "displayOrder": 1},
    "strength_training": {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5},
    "cardio":            {"sportTypeId": 6, "sportTypeKey": "cardio_training",   "displayOrder": 6},
}
_STEP = {
    "warmup":   {"stepTypeId": 1, "stepTypeKey": "warmup",   "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recover":  {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "rest":     {"stepTypeId": 5, "stepTypeKey": "rest",     "displayOrder": 5},
    "repeat":   {"stepTypeId": 6, "stepTypeKey": "repeat",   "displayOrder": 6},
}
_END = {
    "lap":  {"conditionTypeId": 1,  "conditionTypeKey": "lap.button", "displayOrder": 1,  "displayable": True},
    "time": {"conditionTypeId": 2,  "conditionTypeKey": "time",       "displayOrder": 2,  "displayable": True},
    "dist": {"conditionTypeId": 3,  "conditionTypeKey": "distance",   "displayOrder": 3,  "displayable": True},
    "reps": {"conditionTypeId": 10, "conditionTypeKey": "reps",       "displayOrder": 10, "displayable": True},
    "iter": {"conditionTypeId": 7,  "conditionTypeKey": "iterations", "displayOrder": 7,  "displayable": False},
}
_TGT = {
    "none": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target",       "displayOrder": 1},
    "hr":   {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4},
    "pace": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace",            "displayOrder": 6},
}


# ── Pomocné funkce ─────────────────────────────────────────────────────────────
def _int_range(val, default=1):
    """'3-5' -> 5 (max), 3 -> 3, None -> default"""
    if val is None:
        return default
    if isinstance(val, str) and "-" in val:
        a, b = val.split("-", 1)
        return int(float(b))
    return int(val)


def _parse_target(cil):
    """Parsuje cíl ('60-70 % SFmax', 'tempo 4:30/km') -> (tgt_key, val1, val2)."""
    if not cil:
        return "none", None, None
    s = str(cil)

    # Rozsah %: "60-70 % SFmax"
    m = re.search(r"(\d+)\s*[-]\s*(\d+)\s*%", s)
    if m:
        return "hr", int(m.group(1)), int(m.group(2))

    # Jedno %: "75 % SFmax" / "85 % max"
    m = re.search(r"(\d+)\s*%", s)
    if m:
        pct = int(m.group(1))
        return "hr", max(50, pct - 5), pct + 5

    # Tempo "4:30/km" nebo "do 3:50"
    m = re.search(r"(\d+):(\d+)(?:/km)?", s)
    if m:
        pace_s_per_km = int(m.group(1)) * 60 + int(m.group(2))
        mps = 1000.0 / pace_s_per_km
        return "pace", round(mps * 0.95, 4), round(mps * 1.05, 4)

    return "none", None, None


def _cvik_label(c):
    """Sestaví popisek cviku: 'Kliky 3x10' / 'Plank 30s' / vlastní popis."""
    if c.get("popis"):
        return c["popis"]
    key  = c.get("cvik", "")
    name = CVIK_CS.get(key, key.replace("_", " ").capitalize())
    if "opakovani" in c:
        return f"{name} {c['opakovani']}x"
    if "cas_s" in c:
        return f"{name} {c['cas_s']}s"
    if "cas_min" in c:
        return f"{name} {c['cas_min']}min"
    return name


def _build_strength_desc(day_data):
    """Kratky prehled cviku pro popis workoutu."""
    parts = []
    for c in day_data.get("cviky", []):
        parts.append(_cvik_label(c))
    kola = day_data.get("kola")
    prefix = f"{kola}x kolo: " if kola and str(kola) != "1" else ""
    return prefix + " | ".join(parts)


def _build_run_desc(day_data):
    """Popis behoveho workoutu (podtyp + kroky)."""
    podtyp = PODTYP_CS.get(day_data.get("podtyp", ""), "")
    parts = []
    for k in day_data.get("kroky", []):
        kr = k.get("krok", "")
        if kr == "rozklusani":
            parts.append(f"Rozklusani {k.get('cas_min',10)}min")
        elif kr == "vyklus":
            parts.append(f"Vyklus {k.get('cas_min',10)}min")
        elif kr == "opakovat":
            pocet = k.get("pocet", 1)
            inner = []
            for sub in k.get("obsah", []):
                sk = sub.get("krok", "")
                if sk == "chuze":
                    inner.append(f"chuze {sub.get('cas_s','?')}s")
                elif sk == "beh":
                    t = sub.get("cas_s") or (str(sub.get("cas_min","?"))+"min")
                    inner.append(f"beh {t}s" if sub.get("cas_s") else f"beh {t}")
                elif sk == "usek":
                    inner.append(f"{sub.get('vzdalenost_m','?')}m")
                elif sk == "klus":
                    inner.append(f"klus {sub.get('cas_s', sub.get('cas_min','?'))}s")
            parts.append(f"{pocet}x ({' + '.join(inner)})")
        elif kr in ("beh", "usek"):
            if "vzdalenost_m" in k:
                parts.append(f"Beh {k['vzdalenost_m']}m{(' ' + k['cil']) if k.get('cil') else ''}")
            elif "cas_min" in k:
                parts.append(f"Beh {k['cas_min']}min{(' ' + k['cil']) if k.get('cil') else ''}")
        elif kr == "pyramida":
            useky = k.get("useky_m", [])
            parts.append(f"Pyramida: {'-'.join(str(u) for u in useky)}m")
    desc = (podtyp + ": " if podtyp else "") + ", ".join(parts)
    if day_data.get("popis"):
        desc = day_data["popis"] + (" | " + desc if desc else "")
    return desc or None


def _step(stype, end_key, end_val=None, tgt="none", v1=None, v2=None,
          desc=None, ex_cat=None, ex_name=None, order=1):
    s = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _STEP[stype],
        "endCondition": _END[end_key],
        "endConditionValue": float(end_val) if end_val is not None else None,
        "targetType": _TGT[tgt],
    }
    if v1 is not None:
        s["targetValueOne"] = v1
    if v2 is not None:
        s["targetValueTwo"] = v2
    if desc:
        s["description"] = desc
    if ex_cat:
        s["exerciseCategory"] = ex_cat
    if ex_name:
        s["exerciseName"] = ex_name
    return s


def _repeat_group(iterations, child_steps, order=1):
    """Repeat group — children se číslují od 1."""
    for i, cs in enumerate(child_steps, 1):
        cs["stepOrder"] = i
    return {
        "type": "RepeatGroupDTO",
        "stepId": None,
        "stepOrder": order,
        "stepType": _STEP["repeat"],
        "childStepId": 1,
        "numberOfIterations": iterations,
        "endCondition": _END["iter"],
        "endConditionValue": float(iterations),
        "targetType": _TGT["none"],
        "targetValueOne": None,
        "targetValueTwo": None,
        "smartRepeat": False,
        "workoutSteps": child_steps,
    }


def _renumber(steps):
    for i, s in enumerate(steps, 1):
        s["stepOrder"] = i
    return steps


def _envelope(name, sport_key, steps, description=None):
    sport = _SPORT[sport_key]
    return {
        "sportType": sport,
        "workoutName": name,
        "description": description,
        "estimatedDurationInSecs": 0,
        "author": {},
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": sport,
                "workoutSteps": steps,
            }
        ],
    }


# ── Running builder ────────────────────────────────────────────────────────────
def _run_steps(kroky):
    out = []

    for k in kroky:
        krok = k.get("krok", "")
        cil  = k.get("cil")
        desc = k.get("popis") or k.get("poznamka")
        tgt, v1, v2 = _parse_target(cil)

        if krok == "rozklusani":
            secs = _int_range(k.get("cas_min", 10)) * 60
            out.append(_step("warmup", "time", secs, desc=desc or "Rozklusani"))

        elif krok == "vyklus":
            secs = _int_range(k.get("cas_min", 10)) * 60
            out.append(_step("cooldown", "time", secs, desc=desc or "Vyklus"))

        elif krok in ("beh", "usek"):
            cil_str = f" ({cil})" if cil else ""
            if "vzdalenost_m" in k:
                label = desc or f"Beh {k['vzdalenost_m']}m{cil_str}"
                out.append(_step("interval", "dist", k["vzdalenost_m"], tgt, v1, v2, label))
            elif "vzdalenost_km" in k:
                raw = k["vzdalenost_km"]
                km = _int_range(raw) if isinstance(raw, str) and "-" in raw else float(raw)
                label = desc or f"Beh {raw}km{cil_str}"
                out.append(_step("interval", "dist", int(km * 1000), tgt, v1, v2, label))
            elif "cas_min" in k:
                secs = _int_range(k["cas_min"]) * 60
                label = desc or f"Beh {k['cas_min']}min{cil_str}"
                out.append(_step("interval", "time", secs, tgt, v1, v2, label))
            elif "cas_s" in k:
                label = desc or f"Beh {k['cas_s']}s{cil_str}"
                out.append(_step("interval", "time", k["cas_s"], tgt, v1, v2, label))
            else:
                out.append(_step("interval", "lap", desc=desc or f"Beh{cil_str}"))

        elif krok == "chuze":
            secs = k.get("cas_s") or _int_range(k.get("cas_min", 1)) * 60
            out.append(_step("interval", "time", secs, desc="Chuze"))

        elif krok == "klus":
            if "cas_s" in k:
                out.append(_step("recover", "time", k["cas_s"], desc=desc or "Klus"))
            elif "cas_min" in k:
                out.append(_step("recover", "time", _int_range(k["cas_min"]) * 60, desc=desc))
            else:
                out.append(_step("recover", "lap", desc=desc or "Klus zpet"))

        elif krok == "pauza":
            if "cas_s" in k:
                out.append(_step("rest", "time", k["cas_s"], desc=desc))
            elif "cas_min" in k:
                out.append(_step("rest", "time", _int_range(k["cas_min"]) * 60, desc=desc))
            else:
                out.append(_step("rest", "lap", desc=desc))

        elif krok == "opakovat":
            pocet      = k.get("pocet", 1)
            sub_steps  = _run_steps(k.get("obsah", []))
            out.append(_repeat_group(pocet, sub_steps))

        elif krok == "pyramida":
            for dist in k.get("useky_m", []):
                out.append(_step("interval", "dist", dist, desc=f"{dist}m"))
                out.append(_step("rest", "time", dist, desc=f"Pauza {dist}s"))

    return _renumber(out)


def build_running_workout(day_data, name):
    kroky = day_data.get("kroky", [])
    if kroky:
        steps = _run_steps(kroky)
    else:
        secs  = _int_range(day_data.get("cas_min", 30)) * 60
        steps = [_step("interval", "time", secs, desc=day_data.get("popis", "Beh"))]
    desc = _build_run_desc(day_data)
    return _envelope(name, "running", steps, description=desc)


def build_test_workout(day_data, name):
    minima  = day_data.get("minima", {})
    beh_m   = minima.get("beh_12min_m", 2500)
    lehsedy = minima.get("lehsedy_1min", "?")
    kliky   = minima.get("kliky_30s", "?")
    note = (
        f"12min beh - cil min. {beh_m} m | "
        f"max leh-sedy/min (min. {lehsedy}) | max kliky/30s (min. {kliky})"
    )
    steps = [
        _step("warmup",   "time", 600, desc="Rozklusani"),
        _step("interval", "time", 720, desc=note),
        _step("cooldown", "time", 300, desc="Vyklus + protazeni"),
    ]
    return _envelope(name, "running", _renumber(steps),
                     description=day_data.get("popis", "Kontrolni test"))


# ── Strength builder ───────────────────────────────────────────────────────────
def _cvik_steps(c):
    key     = c.get("cvik", "")
    cat, ex = EXERCISE_MAP.get(key, ("OTHER", key.upper()))
    desc    = _cvik_label(c)   # Czech name + count/time
    pauza_s = _int_range(c.get("pauza_s", 60), default=60)
    serie   = _int_range(c.get("serie", 1))
    steps   = []

    for _ in range(serie):
        if "cas_s" in c:
            steps.append(_step("interval", "time", c["cas_s"],
                               ex_cat=cat, ex_name=ex, desc=desc))
        elif "cas_min" in c:
            secs = _int_range(c["cas_min"]) * 60
            steps.append(_step("interval", "time", secs,
                               ex_cat=cat, ex_name=ex, desc=desc))
        elif "opakovani" in c:
            reps = _int_range(c["opakovani"])
            steps.append(_step("interval", "reps", reps,
                               ex_cat=cat, ex_name=ex, desc=desc))
        else:
            rezim = c.get("rezim", desc)
            steps.append(_step("interval", "lap",
                               ex_cat=cat, ex_name=ex, desc=rezim))

        if pauza_s and pauza_s > 0:
            steps.append(_step("rest", "time", pauza_s, desc="Pauza"))

    return steps


def build_strength_workout(day_data, name):
    cviky       = day_data.get("cviky", [])
    kola        = _int_range(day_data.get("kola", 1))
    pauza_kola  = day_data.get("pauza_mezi_koly_s", 120)
    po_treninku = day_data.get("po_treninku", [])

    round_steps = []
    for c in cviky:
        round_steps.extend(_cvik_steps(c))

    if kola > 1 and round_steps:
        round_steps.append(_step("rest", "time", pauza_kola,
                                 desc=f"Pauza mezi koly ({pauza_kola}s)"))
        top_steps = [_repeat_group(kola, round_steps)]
    else:
        top_steps = round_steps

    for c in po_treninku:
        top_steps.extend(_cvik_steps(c))

    desc = _build_strength_desc(day_data)
    extra = day_data.get("kroky_pred") or day_data.get("poznamka")
    if extra:
        desc = extra + " | " + desc if desc else extra
    return _envelope(name, "strength_training", _renumber(top_steps), description=desc)


# ── Combo builder ──────────────────────────────────────────────────────────────
def build_combo_workout(day_data, name):
    bloky      = day_data.get("bloky", [])
    kola       = _int_range(day_data.get("kola", 1))
    pauza_kola = day_data.get("pauza_mezi_koly_s", 180)
    round_steps = []

    for b in bloky:
        if "cvik" in b:
            round_steps.extend(_cvik_steps(b))
        elif b.get("krok") == "beh":
            raw = b.get("vzdalenost_km")
            if raw:
                km = _int_range(raw) if isinstance(raw, str) and "-" in raw else float(raw)
                round_steps.append(_step("interval", "dist", int(km * 1000),
                                         desc=b.get("popis", "Beh")))
            else:
                round_steps.append(_step("interval", "lap", desc=b.get("popis", "Beh")))
        else:
            round_steps.append(_step("interval", "lap", desc=b.get("popis", "")))

    if kola > 1 and round_steps:
        round_steps.append(_step("rest", "time", pauza_kola, desc="Pauza mezi koly"))
        top_steps = [_repeat_group(kola, round_steps)]
    else:
        top_steps = round_steps

    prefix = day_data.get("kroky_pred", "")
    popis  = day_data.get("popis", "")
    desc   = (popis + (" | " + prefix if prefix else "")).strip(" |") or None
    return _envelope(name, "cardio", _renumber(top_steps), description=desc)


# ── Dispatch ───────────────────────────────────────────────────────────────────
def day_to_workout(day_data, name):
    typ = day_data.get("typ", "volno")
    if typ in ("volno", "aktivni_odpocinek"):
        return None
    if typ == "beh":
        return build_running_workout(day_data, name)
    if typ == "silovy":
        return build_strength_workout(day_data, name)
    if typ == "kombinace":
        return build_combo_workout(day_data, name)
    if typ == "kontrolni_test":
        return build_test_workout(day_data, name)
    print(f"  [WARN] Neznamý typ '{typ}' pro {name} - preskoceno")
    return None


# ── Garmin Connect I/O ─────────────────────────────────────────────────────────
def _connect(email=None, password=None, no_save=False):
    """Připojí se ke Garmin Connect. Token se uloží do TOKEN_DIR (pokud není --no-save)."""
    api = Garmin(email or None, password or None)

    if no_save:
        result = api.login()
    else:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        result = api.login(tokenstore=str(TOKEN_DIR))

    if result and result[0]:  # MFA needed
        mfa_code = input("Zadej MFA kód z Garmin / e-mailu: ").strip()
        api.resume_login(mfa_code)

    return api


def delete_vtp_workouts(email=None, password=None, no_save=False):
    """Smaže všechny workouty začínající VTP-T z Garmin Connect."""
    print("Prihlasování do Garmin Connect...")
    api = _connect(email, password, no_save)
    existing = api.get_workouts(0, 1000)
    vtp = [w for w in existing if w["workoutName"].startswith("VTP-T")]
    print(f"Nalezeno {len(vtp)} VTP workoutu ke smazání.")
    for w in vtp:
        api.delete_workout(w["workoutId"])
        print(f"  smazán: {w['workoutName']}")
    print(f"\nSmazáno celkem: {len(vtp)} workoutu.")


def push_plan(plan_name="muzi", weeks_limit=None, dry_run=False,
              email=None, password=None, no_save=False, start_override=None):
    plan_file = PLAN_DIR / f"vtp-plan-{plan_name}.yaml"
    if not plan_file.exists():
        print(f"CHYBA: soubor {plan_file} neexistuje.")
        sys.exit(1)
    with open(plan_file, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    # Datum začátku: --start má přednost před YAML
    if start_override:
        start_date = datetime.date.fromisoformat(start_override)
    else:
        start_str = plan["meta"].get("start_datum")
        if not start_str:
            if not dry_run:
                print("CHYBA: 'start_datum' neni nastaven v YAML. Pouzij --start YYYY-MM-DD.")
                sys.exit(1)
            start_date = datetime.date.today()  # placeholder pro dry-run
        else:
            start_date = datetime.date.fromisoformat(str(start_str))

    api = None
    existing_by_name = {}
    if not dry_run:
        print("Prihlasování do Garmin Connect...")
        api = _connect(email, password, no_save)
        print(f"Prihlasen. Nacitám existující workouty...")
        existing = api.get_workouts(0, 1000)
        existing_by_name = {w["workoutName"]: w["workoutId"] for w in existing}
        print(f"  nalezeno {len(existing_by_name)} existujících workoutu")

    total = 0
    for tyden_data in plan.get("tydny", []):
        tyden = tyden_data["tyden"]
        if weeks_limit and tyden > weeks_limit:
            break

        print(f"\n-- Tyden {tyden} --")
        for den_key, day_data in tyden_data.get("dny", {}).items():
            if not day_data:
                continue
            typ = day_data.get("typ", "volno")
            if typ in ("volno", "aktivni_odpocinek"):
                continue

            date    = start_date + datetime.timedelta(
                        days=(tyden - 1) * 7 + DEN_DELTA[den_key])
            name    = (f"VTP-T{tyden:02d}-{DEN_CODE[den_key]}"
                       f"-{TYP_CODE.get(typ, typ.upper())}")
            workout = day_to_workout(day_data, name)
            if workout is None:
                continue

            print(f"  {date}  {name}")

            if dry_run:
                print(json.dumps(workout, ensure_ascii=False, indent=2))
                continue

            # Idempotent: smazat stary
            if name in existing_by_name:
                api.delete_workout(existing_by_name[name])
                print("    -> smazán existujici")

            # Nahrát
            result = api.upload_workout(workout)
            wid    = result.get("workoutId")
            if not wid:
                print(f"    CHYBA: workoutId chybi v odpovedi: {result}")
                continue

            # Naplánovat na datum
            api.schedule_workout(wid, date.isoformat())
            print(f"    -> id={wid}, naplánován na {date}")
            total += 1

    print(f"\nCelkem nahráno: {total} treninkú.")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="VTP plan -> Garmin Connect",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Příklady:
  python push_plan.py --dry-run                          # náhled bez nahrání
  python push_plan.py --start 2026-09-01 --weeks 1       # pilot, ženy
  python push_plan.py --plan zeny --email x@y.cz --password ...
  python push_plan.py --delete --email x@y.cz --password ...  # smazat VTP workouty
""")
    p.add_argument("--plan",     default="muzi", choices=["muzi", "zeny"],
                   help="Ktery plan nahrat: muzi (default) nebo zeny")
    p.add_argument("--start",    default=None, metavar="YYYY-MM-DD",
                   help="Datum zacatku (pondeli tydne 1), prepisuje start_datum v YAML")
    p.add_argument("--weeks",    type=int, default=None,
                   help="Nahrat jen prvnich N tydnu")
    p.add_argument("--dry-run",  action="store_true",
                   help="Jen výpis JSON, nic nenahrávat")
    p.add_argument("--delete",   action="store_true",
                   help="Smazat vsechny VTP-T* workouty z Garmin Connect (bez nahrani)")
    p.add_argument("--no-save",  action="store_true",
                   help="Neukladat Garmin token na disk (pouzij pro jednourazove spusteni)")
    p.add_argument("--email",    default=None, help="Garmin Connect e-mail")
    p.add_argument("--password", default=None, help="Garmin Connect heslo")
    args = p.parse_args()

    if args.delete:
        delete_vtp_workouts(args.email, args.password, args.no_save)
    else:
        push_plan(
            plan_name=args.plan,
            weeks_limit=args.weeks,
            dry_run=args.dry_run,
            email=args.email,
            password=args.password,
            no_save=args.no_save,
            start_override=args.start,
        )


if __name__ == "__main__":
    main()
