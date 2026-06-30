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

# ── HR zóny / max. SF (naplní se po přihlášení nebo z --max-hr) ─────────────────
# HR_ZONES: dict {"max_hr": int, "floors": [z1..z5], "method": str} nebo None
HR_ZONES = None
MAX_HR   = None
_HR_WARNED = False   # aby se varování "neznámá max. SF" vypsalo jen jednou

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
    "nuzky_vleze":                       ("CORE",           "SCISSORS"),
    "prednozeni_vleze":                  ("CRUNCH",         "TOE_TOUCH"),          # Garmin nema, kategorie CRUNCH se ulozi
    "plank_vydrz":                       ("PLANK",          "PLANK"),
    "plank":                             ("PLANK",          "PLANK"),
    "plank_na_boku":                     ("PLANK",          "SIDE_PLANK"),
    "plank_plus_lehsed":                 ("PLANK",          "PLANK"),
    "extenze_zad":                       ("HYPEREXTENSION", "BACK_EXTENSION"),     # Garmin nema, kategorie HYPEREXTENSION se ulozi
    "drep":                              ("SQUAT",          "AIR_SQUAT"),
    "drep_do_vyponu":                    ("SQUAT",          "SQUAT_TO_CALF_RAISE"), # Garmin nema, kategorie SQUAT se ulozi
    "drep_s_vyskokem":                   ("PLYO",           "JUMP_SQUAT"),
    "vyskok_z_podrepu":                  ("PLYO",           "JUMP_SQUAT"),
    "podrep_vydrz":                      ("SQUAT",          "WALL_SIT"),           # Garmin nema, kategorie SQUAT se ulozi
    "vypad":                             ("LUNGE",          "LUNGE"),
    "chuze_do_vypadu":                   ("LUNGE",          "WALKING_LUNGE"),
    "zabak":                             ("PLYO",           "BROAD_JUMP"),         # Garmin nema, kategorie PLYO se ulozi
    "vyskok_na_bednu":                   ("PLYO",           "BOX_JUMP"),
    "anglicak":                          ("TOTAL_BODY",     "BURPEE"),
    "panak":                             ("CARDIO",         "JUMPING_JACKS"),
    "veslovani_vsede":                   ("ROW",            "SEATED_CABLE_ROW"),
    "shyb":                              ("PULL_UP",        "PULL_UP"),
    "shyb_negativni":                    ("PULL_UP",        "CHIN_UP"),            # Nejblizsi dostupny cvik v Garmin DB
    "shyb_negativni_plus_klik":          ("PULL_UP",        "CHIN_UP"),
    "vis_pasivni":                       ("PULL_UP",        "NEUTRAL_GRIP_PULL_UP"),
    "vis_pritahovani_kolen":             ("CORE",           "HANGING_KNEE_RAISE"), # Garmin nema, kategorie CORE se ulozi
    "vis_pritahovani_kolen_plus_lehsed": ("CORE",           "HANGING_KNEE_RAISE"), # Garmin nema, kategorie CORE se ulozi
}

DEN_CODE  = {"po": "PO", "ut": "UT", "st": "ST", "ct": "CT",
             "pa": "PA", "so": "SO", "ne": "NE"}
DEN_DELTA = {"po": 0, "ut": 1, "st": 2, "ct": 3, "pa": 4, "so": 5, "ne": 6}
TYP_CODE  = {"beh": "BEH", "silovy": "SIL", "kombinace": "KOM", "kontrolni_test": "TEST"}
TYP_LABEL = {"beh": "Beh", "silovy": "Silovy trenink", "kombinace": "Kombinace", "kontrolni_test": "Kontrolni test"}

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
    """Parsuje cíl -> (tgt_key, val1, val2).

    Vrací jeden z:
      ("none",   None, None)            - bez cíle
      ("hr_pct", lo,   hi)              - PROCENTNÍ rozsah % max. SF (NE bpm!)
      ("pace",   mps_lo, mps_hi)        - tempo v m/s

    Pozn.: '% rychlosti' a '% úsilí' jsou rychlost/úsilí (sprint), NE srdeční tep
    -> vracíme "none" (popisek zůstane v labelu).
    """
    if not cil:
        return "none", None, None
    s = str(cil)
    low = s.lower()

    # Sprint: "90 % max rychlosti" / "90 % max úsilí" -> rychlost/úsilí, NE tep
    if "rychlost" in low or "úsil" in low or "usil" in low:
        return "none", None, None

    # Rozsah %: "60-70 % SFmax" -> procentní rozsah
    m = re.search(r"(\d+)\s*[-]\s*(\d+)\s*%", s)
    if m:
        return "hr_pct", int(m.group(1)), int(m.group(2))

    # Jedno %: "75 % SFmax" / "85 % max" / "80 %" -> procento ±5 (jako dosud, ale jako %)
    m = re.search(r"(\d+)\s*%", s)
    if m:
        pct = int(m.group(1))
        return "hr_pct", max(50, pct - 5), pct + 5

    # Tempo "4:30/km" nebo "do 3:50"
    m = re.search(r"(\d+):(\d+)(?:/km)?", s)
    if m:
        pace_s_per_km = int(m.group(1)) * 60 + int(m.group(2))
        mps = 1000.0 / pace_s_per_km
        return "pace", round(mps * 0.95, 4), round(mps * 1.05, 4)

    return "none", None, None


def _zone_for_pct(pct):
    """Mapuje % max. SF na číslo zóny (1-5) dle defaultních prahů.
    Z1 <60, Z2 60-70, Z3 70-80, Z4 80-90, Z5 >=90."""
    if pct < 60:
        return 1
    if pct < 70:
        return 2
    if pct < 80:
        return 3
    if pct < 90:
        return 4
    return 5


def _resolve_hr_pct(lo, hi):
    """Převede procentní rozsah (% max. SF) na (bpm_low, bpm_high, zone_number).

    Priorita zdroje hodnot:
      1) reálné HR zóny z Connectu (HR_ZONES) -> bpm hranice odpovídající zóny
      2) jen známá max. SF (MAX_HR / --max-hr) -> bpm = pct/100 * max_hr
      3) nic -> (None, None, None) + jednorázové varování
    """
    global _HR_WARNED
    if lo is None or hi is None:
        return None, None, None

    central = (lo + hi) / 2.0
    zone = _zone_for_pct(central)

    # 1) Reálné zóny z Connectu -> použij skutečné bpm hranice té zóny
    if HR_ZONES and HR_ZONES.get("floors"):
        floors = HR_ZONES["floors"]           # [z1, z2, z3, z4, z5] floors v bpm
        max_hr = HR_ZONES.get("max_hr")
        bpm_low = floors[zone - 1]
        # horní hranice = floor další zóny; pro Z5 = max. SF
        if zone < 5:
            bpm_high = floors[zone]
        else:
            bpm_high = max_hr if max_hr else floors[4]
        return int(bpm_low), int(bpm_high), zone

    # 2) Známá jen max. SF -> spočítej bpm přímo z procent
    if MAX_HR:
        bpm_low  = round(lo / 100.0 * MAX_HR)
        bpm_high = round(hi / 100.0 * MAX_HR)
        return int(bpm_low), int(bpm_high), zone

    # 3) Nic neznámého -> bez HR cíle
    if not _HR_WARNED:
        print("  [WARN] Neznámá max. SF ani HR zóny - HR cíle budou vynechány."
              " Použij --max-hr N nebo se přihlas (zóny z Garmin Connect).")
        _HR_WARNED = True
    return None, None, None


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
            cil = k.get("cil")
            cil_txt = (" " + cil + _hr_label_suffix(cil)) if cil else ""
            if "vzdalenost_m" in k:
                parts.append(f"Beh {k['vzdalenost_m']}m{cil_txt}")
            elif "cas_min" in k:
                parts.append(f"Beh {k['cas_min']}min{cil_txt}")
        elif kr == "pyramida":
            useky = k.get("useky_m", [])
            parts.append(f"Pyramida: {'-'.join(str(u) for u in useky)}m")
    desc = (podtyp + ": " if podtyp else "") + ", ".join(parts)
    if day_data.get("popis"):
        desc = day_data["popis"] + (" | " + desc if desc else "")
    return desc or None


def _step(stype, end_key, end_val=None, tgt="none", v1=None, v2=None,
          desc=None, ex_cat=None, ex_name=None, order=1, zone=None):
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
    if zone is not None:
        s["zoneNumber"] = zone
    if desc:
        s["description"] = desc
    if ex_cat:
        s["category"] = ex_cat
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
def _resolve_step_target(cil):
    """Z YAML cíle vrátí (tgt_key, v1, v2, zone, label_suffix) pro běžecký krok.

    - hr_pct  -> převede na bpm + zónu (dle reálných zón / max. SF).
                 Pokud se nepodaří, vrátí no.target, ale popisek % zachová.
    - pace    -> beze změny.
    - none    -> bez cíle (label_suffix prázdný).
    label_suffix je text k doplnění do popisku kroku, např. " [Z2, 114-133]".
    """
    tgt, a, b = _parse_target(cil)

    if tgt == "hr_pct":
        bpm_low, bpm_high, zone = _resolve_hr_pct(a, b)
        if bpm_low is not None:
            suffix = f" [Z{zone}, {bpm_low}-{bpm_high}]"
            return "hr", bpm_low, bpm_high, zone, suffix
        # nešlo přepočítat (neznámá max. SF) -> bez HR cíle, popis % zůstává v cil_str
        return "none", None, None, None, ""

    if tgt == "pace":
        return "pace", a, b, None, ""

    return "none", None, None, None, ""


def _hr_label_suffix(cil):
    """Vrátí popisek typu ' [Z2, 114-133]' pro HR cíl, jinak prázdný řetězec.
    Používá se v ICS / popisech (ne ve struktuře kroku)."""
    _, _, _, _, suffix = _resolve_step_target(cil)
    return suffix


def _run_steps(kroky):
    out = []

    for k in kroky:
        krok = k.get("krok", "")
        cil  = k.get("cil")
        desc = k.get("popis") or k.get("poznamka")
        tgt, v1, v2, zone, tgt_suffix = _resolve_step_target(cil)

        if krok == "rozklusani":
            secs = _int_range(k.get("cas_min", 10)) * 60
            out.append(_step("warmup", "time", secs, desc=desc or "Rozklusani"))

        elif krok == "vyklus":
            secs = _int_range(k.get("cas_min", 10)) * 60
            out.append(_step("cooldown", "time", secs, desc=desc or "Vyklus"))

        elif krok in ("beh", "usek"):
            cil_str = f" ({cil}){tgt_suffix}" if cil else ""
            if "vzdalenost_m" in k:
                label = (desc + tgt_suffix) if desc else f"Beh {k['vzdalenost_m']}m{cil_str}"
                out.append(_step("interval", "dist", k["vzdalenost_m"], tgt, v1, v2, label, zone=zone))
            elif "vzdalenost_km" in k:
                raw = k["vzdalenost_km"]
                km = _int_range(raw) if isinstance(raw, str) and "-" in raw else float(raw)
                label = (desc + tgt_suffix) if desc else f"Beh {raw}km{cil_str}"
                out.append(_step("interval", "dist", int(km * 1000), tgt, v1, v2, label, zone=zone))
            elif "cas_min" in k:
                secs = _int_range(k["cas_min"]) * 60
                label = (desc + tgt_suffix) if desc else f"Beh {k['cas_min']}min{cil_str}"
                out.append(_step("interval", "time", secs, tgt, v1, v2, label, zone=zone))
            elif "cas_s" in k:
                label = (desc + tgt_suffix) if desc else f"Beh {k['cas_s']}s{cil_str}"
                out.append(_step("interval", "time", k["cas_s"], tgt, v1, v2, label, zone=zone))
            else:
                out.append(_step("interval", "lap", tgt=tgt, v1=v1, v2=v2,
                                 desc=(desc + tgt_suffix) if desc else f"Beh{cil_str}", zone=zone))

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
def _cvik_steps(c, pauza_faktor=1.0):
    key     = c.get("cvik", "")
    cat, ex = EXERCISE_MAP.get(key, ("OTHER", key.upper()))
    desc    = _cvik_label(c)   # Czech name + count/time
    pauza_s = int(_int_range(c.get("pauza_s", 60), default=60) * pauza_faktor)
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


def build_strength_workout(day_data, name, pauza_faktor=1.0):
    cviky       = day_data.get("cviky", [])
    kola        = _int_range(day_data.get("kola", 1))
    pauza_kola  = int(day_data.get("pauza_mezi_koly_s", 120) * pauza_faktor)
    po_treninku = day_data.get("po_treninku", [])

    round_steps = []
    for c in cviky:
        if c.get("krok") == "pauza":
            secs = int((c.get("cas_s") or _int_range(c.get("cas_min", 2)) * 60) * pauza_faktor)
            round_steps.append(_step("rest", "time", secs, desc="Pauza"))
        else:
            round_steps.extend(_cvik_steps(c, pauza_faktor))

    if kola > 1 and round_steps:
        round_steps.append(_step("rest", "time", pauza_kola,
                                 desc=f"Pauza mezi koly ({pauza_kola}s)"))
        top_steps = [_repeat_group(kola, round_steps)]
    else:
        top_steps = round_steps

    for c in po_treninku:
        top_steps.extend(_cvik_steps(c, pauza_faktor))

    desc = _build_strength_desc(day_data)
    extra = day_data.get("kroky_pred") or day_data.get("poznamka")
    if extra:
        desc = extra + " | " + desc if desc else extra
    return _envelope(name, "strength_training", _renumber(top_steps), description=desc)


# ── Combo builder ──────────────────────────────────────────────────────────────
def build_combo_workout(day_data, name, pauza_faktor=1.0):
    bloky      = day_data.get("bloky", [])
    kola       = _int_range(day_data.get("kola", 1))
    pauza_kola = int(day_data.get("pauza_mezi_koly_s", 180) * pauza_faktor)
    round_steps = []

    for b in bloky:
        if "cvik" in b:
            round_steps.extend(_cvik_steps(b, pauza_faktor))
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
def day_to_workout(day_data, name, pauza_faktor=1.0):
    typ = day_data.get("typ", "volno")
    if typ in ("volno", "aktivni_odpocinek"):
        return None
    if typ == "beh":
        return build_running_workout(day_data, name)
    if typ == "silovy":
        return build_strength_workout(day_data, name, pauza_faktor)
    if typ == "kombinace":
        return build_combo_workout(day_data, name, pauza_faktor)
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


def _get_hr_zones(api):
    """Načte HR zóny z Garmin Connectu a vrátí dict pro běh:
        {"max_hr": int, "floors": [z1..z5], "method": str}
    Preferuje sport RUNNING, jinak DEFAULT. Při chybě / chybějících datech
    vrátí None a vypíše varování. Tolerantní k variantám názvů polí.
    """
    try:
        data = api.connectapi("/biometric-service/heartRateZones")
    except Exception as e:
        print(f"  [WARN] Nepodařilo se načíst HR zóny z Connectu: {e}")
        return None

    # Endpoint vrací seznam objektů (jeden na sport: DEFAULT/RUNNING/CYCLING),
    # ale buď defenzivní i vůči jednomu objektu / jinému obalu.
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        # možný obal typu {"heartRateZones": [...]} nebo přímo jeden záznam
        if isinstance(data.get("heartRateZones"), list):
            entries = data["heartRateZones"]
        else:
            entries = [data]
    if not entries:
        print("  [WARN] HR zóny z Connectu prázdné / neočekávaný formát.")
        return None

    def _sport_of(e):
        return str(e.get("sport") or e.get("zone") or e.get("sportType") or "").upper()

    chosen = (next((e for e in entries if _sport_of(e) == "RUNNING"), None)
              or next((e for e in entries if _sport_of(e) == "DEFAULT"), None)
              or entries[0])

    # max. SF (tolerantní k variantám názvů)
    max_hr = (chosen.get("maxHeartRateUsed") or chosen.get("maxHeartRate")
              or chosen.get("maxHr"))

    # hranice zón: buď zone{N}Floor, nebo seznam s min/max
    floors = []
    if all(chosen.get(f"zone{i}Floor") is not None for i in range(1, 6)):
        floors = [int(chosen[f"zone{i}Floor"]) for i in range(1, 6)]
    else:
        zlist = chosen.get("heartRateZones") or chosen.get("zones")
        if isinstance(zlist, list) and zlist:
            for z in zlist[:5]:
                lo = (z.get("floor") if isinstance(z, dict) else None)
                if lo is None and isinstance(z, dict):
                    lo = z.get("min") or z.get("low") or z.get("secsInZone")
                if lo is not None:
                    floors.append(int(lo))

    method = (chosen.get("trainingMethod") or chosen.get("method")
              or chosen.get("zoneCalculationMethod"))

    if not floors and not max_hr:
        print("  [WARN] HR zóny: nenalezena ani max. SF, ani hranice zón.")
        return None

    return {
        "max_hr": int(max_hr) if max_hr else None,
        "floors": floors,           # [z1..z5] floors v bpm (může být prázdné)
        "method": method,
        "sport":  _sport_of(chosen),
    }


def _apply_max_hr(max_hr):
    """Nastaví modulový MAX_HR (ruční override z --max-hr)."""
    global MAX_HR
    if max_hr:
        MAX_HR = int(max_hr)


def _load_hr_state(api, max_hr_override=None):
    """Naplní modulové HR_ZONES / MAX_HR a vypíše přehled.

    Priorita: --max-hr (override) > zóny z Connectu > nic (varování při použití).
    Po načtení zón z Connectu má --max-hr přednost jako hodnota max. SF.
    """
    global HR_ZONES, MAX_HR

    if api is not None:
        zones = _get_hr_zones(api)
        if zones:
            HR_ZONES = zones
            if zones.get("max_hr"):
                MAX_HR = zones["max_hr"]

    # --max-hr má přednost (přepíše i hodnotu z Connectu)
    if max_hr_override:
        MAX_HR = int(max_hr_override)
        if HR_ZONES:
            HR_ZONES["max_hr"] = MAX_HR

    # Přehled
    if HR_ZONES and HR_ZONES.get("floors"):
        floors = HR_ZONES["floors"]
        zsport = HR_ZONES.get("sport", "?")
        zmeth  = HR_ZONES.get("method", "?")
        print(f"HR zóny ({zsport}, metoda {zmeth}): max. SF {MAX_HR or '?'} bpm,"
              f" hranice Z1-Z5 = {floors} bpm")
    elif MAX_HR:
        print(f"HR cíle počítány z max. SF {MAX_HR} bpm (bez reálných zón z Connectu).")
    else:
        print("HR cíle: neznámá max. SF ani zóny - běžecké HR cíle budou vynechány."
              " (Použij --max-hr N nebo se přihlas.)")


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


def fetch_garmin_cviky(api, output_file="cviky-garmin.json"):
    """Stáhne seznam všech cviků z Garmin Connect a uloží do JSON."""
    print("Stahuji seznam cviků z Garmin Connect...")
    try:
        cats_raw = api.connectapi("/workout-service/workout/exercise/categories")
    except Exception as e:
        print(f"CHYBA při stahování kategorií: {e}")
        sys.exit(1)

    if not isinstance(cats_raw, list):
        print("Neočekávaný formát odpovědi (není list). Raw odpověď:")
        print(json.dumps(cats_raw, ensure_ascii=False, indent=2)[:2000])
        sys.exit(1)

    result = {}
    for cat in cats_raw:
        cat_key = cat.get("exerciseCategoryKey") or cat.get("key") or str(cat)
        cat_id  = cat.get("exerciseCategoryId") or cat.get("id")
        try:
            names_raw = api.connectapi(
                "/workout-service/workout/exercise/names",
                params={"categoryId": cat_id}
            )
            result[cat_key] = [
                n.get("exerciseNameKey") or n.get("key") or str(n)
                for n in (names_raw if isinstance(names_raw, list) else [])
            ]
        except Exception:
            result[cat_key] = []

    out_path = Path(output_file)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v) for v in result.values())
    print(f"Uloženo {len(result)} kategorií, {total} cviků -> {out_path.resolve()}")


def validate_exercise_map(garmin_json_path):
    """Ověří EXERCISE_MAP proti staženému JSON s Garmin cviky."""
    p = Path(garmin_json_path)
    if not p.exists():
        print(f"CHYBA: soubor {p} nenalezen. Spusť nejdřív --fetch-cviky.")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        garmin_cviky = json.load(f)

    known = {(cat, name) for cat, names in garmin_cviky.items() for name in names}

    ok = err = 0
    for cvik_cs, (cat, name) in sorted(EXERCISE_MAP.items()):
        if (cat, name) in known:
            print(f"  OK  {cvik_cs}: {cat} / {name}")
            ok += 1
        else:
            candidates = garmin_cviky.get(cat, [])
            suggestion = next(
                (c for c in candidates if name in c or c in name), None
            ) or (candidates[0] if candidates else None)
            hint = f"  --> zkus: {suggestion}" if suggestion else "  (kategorie nenalezena)"
            print(f"  ERR {cvik_cs}: {cat} / {name} -- NENALEZENO{hint}")
            err += 1

    print(f"\nVýsledek: {ok} OK, {err} chyb z {ok + err} cviků.")
    if err:
        print("Uprav EXERCISE_MAP v push_plan.py dle výše.")


def push_plan(plan_name="muzi", weeks_limit=None, dry_run=False,
              email=None, password=None, no_save=False, start_override=None,
              pauza_faktor=1.0, from_week=1, max_hr=None):
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

    _validate_start(start_date)

    if pauza_faktor != 1.0:
        print(f"Zkrácení pauz na {pauza_faktor*100:.0f}% (--pauza-faktor {pauza_faktor})")

    api = None
    existing_by_name = {}
    if not dry_run:
        print("Prihlasování do Garmin Connect...")
        api = _connect(email, password, no_save)
        print(f"Prihlasen. Nacitám HR zóny a existující workouty...")
        # HR stav MUSÍ být načten PŘED stavbou workoutů (běžecké HR cíle se z něj počítají)
        _load_hr_state(api, max_hr_override=max_hr)
        existing = api.get_workouts(0, 1000)
        existing_by_name = {w["workoutName"]: w["workoutId"] for w in existing}
        print(f"  nalezeno {len(existing_by_name)} existujících workoutu")
    else:
        # dry-run: zóny z Connectu nedostupné, využij jen --max-hr (pokud zadáno)
        _load_hr_state(None, max_hr_override=max_hr)

    total = 0
    for tyden_data in plan.get("tydny", []):
        tyden = tyden_data["tyden"]
        if weeks_limit and tyden > weeks_limit:
            break
        if tyden < from_week:
            continue

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
            workout = day_to_workout(day_data, name, pauza_faktor)
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


# ── Validace a odhad délky ────────────────────────────────────────────────────
def _validate_start(date):
    """Varování pokud datum není pondělí."""
    if date.weekday() != 0:
        dny = ["pondeli", "utery", "streda", "ctvrtek", "patek", "sobota", "nedele"]
        print(f"VAROVANI: {date} je {dny[date.weekday()]}, ne pondeli."
              f" Plan predpoklada pondeli jako 1. den tydne.")


def _estimate_beh_sec(kroky):
    """Odhadne délku běžeckých kroků v sekundách (rekurzivně)."""
    total = 0
    for k in kroky:
        kr = k.get("krok", "")
        if kr in ("rozklusani", "vyklus", "klus"):
            total += k.get("cas_min", 10) * 60
        elif kr in ("beh", "usek"):
            if "cas_s" in k:
                total += k["cas_s"]
            elif "cas_min" in k:
                total += k["cas_min"] * 60
            elif "vzdalenost_m" in k:
                total += k["vzdalenost_m"] / 150 * 60
            elif "vzdalenost_km" in k:
                total += k["vzdalenost_km"] * 1000 / 150 * 60
        elif kr in ("chuze", "pauza"):
            if "cas_s" in k:
                total += k["cas_s"]
            elif "cas_min" in k:
                total += k["cas_min"] * 60
        elif kr == "opakovat":
            total += k.get("pocet", 1) * _estimate_beh_sec(k.get("obsah", []))
        elif kr == "pyramida":
            useky = k.get("useky_m", [])
            total += sum(useky) / 150 * 60 * 2  # beh + pauzy
    return total


def _estimate_duration_min(day_data):
    """Odhadne délku tréninku v minutách."""
    typ = day_data.get("typ", "")
    if typ == "kontrolni_test":
        return 40
    if typ == "beh":
        return max(20, round(_estimate_beh_sec(day_data.get("kroky", [])) / 60))
    if typ in ("silovy", "kombinace"):
        kola = _int_range(day_data.get("kola", 1))
        one_round_sec = 0
        for c in day_data.get("cviky", []):
            serie = _int_range(c.get("serie", 1))
            cvik_s = int(c.get("cas_s") or _int_range(c.get("opakovani", 10)) * 3)
            one_round_sec += serie * (cvik_s + _int_range(c.get("pauza_s", 60)))
        pauza_kola = day_data.get("pauza_mezi_koly_s", 180)
        total_sec = kola * one_round_sec + max(0, kola - 1) * pauza_kola + 300
        if typ == "kombinace":
            total_sec += _estimate_beh_sec(day_data.get("kroky", []))
        return max(20, round(total_sec / 60))
    return 45


# ── ICS export (Google Kalendář) ───────────────────────────────────────────────
def _ics_fold(line):
    """Rozdělí řádek na max 75 oktetů dle RFC 5545."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line + "\r\n"
    result = []
    while len(encoded) > 75:
        split = 75
        while split > 0 and (encoded[split] & 0xC0) == 0x80:
            split -= 1
        result.append(encoded[:split].decode("utf-8"))
        encoded = b" " + encoded[split:]
    result.append(encoded.decode("utf-8"))
    return "\r\n".join(result) + "\r\n"


def _ics_escape(text):
    """Escapuje speciální znaky pro ICS hodnoty."""
    return (text
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n"))


def _ics_description(day_data):
    """Sestaví čitelný popis pro ICS událost podle typu tréninku."""
    typ = day_data.get("typ", "")
    if typ == "silovy":
        parts = []
        kola = day_data.get("kola")
        if kola:
            parts.append(f"Kola: {kola}")
        for c in day_data.get("cviky", []):
            key  = c.get("cvik", "")
            name = CVIK_CS.get(key, key.replace("_", " ").capitalize())
            serie = c.get("serie", 1)
            if "opakovani" in c:
                parts.append(f"{name}: {serie}x {c['opakovani']} opak.")
            elif "cas_s" in c:
                parts.append(f"{name}: {serie}x {c['cas_s']}s")
            else:
                parts.append(_cvik_label(c))
        return "\n".join(parts)
    if typ == "beh":
        return _build_run_desc(day_data) or "Beh"
    if typ == "kombinace":
        parts = []
        if day_data.get("cviky"):
            parts.append(_build_strength_desc(day_data))
        if day_data.get("kroky"):
            run_desc = _build_run_desc(day_data)
            if run_desc:
                parts.append(run_desc)
        return "\n".join(p for p in parts if p)
    if typ == "kontrolni_test":
        return "Kontrolni test:\n- 12min beh (max vzdalenost)\n- Leh-sedy 1 min\n- Kliky 30s"
    return ""


def generate_ics(plan_name="muzi", weeks_limit=None, start_override=None,
                 out_file="vtp-plan.ics", start_time=None):
    """Vygeneruje ICS soubor pro import do Google Kalendáře."""
    plan_file = PLAN_DIR / f"vtp-plan-{plan_name}.yaml"
    if not plan_file.exists():
        print(f"CHYBA: soubor {plan_file} neexistuje.")
        sys.exit(1)
    with open(plan_file, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    if start_override:
        start_date = datetime.date.fromisoformat(start_override)
    else:
        start_str = plan["meta"].get("start_datum")
        if not start_str:
            print("CHYBA: 'start_datum' neni nastaven v YAML. Pouzij --start YYYY-MM-DD.")
            sys.exit(1)
        start_date = datetime.date.fromisoformat(str(start_str))

    _validate_start(start_date)

    t = None
    if start_time:
        h, m = map(int, start_time.split(":"))
        t = datetime.time(h, m)

    ics_lines = []
    ics_lines.append("BEGIN:VCALENDAR\r\n")
    ics_lines.append("VERSION:2.0\r\n")
    ics_lines.append("PRODID:-//VTP Treninkovy plan//CS\r\n")
    ics_lines.append("CALSCALE:GREGORIAN\r\n")
    ics_lines.append("METHOD:PUBLISH\r\n")

    count = 0
    for tyden_data in plan.get("tydny", []):
        tyden = tyden_data["tyden"]
        if weeks_limit and tyden > weeks_limit:
            break
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
            label   = TYP_LABEL.get(typ, typ.replace("_", " ").capitalize())
            summary = f"VTP T{tyden:02d} {DEN_CODE[den_key]} - {label}"
            uid     = name.lower() + "@garmin-treninky"
            desc    = _ics_description(day_data)

            ics_lines.append("BEGIN:VEVENT\r\n")
            ics_lines.append(_ics_fold(f"UID:{uid}"))
            if t:
                duration_min = _estimate_duration_min(day_data)
                dt_start = datetime.datetime.combine(date, t)
                dt_end   = dt_start + datetime.timedelta(minutes=duration_min)
                ics_lines.append(_ics_fold(f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%S')}"))
                ics_lines.append(_ics_fold(f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}"))
            else:
                dtend = date + datetime.timedelta(days=1)
                ics_lines.append(_ics_fold(f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}"))
                ics_lines.append(_ics_fold(f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}"))
            ics_lines.append(_ics_fold(f"SUMMARY:{summary}"))
            if desc:
                ics_lines.append(_ics_fold(f"DESCRIPTION:{_ics_escape(desc)}"))
            ics_lines.append("END:VEVENT\r\n")
            count += 1

    ics_lines.append("END:VCALENDAR\r\n")

    out_path = Path(out_file)
    out_path.write_bytes("".join(ics_lines).encode("utf-8"))
    print(f"Vygenerovano {count} udalosti -> {out_path.resolve()}")
    print("Import: Google Calendar -> + (Dalsi kalendare) -> Importovat")


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
    p.add_argument("--ics",     nargs="?", const="vtp-plan.ics", metavar="SOUBOR",
                   help="Vygenerovat ICS soubor pro Google Kalendar (default: vtp-plan.ics)")
    p.add_argument("--time",    default=None, metavar="HH:MM",
                   help="Cas zacatku treninku v ICS (napr. 06:30); bez toho jsou udalosti celodennni")
    p.add_argument("--delete",   action="store_true",
                   help="Smazat vsechny VTP-T* workouty z Garmin Connect (bez nahrani)")
    p.add_argument("--no-save",  action="store_true",
                   help="Neukladat Garmin token na disk (pouzij pro jednourazove spusteni)")
    p.add_argument("--email",    default=None, help="Garmin Connect e-mail")
    p.add_argument("--password", default=None, help="Garmin Connect heslo")
    p.add_argument("--pauza-faktor", type=float, default=1.0, metavar="FLOAT",
                   help="Násobitel pauz (default 1.0; pro pasivní odpočinek doporučeno 0.5)")
    p.add_argument("--fetch-cviky", nargs="?", const="cviky-garmin.json", metavar="SOUBOR",
                   help="Stáhne seznam cviků z Garmin Connect do JSON (default: cviky-garmin.json)")
    p.add_argument("--validate-cviky", default=None, metavar="SOUBOR",
                   help="Ověří EXERCISE_MAP proti staženému JSON (výstup --fetch-cviky)")
    p.add_argument("--od-tydne", type=int, default=1, metavar="N",
                   help="Začít nahrávat od týdne N (přeskočí týdny 1..N-1); default: 1")
    p.add_argument("--max-hr", type=int, default=None, metavar="N",
                   help="Ruční max. SF pro výpočet HR cílů (override / fallback pro --dry-run)."
                        " Priorita: --max-hr > zóny z Garmin Connect > bez HR cíle")
    args = p.parse_args()

    if args.validate_cviky:
        validate_exercise_map(args.validate_cviky)
    elif args.fetch_cviky is not None:
        api = _connect(args.email, args.password, args.no_save)
        fetch_garmin_cviky(api, args.fetch_cviky)
    elif args.ics:
        # Pro ICS popisky využijeme --max-hr (jinak HR cíle zůstanou jen jako %)
        _apply_max_hr(args.max_hr)
        generate_ics(
            plan_name=args.plan,
            weeks_limit=args.weeks,
            start_override=args.start,
            out_file=args.ics,
            start_time=args.time,
        )
    elif args.delete:
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
            pauza_faktor=args.pauza_faktor,
            from_week=args.od_tydne,
            max_hr=args.max_hr,
        )


if __name__ == "__main__":
    main()
