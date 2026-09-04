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
import copy
import datetime
import io
import json
import re
import sys
import time
from pathlib import Path

# Zajistíme UTF-8 výstup na Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import yaml

def _import_garmin():
    """Naimportuje garminconnect az ve chvili, kdy je potreba prihlaseni.

    Offline rezimy (--dry-run, --ics, --validate-cviky, --zkontroluj-plan) tak
    bezi jen s pyyaml - diky tomu je lze spustit i v CI a mimo Windows.
    """
    try:
        from garminconnect import Garmin
    except ImportError:
        print("Chybí knihovna garminconnect. Spusť: pip install garminconnect pyyaml")
        sys.exit(1)
    return Garmin

PLAN_DIR  = Path(__file__).parent / "plan"
TOKEN_DIR = Path.home() / ".garmin_tokens"

# ── HR zóny / max. SF (naplní se po přihlášení nebo z --max-hr) ─────────────────
# HR_ZONES: dict {"max_hr": int, "floors": [z1..z5], "method": str} nebo None
HR_ZONES = None
MAX_HR   = None
_HR_WARNED = False   # aby se varování "neznámá max. SF" vypsalo jen jednou
_CVIK_WARNED = set()  # cviky mimo EXERCISE_MAP - varovat u kazdeho jen jednou

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


def _vtp_name(tyden, den_key, typ):
    """Sestaví jednotný název workoutu: VTP-T{TT}-{DEN}-{TYP}."""
    return f"VTP-T{tyden:02d}-{DEN_CODE[den_key]}-{TYP_CODE.get(typ, typ.upper())}"

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


def _parse_target(cil, vzdalenost_m=None):
    """Parsuje cíl -> (tgt_key, val1, val2).

    Vrací jeden z:
      ("none",    None, None)           - bez cíle
      ("hr_abs",  bpm,  bpm)            - ABSOLUTNÍ tep (bpm)
      ("hr_pct",  lo,   hi)             - PROCENTNÍ rozsah % max. SF (NE bpm!)
      ("pace",    mps_lo, mps_hi)       - tempo v m/s

    Pozn.: '% rychlosti' a '% úsilí' jsou rychlost/úsilí (sprint), NE srdeční tep
    -> vracíme "none" (popisek zůstane v labelu).

    Tempo: "X:YY/km" (explicitní /km) je tempo přímo na km. "do X:YY", "max do X:YY"
    nebo "NN s/kolo" (bez /km) je CELKOVÝ ČAS na daný úsek -> tempo se dopočítá jako
    vzdalenost_m / celkový_čas (proto je potřeba znát vzdálenost úseku).
    """
    if not cil:
        return "none", None, None
    s = str(cil)
    low = s.lower()

    # Sprint: "90 % max rychlosti" / "90 % max úsilí" -> rychlost/úsilí, NE tep
    if "rychlost" in low or "úsil" in low or "usil" in low:
        return "none", None, None

    # Absolutní tep: "120 tep/min", "průměrná SF 120 tep/min"
    m = re.search(r"(\d+)\s*tep", low)
    if m:
        bpm = int(m.group(1))
        return "hr_abs", bpm, bpm

    # Rozsah %: "60-70 % SFmax" -> procentní rozsah
    m = re.search(r"(\d+)\s*[-]\s*(\d+)\s*%", s)
    if m:
        return "hr_pct", int(m.group(1)), int(m.group(2))

    # Jedno %: "75 % SFmax" / "85 % max" / "80 %" -> procento ±5 (jako dosud, ale jako %)
    m = re.search(r"(\d+)\s*%", s)
    if m:
        pct = int(m.group(1))
        return "hr_pct", max(50, pct - 5), pct + 5

    # Tempo přímo na km: "tempo 4:20-4:30/km" (jen první hodnota + ±5 % pásmo)
    if "/km" in low:
        m = re.search(r"(\d+):(\d+)", s)
        if m:
            pace_s_per_km = int(m.group(1)) * 60 + int(m.group(2))
            mps = 1000.0 / pace_s_per_km
            return "pace", round(mps * 0.95, 4), round(mps * 1.05, 4)
        return "none", None, None

    # Celkový čas na úsek: "max do 1:50", "max, do 7:45", "tempo 90 s/kolo"
    m = re.search(r"(\d+):(\d+)", s)
    total_s = int(m.group(1)) * 60 + int(m.group(2)) if m else None
    if total_s is None:
        m = re.search(r"(\d+)\s*s\b", low)
        total_s = int(m.group(1)) if m else None
    if total_s and vzdalenost_m:
        mps = vzdalenost_m / total_s
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


def _resolve_hr_abs(bpm):
    """Převede absolutní tep (bpm, např. 'průměrná SF 120 tep/min') na
    (bpm_low, bpm_high, zone_number) — najde zónu z reálných hranic (HR_ZONES),
    do níž bpm spadá, a vrátí její hranice. Stejná priorita zdroje jako
    _resolve_hr_pct (reálné zóny z Connectu > jen max. SF > nic)."""
    global _HR_WARNED
    if HR_ZONES and HR_ZONES.get("floors"):
        floors = HR_ZONES["floors"]
        max_hr = HR_ZONES.get("max_hr")
        zone = 1
        for i, floor in enumerate(floors, start=1):
            if bpm >= floor:
                zone = i
        bpm_low = floors[zone - 1]
        bpm_high = floors[zone] if zone < 5 else (max_hr if max_hr else floors[4])
        return int(bpm_low), int(bpm_high), zone

    if MAX_HR:
        zone = _zone_for_pct(bpm / MAX_HR * 100.0)
        return bpm - 5, bpm + 5, zone

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
    # 'bloky' jako fallback: silove i combo dny je pouzivaji misto 'cviky'
    for c in day_data.get("cviky") or day_data.get("bloky") or []:
        if c.get("krok") == "pauza":
            continue
        lbl = _cvik_label(c)
        if lbl:
            parts.append(lbl)
    kola = day_data.get("kola")
    prefix = f"{kola}x kolo: " if kola and str(kola) != "1" else ""
    return prefix + " | ".join(parts)


def _klus_label(sub):
    """'klus 60s' / 'klus 3min' - jednotka podle toho, ktery klic je zadan."""
    if "cas_min" in sub:
        return f"klus {sub['cas_min']}min"
    return f"klus {sub.get('cas_s','?')}s"


def _format_opakovat_obsah(obsah):
    """Popis obsahu 'opakovat' - rekurzivne, aby vnorene 'opakovat'
    (napr. 2 kola x 10 sprintu) nedalo prazdne '2x ()'."""
    inner = []
    for sub in obsah or []:
        sk = sub.get("krok", "")
        if sk == "chuze":
            inner.append(f"chuze {sub.get('cas_s','?')}s")
        elif sk == "beh":
            t = sub.get("cas_s") or (str(sub.get("cas_min","?"))+"min")
            sub_cil = sub.get("cil")
            sub_txt = (" " + sub_cil + _hr_label_suffix(sub_cil)) if sub_cil else ""
            inner.append((f"beh {t}s" if sub.get("cas_s") else f"beh {t}") + sub_txt)
        elif sk == "usek":
            sub_cil = sub.get("cil")
            sub_txt = (" " + sub_cil + _hr_label_suffix(sub_cil, sub.get("vzdalenost_m"))) if sub_cil else ""
            inner.append(f"{sub.get('vzdalenost_m','?')}m{sub_txt}")
        elif sk == "klus":
            inner.append(_klus_label(sub))
        elif sk == "opakovat":
            sub_pocet = sub.get("pocet", 1)
            inner.append(f"{sub_pocet}x ({_format_opakovat_obsah(sub.get('obsah', []))})")
    return " + ".join(inner)


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
        elif kr == "klus":
            parts.append(_klus_label(k).capitalize())
        elif kr == "opakovat":
            pocet = k.get("pocet", 1)
            parts.append(f"{pocet}x ({_format_opakovat_obsah(k.get('obsah', []))})")
        elif kr in ("beh", "usek"):
            cil = k.get("cil")
            cil_txt = (" " + cil + _hr_label_suffix(cil, k.get("vzdalenost_m"))) if cil else ""
            if "vzdalenost_m" in k:
                parts.append(f"Beh {k['vzdalenost_m']}m{cil_txt}")
            elif "cas_min" in k:
                parts.append(f"Beh {k['cas_min']}min{cil_txt}")
        elif kr == "pyramida":
            useky = k.get("useky_m", [])
            cil = k.get("cil")
            cil_txt = (" " + cil + _hr_label_suffix(cil)) if cil else ""
            parts.append(f"Pyramida: {'-'.join(str(u) for u in useky)}m{cil_txt}")
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
def _resolve_step_target(cil, vzdalenost_m=None):
    """Z YAML cíle vrátí (tgt_key, v1, v2, zone, label_suffix) pro běžecký krok.

    - hr_abs  -> absolutní bpm převede na zónu (dle reálných zón / max. SF).
    - hr_pct  -> převede na bpm + zónu (dle reálných zón / max. SF).
                 Pokud se nepodaří, vrátí no.target, ale popisek % zachová.
    - pace    -> beze změny (pro "celkový čas na úsek" potřebuje vzdalenost_m).
    - none    -> bez cíle (label_suffix prázdný).
    label_suffix je text k doplnění do popisku kroku, např. " [Z2, 114-133]".
    """
    tgt, a, b = _parse_target(cil, vzdalenost_m)

    if tgt == "hr_abs":
        bpm_low, bpm_high, zone = _resolve_hr_abs(a)
        if bpm_low is not None:
            suffix = f" [Z{zone}, {bpm_low}-{bpm_high}]"
            return "hr", bpm_low, bpm_high, zone, suffix
        return "none", None, None, None, ""

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


def _hr_label_suffix(cil, vzdalenost_m=None):
    """Vrátí popisek typu ' [Z2, 114-133]' pro HR cíl, jinak prázdný řetězec.
    Používá se v ICS / popisech (ne ve struktuře kroku)."""
    _, _, _, _, suffix = _resolve_step_target(cil, vzdalenost_m)
    return suffix


def _run_steps(kroky):
    out = []

    for k in kroky:
        krok = k.get("krok", "")
        cil  = k.get("cil")
        desc = k.get("popis") or k.get("poznamka")
        vzd_m = k.get("vzdalenost_m")
        if vzd_m is None and "vzdalenost_km" in k:
            raw_km = k["vzdalenost_km"]
            vzd_m = (_int_range(raw_km) if isinstance(raw_km, str) and "-" in raw_km else float(raw_km)) * 1000
        tgt, v1, v2, zone, tgt_suffix = _resolve_step_target(cil, vzd_m)

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
            pauza_mezi = _int_range(k["pauza_mezi_s"]) if "pauza_mezi_s" in k else None
            # pauza MEZI opakovanimi (analogie pauza_mezi_koly_s v build_strength_workout/
            # build_combo_workout) - posledni opakovani ji nedostane, nic uz nenasleduje.
            # sub_steps se pred pridanim pauzy zbavi vlastniho koncoveho rest/recovery
            # (napr. otevreny klus) - jinak by na konci kazdeho kola byly dve pauzy za sebou.
            if pauza_mezi and pocet > 1 and sub_steps:
                core = list(sub_steps)
                # len(core) > 1: nikdy nesmaz UPLNE cely obsah (degenerovany
                # pripad - "obsah" je jen jeden otevreny klus/pauza) - to by
                # tise zahodilo cely predpis a kolo by skoncilo jen na pauze
                while len(core) > 1 and core[-1]["stepType"]["stepTypeKey"] in ("rest", "recovery"):
                    core.pop()
                grouped = [dict(s) for s in core]
                grouped.append(_step("rest", "time", pauza_mezi,
                                     desc=f"Pauza mezi opakovanimi ({pauza_mezi}s)"))
                out.append(_repeat_group(pocet - 1, grouped))
                out.extend(dict(s) for s in core)
            # pokud poslední krok opakování je pauza/klus, poslední opakování ji
            # nedostane - nic dalšího uvnitř opakování už nenásleduje
            elif pocet > 1 and sub_steps and sub_steps[-1]["stepType"]["stepTypeKey"] in ("rest", "recovery"):
                out.append(_repeat_group(pocet - 1, [dict(s) for s in sub_steps]))
                out.extend(dict(s) for s in sub_steps[:-1])
            else:
                out.append(_repeat_group(pocet, sub_steps))

        elif krok == "pyramida":
            # Pauza mezi useky je podle zdroje "1:1", tedy STEJNE DLOUHA JAKO USEK
            # a proklusava se -> konci na VZDALENOST, ne na cas. Driv se sem posilala
            # delka useku v metrech jako sekundy, takze 1600 m dalo pauzu 26:40.
            cil_str = f" ({cil}){tgt_suffix}" if cil else ""
            useky      = k.get("useky_m", [])
            pauza_s    = k.get("pauza_cas_s")            # varianta na cas (nepovinna)
            pomer      = k.get("pauza_pomer", 1)         # 1 = pauza stejne dlouha jako usek
            for i, dist in enumerate(useky):
                label = f"{dist}m{cil_str}"
                out.append(_step("interval", "dist", dist, tgt, v1, v2, label, zone=zone))
                # bez pauzy po poslednim useku - nasleduje uz jen vyklus
                if i < len(useky) - 1:
                    if pauza_s:
                        out.append(_step("rest", "time", pauza_s, desc=f"Pauza {pauza_s}s"))
                    else:
                        p = max(1, int(dist * pomer))
                        out.append(_step("recover", "dist", p,
                                         desc=f"Klus {p}m ({pomer:g}:1)"))

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


TEST_BEH_S = 720            # 12 min behu v kontrolnim testu
TEST_TEMPO_PASMO = 0.03     # +-3 % tolerance kolem cilového tempa


def build_test_workout(day_data, name):
    """Kontrolni test: 12min beh + leh-sedy + kliky.

    `cil_beh_m` (nepovinne) = na jakou vzdalenost rozvrhnout 12min beh. Prepocte
    se na tempo a nasadi jako cil kroku, takze hodinky ukazuji cilove tempo a
    hlasi vypadnuti z pasma. Bez nej krok zadny cil nema (jako driv) a bezec
    jede na pocit - coz vede k prilis rychlemu zacatku a propadu ve druhe pulce.

    POZOR: `cil_beh_m` je zamerne oddelene od `minima.beh_12min_m`. Minima jsou
    oficialni armadni pozadavek, cilove tempo je realisticke rozvrzeni pro dany
    trenink - muze byt (a typicky je) nizsi.
    """
    minima  = day_data.get("minima", {})
    beh_m   = minima.get("beh_12min_m", 2500)
    lehsedy = minima.get("lehsedy_1min", "?")
    kliky   = minima.get("kliky_30s", "?")
    skok    = minima.get("skok_daleky_cm")

    cil_m = day_data.get("cil_beh_m")
    tgt, v1, v2, tempo_txt = "none", None, None, ""
    if cil_m:
        mps = cil_m / float(TEST_BEH_S)
        tgt = "pace"
        v1  = round(mps * (1 - TEST_TEMPO_PASMO), 4)
        v2  = round(mps * (1 + TEST_TEMPO_PASMO), 4)
        s_per_km = TEST_BEH_S / float(cil_m) * 1000
        tempo_txt = f" | drz tempo {int(s_per_km // 60)}:{int(s_per_km % 60):02d}/km na {cil_m} m"

    note = (
        f"12min beh - cil min. {beh_m} m | "
        f"max leh-sedy/min (min. {lehsedy}) | max kliky/30s (min. {kliky})"
        f"{f' | skok daleky (min. {skok} cm)' if skok else ''}"
        f"{tempo_txt}"
    )
    steps = [
        _step("warmup",   "time", 600, desc="Rozklusani"),
        _step("interval", "time", TEST_BEH_S, tgt, v1, v2, note),
        _step("cooldown", "time", 300, desc="Vyklus + protazeni"),
    ]
    return _envelope(name, "running", _renumber(steps),
                     description=day_data.get("popis", "Kontrolni test"))


# ── Strength builder ───────────────────────────────────────────────────────────
def _cvik_steps(c, pauza_faktor=1.0, den_interval=None):
    """Prevede jeden cvik na Garmin kroky.

    `den_interval` = {"zatez_s": 20, "pauza_s": 10} z urovne dne (tabata / kruhovy
    rezim). Pouzije se jen u cviku, ktery nema vlastni `cas_s`/`cas_min`/`opakovani`
    - driv takovy cvik spadl na lap.button, takze na hodinkach nebezel zadny odpocet.
    Stejny klic `interval` lze dat i na samotny cvik (napr. "10x (20 s / 10 s)"),
    pak prebije rezim dne.
    """
    key     = c.get("cvik", "")
    if key and key not in EXERCISE_MAP and key not in _CVIK_WARNED:
        _CVIK_WARNED.add(key)
        print(f"  [WARN] cvik '{key}' neni v EXERCISE_MAP - nahraje se jako OTHER/{key.upper()}")
    cat, ex = EXERCISE_MAP.get(key, ("OTHER", key.upper()))
    desc    = _cvik_label(c)   # Czech name + count/time
    pauza_s = max(1, int(_int_range(c.get("pauza_s", 60), default=60) * pauza_faktor))
    serie   = _int_range(c.get("serie", 1))
    steps   = []
    # 'interval' na cviku prebije rezim dne
    den_interval = c.get("interval") or den_interval

    # Sestupna pyramida: kazda serie ma vlastni dobu/pocet i vlastni pauzu.
    # Tyhle pauzy jsou soucast PREDPISU (ne odpocinek mezi seriemi), takze je
    # --pauza-faktor zamerne nekrati.
    sestupne = c.get("sestupne")
    if sestupne:
        nazev = CVIK_CS.get(key, key.replace("_", " ").capitalize())
        pozn  = c.get("popis")
        for i, s in enumerate(sestupne):
            if "opakovani" in s:
                lbl = s.get("popis") or f"{nazev} {s['opakovani']}x"
                steps.append(_step("interval", "reps", _int_range(s["opakovani"]),
                                   ex_cat=cat, ex_name=ex,
                                   desc=(lbl if s.get("popis") or not pozn else f"{lbl} - {pozn}")))
            else:
                secs = s.get("cas_s") or _int_range(s.get("cas_min", 1)) * 60
                lbl  = s.get("popis") or f"{nazev} {secs}s"
                steps.append(_step("interval", "time", secs,
                                   ex_cat=cat, ex_name=ex,
                                   desc=(lbl if s.get("popis") or not pozn else f"{lbl} - {pozn}")))
            # posledni serie zustava bez pauzy
            p = s.get("pauza_s")
            if p and i < len(sestupne) - 1:
                steps.append(_step("rest", "time", max(1, int(p)), desc=f"Pauza {int(p)}s"))
        return steps

    for i in range(serie):
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
        elif den_interval:
            # zatez + pauza z rezimu dne; pauza je soucast predpisu -> nekrati se.
            # Koncovou pauzu na konci kola odstrani build_strength_workout.
            zatez = den_interval.get("zatez_s") or _int_range(den_interval.get("zatez_min", 1)) * 60
            steps.append(_step("interval", "time", zatez,
                               ex_cat=cat, ex_name=ex, desc=desc))
            odpocinek = int(den_interval.get("pauza_s", 0))
            if odpocinek > 0:
                steps.append(_step("rest", "time", odpocinek, desc=f"Pauza {odpocinek}s"))
            continue
        else:
            rezim = c.get("rezim", desc)
            steps.append(_step("interval", "lap",
                               ex_cat=cat, ex_name=ex, desc=rezim))

        # bez pauzy po posledni serii - neni uz co odpocivat pred dalsim cvikem
        if pauza_s and pauza_s > 0 and i < serie - 1:
            steps.append(_step("rest", "time", pauza_s, desc="Pauza"))

    return steps


def build_strength_workout(day_data, name, pauza_faktor=1.0):
    cviky = day_data.get("cviky", [])
    if not cviky and day_data.get("bloky"):
        # Nektere silove dny nesou strukturu v 'bloky' (jako combo dny). Driv se
        # cetly jen 'cviky', takze takovy den nahral workout s NULOU kroku.
        cviky = day_data["bloky"]
    kola         = _int_range(day_data.get("kola", 1))
    pauza_kola   = max(1, int(day_data.get("pauza_mezi_koly_s", 120) * pauza_faktor))
    po_treninku  = day_data.get("po_treninku", [])
    den_interval = day_data.get("interval")

    round_steps = []
    for c in cviky:
        if c.get("krok") == "pauza":
            secs = int((c.get("cas_s") or _int_range(c.get("cas_min", 2)) * 60) * pauza_faktor)
            round_steps.append(_step("rest", "time", max(1, secs), desc="Pauza"))
        else:
            round_steps.extend(_cvik_steps(c, pauza_faktor, den_interval))

    # Kolo nesmi skoncit pauzou - u intervalovych rezimu (tabata) prijde pauza
    # po kazdem cviku vcetne posledniho, tak ji tady zahodime.
    while round_steps and round_steps[-1]["stepType"]["stepTypeKey"] in ("rest", "recovery"):
        round_steps.pop()

    if kola > 1 and round_steps:
        # posledni kolo bez navazujici pauzy - trenink pak rovnou konci
        grouped = [dict(s) for s in round_steps]
        grouped.append(_step("rest", "time", pauza_kola,
                             desc=f"Pauza mezi koly ({pauza_kola}s)"))
        top_steps = [_repeat_group(kola - 1, grouped)] + round_steps
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
            vzd_m = b.get("vzdalenost_m")
            raw   = b.get("vzdalenost_km")
            if vzd_m is None and raw:
                km = _int_range(raw) if isinstance(raw, str) and "-" in raw else float(raw)
                vzd_m = km * 1000
            # beh v combo bloku muze byt i na cas (napr. "30 s beh na 100 %") -
            # driv se takovy krok tise degradoval na lap.button
            secs = b.get("cas_s") or (_int_range(b["cas_min"]) * 60 if "cas_min" in b else None)
            cil = b.get("cil")
            tgt, v1, v2, zone, tgt_suffix = _resolve_step_target(cil, vzd_m)
            label = (b.get("popis", "Beh") + tgt_suffix) if cil else b.get("popis", "Beh")
            if vzd_m:
                round_steps.append(_step("interval", "dist", int(vzd_m),
                                         tgt=tgt, v1=v1, v2=v2, desc=label, zone=zone))
            elif secs:
                round_steps.append(_step("interval", "time", secs,
                                         tgt=tgt, v1=v1, v2=v2, desc=label, zone=zone))
            else:
                round_steps.append(_step("interval", "lap",
                                         tgt=tgt, v1=v1, v2=v2, desc=label, zone=zone))
        else:
            # blok bez cviku i behu = jen text; na hodinkach z nej nemuze byt
            # nic jineho nez otevreny krok na lap.button
            if not b.get("lint_ok"):
                print(f"  [WARN] blok bez struktury (jen popis): {b.get('popis', '')!r}"
                      f" - nahraje se jako otevreny krok na lap")
            round_steps.append(_step("interval", "lap", desc=b.get("popis", "")))

    # kolo nesmi skoncit pauzou
    while round_steps and round_steps[-1]["stepType"]["stepTypeKey"] in ("rest", "recovery"):
        round_steps.pop()

    if kola > 1 and round_steps:
        # posledni kolo bez navazujici pauzy - trenink pak rovnou konci
        grouped = [dict(s) for s in round_steps]
        grouped.append(_step("rest", "time", pauza_kola, desc="Pauza mezi koly"))
        top_steps = [_repeat_group(kola - 1, grouped)] + round_steps
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


# ── Overlay: vlastni treninky a upravy MIMO armadni plan ───────────────────────
# Armadni plany (plan/vtp-plan-*.yaml) zustavaji cistym prepisem zdroje, aby se
# podle nich dalo kdykoli zacit znovu od tydne 1 a aby se daly overit proti
# originalu. Vlastni realita (pravidelna hazena ve ctvrtek, presuny dnu kolem ni)
# zije v samostatnem souboru a slucuje se az za behu.

VLASTNI_FILE = PLAN_DIR / "vlastni-treninky.yaml"
_VOLNO = {"typ": "volno"}


def _je_volny(day_data):
    return not day_data or day_data.get("typ", "volno") in ("volno", "aktivni_odpocinek")


def load_overlay(path=None, vypnuto=False):
    """Nacte overlay s vlastnimi treninky. Vraci {} kdyz nic neni k dispozici.

    Bez `--vlastni` se bere konvencni cesta plan/vlastni-treninky.yaml, a kdyz
    neexistuje, tise se preskoci (cista instalace / CI se chovaji jako driv).
    Explicitne zadana cesta, ktera neexistuje, je chyba.
    """
    if vypnuto:
        return {}
    if path:
        p = Path(path)
        if not p.exists():
            print(f"CHYBA: overlay soubor {p} neexistuje.")
            sys.exit(1)
    else:
        p = VLASTNI_FILE
        if not p.exists():
            return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def apply_overlay(plan, overlay):
    """Slouci armadni plan s vlastnimi upravami.

    Vraci (efektivni_plan, osirele_nazvy). Presunuty i zruseny den se v
    efektivnim planu stane 'volno' - diky tomu nepotrebuje zadny builder,
    ICS ani dispatcher novy typ dne. `osirele_nazvy` jsou workouty, ktere pod
    starym jmenem zustaly na Garminu (jmeno se odvozuje ze dne, takze presun
    ST -> PO zmeni VTP-T10-ST-SIL na VTP-T10-PO-SIL) a je treba je smazat.
    """
    if not overlay or not overlay.get("zmeny"):
        return plan, []

    plan = copy.deepcopy(plan)
    osirele = []
    tydny = {t.get("tyden"): t for t in plan.get("tydny", [])}

    for z in overlay.get("zmeny") or []:
        tyden = z.get("tyden")
        tdata = tydny.get(tyden)
        if not tdata:
            print(f"  [WARN] overlay: tyden {tyden} v planu neexistuje")
            continue
        dny = tdata.setdefault("dny", {})

        prohodit = z.get("prohodit")
        if prohodit and len(prohodit) == 2:
            a, b = prohodit
            da, db = dny.get(a), dny.get(b)
            dny[a], dny[b] = db, da
            for den, d in ((a, da), (b, db)):
                if not _je_volny(d):
                    osirele.append(_vtp_name(tyden, den, d.get("typ")))

        for zdroj, cil in (z.get("presun") or {}).items():
            d = dny.get(zdroj)
            if _je_volny(d):
                print(f"  [WARN] overlay T{tyden}: v '{zdroj}' neni co presouvat")
                continue
            if not _je_volny(dny.get(cil)):
                print(f"  [WARN] overlay T{tyden}: cilovy den '{cil}' neni volny"
                      f" - '{zdroj}' zustava na miste")
                continue
            dny[cil] = d
            dny[zdroj] = dict(_VOLNO)
            osirele.append(_vtp_name(tyden, zdroj, d.get("typ")))

        for den in z.get("zrusit") or []:
            d = dny.get(den)
            if _je_volny(d):
                continue
            dny[den] = dict(_VOLNO)
            osirele.append(_vtp_name(tyden, den, d.get("typ")))

        for den, d in (z.get("pridat") or {}).items():
            if not _je_volny(dny.get(den)):
                print(f"  [WARN] overlay T{tyden}: '{den}' neni volny"
                      f" - vlastni trenink se nepridava")
                continue
            dny[den] = d

    # Jmeno, ktere v efektivnim planu dal existuje, osirele neni (po prohozeni
    # dvou dnu se cast jmen jen vymeni).
    aktualni = set()
    for t in plan.get("tydny", []):
        for den, d in (t.get("dny") or {}).items():
            if not _je_volny(d):
                aktualni.add(_vtp_name(t["tyden"], den, d.get("typ")))

    return plan, [n for n in dict.fromkeys(osirele) if n not in aktualni]


def vlastni_ics_events(overlay, start_date, end_date):
    """Pravidelne vlastni treninky (hazena) jako udalosti do kalendare.

    Zamerne se NEnahravaji na Garmin - hodinkam by prazdny workout nepomohl.
    Diky tomu, ze se generuji z datoveho rozsahu (a ne z tydnu planu), funguje
    to i v --ics-garmin, kde autoritou dat je Garmin kalendar a cislo tydne 1
    se nikde nepocita.
    """
    out = []
    for e in overlay.get("opakovane") or []:
        den = e.get("den")
        if den not in DEN_DELTA:
            print(f"  [WARN] overlay: neznamy den '{den}' u vlastniho treninku")
            continue
        d = start_date
        while d <= end_date:
            if d.weekday() == DEN_DELTA[den]:
                out.append({
                    "date":     d,
                    "klic":     e.get("klic", "vlastni"),
                    "nazev":    e.get("nazev") or e.get("klic", "Vlastni trenink"),
                    "popis":    e.get("popis", ""),
                    "delka_min": e.get("delka_min", 60),
                })
            d += datetime.timedelta(days=1)
    return out


# ── Garmin Connect I/O ─────────────────────────────────────────────────────────
def _connect(email=None, password=None, no_save=False):
    """Připojí se ke Garmin Connect. Token se uloží do TOKEN_DIR (pokud není --no-save).

    MFA se řeší přes `prompt_mfa` callback knihovny - ta si o kód řekne sama,
    když ho Garmin vyžádá. (Dřív se tu testovala návratová hodnota `login()`,
    ale ta MFA nikdy nesignalizuje: bez `prompt_mfa`/`return_on_mfa` knihovna
    rovnou vyhodí GarminConnectAuthenticationError.)
    """
    Garmin = _import_garmin()
    api = Garmin(
        email or None,
        password or None,
        prompt_mfa=lambda: input("Zadej MFA kód z Garmin / e-mailu: ").strip(),
    )

    try:
        if no_save:
            api.login()
        else:
            TOKEN_DIR.mkdir(parents=True, exist_ok=True)
            api.login(tokenstore=str(TOKEN_DIR))
    except Exception as e:
        print(f"\nCHYBA prihlaseni do Garmin Connect: {e}")
        if not (email and password):
            print("Ulozeny token je asi prosly - spust znovu s --email a --password.")
        sys.exit(1)

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


# ── Lint: kontrola prevodu YAML -> Garmin kroky ────────────────────────────────
# Smysl: kazdou tichou degradaci prevodu odhalit OFFLINE, drive nez se workout
# nahraje a clovek na to prijde az na hodinkach pri treninku. Presne tyhle chyby
# se takhle nasly: pauza v pyramide v metrech misto sekund, tabata bez odpoctu,
# silovy den s 'bloky' misto 'cviky' (= workout s nulou kroku).

_LINT_CISLO_RE  = re.compile(r"\d+\s*(?:x|s\b|sec|min)", re.IGNORECASE)
_LINT_ROZSAH_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*-\s*\d+(?:[.,]\d+)?\s*$")


def _lint_flat(steps):
    """Rozbali repeat grupy - vrati plochy seznam vykonnych kroku."""
    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        if s.get("type") == "RepeatGroupDTO":
            out.extend(_lint_flat(s.get("workoutSteps")))
        else:
            out.append(s)
    return out


def _lint_polozky(day_data):
    """Vsechny polozky cviku/bloku/kroku dne (i po_treninku, vnorene faze
    a vnorene 'opakovat' bloky u behu)."""
    out = []
    for klic in ("cviky", "bloky", "po_treninku"):
        for it in day_data.get(klic) or []:
            if isinstance(it, dict):
                out.append(it)

    def _walk_kroky(kroky):
        for k in kroky or []:
            if not isinstance(k, dict):
                continue
            out.append(k)
            if k.get("krok") == "opakovat":
                _walk_kroky(k.get("obsah"))

    _walk_kroky(day_data.get("kroky"))
    return out


class _TrackedDict(dict):
    """Pouziva se jen uvnitr lint_plan() - zaznamena, ktere klice byly
    precteny (__getitem__/get/__contains__) pri stavbe workoutu, aby lint
    odhalil klic, ktery YAML nese, ale zadny builder ho nikdy nenacte."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._touched = set()

    def __getitem__(self, key):
        self._touched.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._touched.add(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._touched.add(key)
        return super().__contains__(key)


def _track_wrap(obj):
    """Rekurzivne obali dicty do _TrackedDict; listy prochazi, scalary necha."""
    if isinstance(obj, dict):
        return _TrackedDict((k, _track_wrap(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return [_track_wrap(v) for v in obj]
    return obj


# Klice, ktere jsou zamerne jen lidska dokumentace duplikujici uz strukturovana
# data (podtyp/rezim), nebo je cte jen samotny lint a nikdy zadny builder
# (lint_ok) - bez teto vyjimky by kazda existujici lint_ok anotace byla sama
# nahlasena jako "nikdy neprectena".
_LINT_IGNOROVANE_KLICE = {"podtyp", "rezim", "lint_ok"}


def _track_unused(obj, cesta=""):
    """Projde wrapnuty strom a vrati [(cesta, hodnota), ...] pro klice, ktere
    pri stavbe workoutu nebyly precteny. Pokud klic byl precten, rekurze
    pokracuje do jeho hodnoty; pokud ne, nahlasi se jen on sam."""
    out = []
    if isinstance(obj, _TrackedDict):
        for k, v in obj.items():
            klic_cesta = f"{cesta}.{k}" if cesta else str(k)
            if k not in obj._touched:
                if k not in _LINT_IGNOROVANE_KLICE:
                    out.append((klic_cesta, v))
            else:
                out.extend(_track_unused(v, klic_cesta))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_track_unused(v, f"{cesta}[{i}]"))
    return out


def _lint_rozsahy(obj, cesta=""):
    """Najde vsechny hodnoty typu "3-5" (rozsah) - resolvuji se na MAXIMUM."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_lint_rozsahy(v, f"{cesta}.{k}" if cesta else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_lint_rozsahy(v, f"{cesta}[{i}]"))
    elif isinstance(obj, str) and _LINT_ROZSAH_RE.match(obj):
        out.append((cesta, obj))
    return out


def lint_plan(plan_name="muzi", pauza_faktor=1.0, vlastni=None, bez_vlastnich=False):
    """Projde vsechny dny planu, postavi workouty realnymi buildery a nahlasi
    kroky, ze kterych by na hodinkach vznikla nesmyslna nebo prazdna jednotka.
    Kontrola je typove agnosticka - bezi stejne pro beh/silovy/kombinace/test,
    vcetne generickeho nalezu "tenhle klic z YAML se pri stavbe nikdy necetl"
    (viz _TrackedDict/_track_unused), ktery odhali tiche zahozeni hodnoty bez
    ohledu na typ dne.

    Bezi OFFLINE (bez prihlaseni), takze se da poustet i v CI.
    Polozku, ktera ma byt zamerne otevrena (napr. "max opakovani", proklus
    vlastnim tempem), oznac v YAML klicem `lint_ok: "duvod"` - lint ji pak
    nenahlasi.
    """
    plan_file = PLAN_DIR / f"vtp-plan-{plan_name}.yaml"
    if not plan_file.exists():
        print(f"CHYBA: soubor {plan_file} neexistuje.")
        sys.exit(1)
    with open(plan_file, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    # kontroluje se EFEKTIVNI plan - vlastni pridane dny musi projit taky
    overlay = load_overlay(vlastni, bez_vlastnich)
    plan, _ = apply_overlay(plan, overlay)

    print(f"Kontrola prevodu: {plan_file.name} (pauza_faktor {pauza_faktor})"
          f"{' + overlay' if overlay else ''}\n")
    chyby, infa, dnu = [], [], 0

    for tyden_data in plan.get("tydny", []):
        tyden = tyden_data["tyden"]
        for den_key, day_data in (tyden_data.get("dny") or {}).items():
            if not day_data:
                continue
            typ = day_data.get("typ", "volno")
            if typ in ("volno", "aktivni_odpocinek", "hazena"):
                continue
            dnu += 1
            kde  = f"T{tyden:02d} {DEN_CODE[den_key]}"
            name = _vtp_name(tyden, den_key, typ)

            # klice, ktere builder pro dany typ vubec necte
            if typ == "silovy" and day_data.get("bloky") and not day_data.get("cviky"):
                infa.append(f"{kde} {name}: pouziva 'bloky' na silovem dni"
                            f" - cte se jako 'cviky' (fallback)")
            if typ == "kombinace" and day_data.get("cviky") and not day_data.get("bloky"):
                chyby.append(f"{kde} {name}: 'cviky' na combo dni se NECTE - patri do 'bloky'")

            # neznamy cvik
            for it in _lint_polozky(day_data):
                k = it.get("cvik")
                if k and k not in EXERCISE_MAP:
                    chyby.append(f"{kde} {name}: cvik '{k}' neni v EXERCISE_MAP")

            day_data_wrapped = _track_wrap(day_data)
            workout = day_to_workout(day_data_wrapped, name, pauza_faktor)
            if workout is None:
                chyby.append(f"{kde} {name}: typ '{typ}' nevyrobil zadny workout")
                continue

            # generický nález: klic z YAML, ktery pri stavbe tohoto dne
            # (bez ohledu na typ) zadny builder nikdy neprecetl
            for cesta, hodnota in _track_unused(day_data_wrapped):
                chyby.append(f"{kde} {name}: klic '{cesta}' se pri stavbe tohoto"
                             f" dne (typ '{typ}') nikdy necte - hodnota {hodnota!r}"
                             f" se ztrati")

            steps = _lint_flat(workout["workoutSegments"][0]["workoutSteps"])
            if not steps:
                chyby.append(f"{kde} {name}: workout ma NULA kroku"
                             f" - na hodinkach bude prazdny")
                continue

            # polozky zamerne otevrene (lint_ok) pozname podle popisku kroku
            povoleno = set()
            for it in _lint_polozky(day_data):
                if it.get("lint_ok"):
                    povoleno.add(_cvik_label(it))

            for i, s in enumerate(steps):
                konec = (s.get("endCondition") or {}).get("conditionTypeKey")
                hod   = s.get("endConditionValue")
                popis = s.get("description") or ""

                if konec == "lap.button" and popis not in povoleno:
                    cisla = _LINT_CISLO_RE.findall(popis)
                    detail = (f" (v popisu jsou cisla {cisla} - nedostala se do kroku)"
                              if cisla else "")
                    chyby.append(f"{kde} {name}: krok konci na tlacitko (lap) bez"
                                 f" odpoctu i poctu: {popis!r}{detail}")

                if konec in ("time", "distance") and not hod:
                    chyby.append(f"{kde} {name}: krok {popis!r} ma end condition"
                                 f" '{konec}' bez hodnoty - Garmin ho odmitne")

                # regresni pojistka na pyramidovy bug: pauza na CAS s hodnotou
                # rovnou vzdalenosti predchazejiciho useku
                if i > 0 and konec == "time":
                    p = steps[i - 1]
                    p_konec = (p.get("endCondition") or {}).get("conditionTypeKey")
                    if (p_konec == "distance"
                            and s["stepType"]["stepTypeKey"] in ("rest", "recovery")
                            and hod and hod == p.get("endConditionValue")):
                        chyby.append(f"{kde} {name}: pauza {int(hod)} s ma stejnou"
                                     f" hodnotu jako predchazejici usek {int(hod)} m"
                                     f" - zamena metru za sekundy?")

            for cesta, raw in _lint_rozsahy(day_data):
                infa.append(f"{kde} {name}: {cesta} = {raw!r} -> pouzije se MAX"
                            f" {_int_range(raw)}")

    for m in infa:
        print(f"  INFO {m}")
    if infa:
        print()
    for m in chyby:
        print(f"  ERR  {m}")

    print(f"\nVysledek: {dnu} dnu zkontrolovano, {len(chyby)} nalezu"
          f" ({len(infa)} informativnich).")
    return len(chyby)


# ── Stažení reálného výkonu z Garminu ──────────────────────────────────────────
# Garmin k nazvu aktivity casto predradi lokalitu ("Praha - VTP-T04-UT-BEH"),
# takze presna shoda nazvu workoutu nefunguje - VTP kod hledame kdekoli v textu.
_VTP_RE = re.compile(r"VTP-T\d{2}-[A-Z]{2}-[A-Z]+")


def _vtp_name_in(text):
    """Vytáhne z názvu aktivity VTP kód workoutu, nebo None."""
    m = _VTP_RE.search(str(text or ""))
    return m.group(0) if m else None


def _pick(obj, *keys, default=None):
    """Vrátí první neprázdný klíč z dictu. Garmin JSON má nekonzistentní názvy
    polí mezi endpointy, takže zkoušíme víc variant."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if obj.get(k) is not None:
            return obj[k]
    return default


def _num(val, digits=1):
    """Zaokrouhlí číslo (šetří velikost JSONu); nečíslo vrátí beze změny."""
    if isinstance(val, (int, float)):
        return round(val, digits)
    return val


def _api_try(label, fn, *args, **kwargs):
    """Zavolá Garmin API; při chybě vypíše [WARN] a vrátí None.

    Garmin API je neoficiální a jednotlivé endpointy občas chybí data nebo
    vrátí 4xx (ty knihovna neretryuje) - jeden neúspěch nesmí shodit celý sběr.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"  [WARN] {label}: {e}")
        return None


def _trim_laps(splits):
    """Z /activity/{id}/splits ponechá jen pole nutná k posouzení tempa a tepu
    po jednotlivých úsecích (kvůli velikosti JSONu zahazujeme zbytek)."""
    if not isinstance(splits, dict):
        return []
    raw = splits.get("lapDTOs") or splits.get("splits") or []
    out = []
    for i, lap in enumerate(raw, 1):
        if not isinstance(lap, dict):
            continue
        out.append({
            "i":             i,
            "vzdalenost_m":  _num(_pick(lap, "distance")),
            "cas_s":         _num(_pick(lap, "duration", "elapsedDuration")),
            "tempo_mps":     _num(_pick(lap, "averageSpeed"), 3),
            "tempo_max_mps": _num(_pick(lap, "maxSpeed"), 3),
            "hr_avg":        _pick(lap, "averageHR"),
            "hr_max":        _pick(lap, "maxHR"),
        })
    return out


def _trim_sets(sets_raw):
    """Z /activity/{id}/exerciseSets ponechá cvik + opakování/čas per série."""
    if not isinstance(sets_raw, dict):
        return []
    out = []
    for s in sets_raw.get("exerciseSets") or []:
        if not isinstance(s, dict):
            continue
        exercises = s.get("exercises")
        ex = exercises[0] if isinstance(exercises, list) and exercises else {}
        out.append({
            "typ":       str(s.get("setType") or "").upper(),   # ACTIVE / REST
            "cvik":      _pick(ex, "name", "category"),
            "kategorie": _pick(ex, "category"),
            "opakovani": s.get("repetitionCount"),
            "cas_s":     _num(s.get("duration")),
        })
    return out


def _trim_plan_steps(steps):
    """Z plánovaných Garmin kroků ponechá cíl + délku, rekurzivně i v repeat
    grupách. Slouží k porovnání 'co bylo naplánováno' vs. 'co se odběhlo'."""
    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        if s.get("type") == "RepeatGroupDTO":
            out.append({
                "opakovat": s.get("numberOfIterations"),
                "kroky":    _trim_plan_steps(s.get("workoutSteps")),
            })
            continue
        out.append({
            "krok":          (s.get("stepType")   or {}).get("stepTypeKey"),
            "konec":         (s.get("endCondition") or {}).get("conditionTypeKey"),
            "konec_hodnota": _num(s.get("endConditionValue")),
            "cil":           (s.get("targetType") or {}).get("workoutTargetTypeKey"),
            "cil_od":        _num(s.get("targetValueOne"), 3),
            "cil_do":        _num(s.get("targetValueTwo"), 3),
            "zona":          s.get("zoneNumber"),
            "popis":         s.get("description"),
        })
    return out


def fetch_garmin_vykon(api, output_file="vykon-garmin.json", plan_name="muzi",
                       pauza_faktor=1.0, start_override=None, max_hr=None,
                       vlastni=None, bez_vlastnich=False):
    """Stáhne REÁLNÝ výkon + kondiční data z Garmin Connectu do jednoho JSONu.

    Výstup slouží k offline analýze: ke každé odběhnuté aktivitě se podle názvu
    (VTP-T08-CT-BEH) dohledá plánovaný den v YAML a k němu se přiloží plánované
    kroky s dořešenými cíli - tempo je v obou případech v m/s, takže jde
    plánované a skutečné srovnat přímo.

    pauza_faktor se propisuje do plánovaných kroků, aby pauzy odpovídaly tomu,
    co uživatel reálně nahrál na hodinky (ne tomu, co je surově v YAML).
    """
    plan_file = PLAN_DIR / f"vtp-plan-{plan_name}.yaml"
    if not plan_file.exists():
        print(f"CHYBA: soubor {plan_file} neexistuje.")
        sys.exit(1)
    with open(plan_file, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    # efektivni plan, aby presunute dny nasly svuj planovany obsah podle nazvu
    plan, _ = apply_overlay(plan, load_overlay(vlastni, bez_vlastnich))
    day_index = _index_plan_by_name(plan)

    today = datetime.date.today()
    if start_override:
        try:
            start = datetime.date.fromisoformat(start_override)
        except ValueError:
            print(f"CHYBA: --start '{start_override}' neni platne datum (YYYY-MM-DD).")
            sys.exit(1)
    else:
        # bez --start bereme generozni okno dozadu, at pokryjeme cely plan
        start = today - datetime.timedelta(days=140)

    print(f"Obdobi: {start.isoformat()} .. {today.isoformat()}")

    # HR zóny z Connectu -> plánované % SFmax se dořeší na reálné bpm/zóny
    _load_hr_state(api, max_hr_override=max_hr)

    result = {
        "meta": {
            "stazeno":       today.isoformat(),
            "obdobi_od":     start.isoformat(),
            "obdobi_do":     today.isoformat(),
            "plan":          plan_name,
            "pauza_faktor":  pauza_faktor,
            "max_hr":        MAX_HR,
            "hr_zony":       HR_ZONES,
        },
        "profil":     {},
        "vaha":       [],
        "kondice":    {},
        "naplanovano": [],
        "treninky":   [],
    }

    # ── Profil, váha ───────────────────────────────────────────────────────────
    print("Stahuji profil a vahu...")
    prof = _api_try("profil", api.get_user_profile)
    if isinstance(prof, dict):
        result["profil"] = {
            k: prof.get(k) for k in
            ("weight", "height", "vo2MaxRunning", "vo2MaxCycling", "lactateThresholdSpeed",
             "lactateThresholdHeartRate", "restingHeartRate", "gender", "birthDate")
            if prof.get(k) is not None
        }

    body = _api_try("vaha", api.get_body_composition, start.isoformat(), today.isoformat())
    if isinstance(body, dict):
        result["kondice"]["vaha_prumer"] = body.get("totalAverage")
        for w in body.get("dateWeightList") or []:
            if isinstance(w, dict):
                result["vaha"].append({
                    "datum":     _pick(w, "calendarDate", "date"),
                    "vaha_g":    _pick(w, "weight"),
                    "tuk_pct":   _pick(w, "bodyFat"),
                })

    # ── Kondiční metriky: týdenní vzorky + rozsahové/aktuální ─────────────────
    sample_days = []
    d = start
    while d <= today:
        sample_days.append(d)
        d += datetime.timedelta(days=7)
    if not sample_days or sample_days[-1] != today:
        sample_days.append(today)

    print(f"Stahuji kondicni metriky ({len(sample_days)} tydennich vzorku)...")
    vo2, tstatus, fage, hrv, rhr = [], [], [], [], []
    for d in sample_days:
        ds = d.isoformat()
        m = _api_try(f"vo2max {ds}", api.get_max_metrics, ds)
        if m:
            entry = m[0] if isinstance(m, list) and m else m
            gen = (entry or {}).get("generic") or {}
            vo2.append({"datum": ds, "vo2max": gen.get("vo2MaxPreciseValue") or gen.get("vo2MaxValue")})
        ts = _api_try(f"training status {ds}", api.get_training_status, ds)
        if isinstance(ts, dict):
            tstatus.append({"datum": ds, "stav": _pick(ts, "trainingStatus", "trainingStatusKey")})
        fa = _api_try(f"fitness age {ds}", api.get_fitnessage_data, ds)
        if isinstance(fa, dict):
            fage.append({"datum": ds, "fitness_age": _pick(fa, "chronologicalAge", "achievableFitnessAge",
                                                           "fitnessAge")})
        hv = _api_try(f"hrv {ds}", api.get_hrv_data, ds)
        if isinstance(hv, dict):
            summ = hv.get("hrvSummary") or {}
            hrv.append({"datum": ds, "hrv": summ.get("weeklyAvg"), "stav": summ.get("status")})
        rh = _api_try(f"rhr {ds}", api.get_rhr_day, ds)
        if isinstance(rh, dict):
            metrics = rh.get("allMetrics", {}).get("metricsMap", {}) if isinstance(rh.get("allMetrics"), dict) else {}
            vals = metrics.get("WELLNESS_RESTING_HEART_RATE") or []
            rhr.append({"datum": ds, "rhr": (vals[-1].get("value") if vals else None)})

    result["kondice"].update({
        "vo2max":            vo2,
        "training_status":   tstatus,
        "fitness_age":       fage,
        "hrv":               hrv,
        "rhr":               rhr,
        "endurance_score":   _api_try("endurance score", api.get_endurance_score,
                                      start.isoformat(), today.isoformat()),
        "running_tolerance": _api_try("running tolerance", api.get_running_tolerance,
                                      start.isoformat(), today.isoformat()),
        "race_predictions":  _api_try("race predictions", api.get_race_predictions),
        "lactate_threshold": _api_try("lactate threshold", api.get_lactate_threshold, latest=True),
        "personal_records":  _api_try("osobni rekordy", api.get_personal_record),
        "training_readiness": _api_try("training readiness", api.get_training_readiness,
                                       today.isoformat()),
    })

    # ── Naplánované VTP tréninky z kalendáře (pro odhalení vynechaných) ────────
    print("Stahuji naplanovane VTP treninky z kalendare...")
    for ev in _fetch_garmin_vtp_events(api, start, today):
        result["naplanovano"].append({"datum": ev["date"].isoformat(), "nazev": ev["name"]})

    # ── Odběhnuté aktivity ─────────────────────────────────────────────────────
    print("Stahuji odbehnute aktivity...")
    acts = _api_try("seznam aktivit", api.get_activities_by_date,
                    start.isoformat(), today.isoformat()) or []

    # Minulé aktivity se už nemění -> detaily z předchozího běhu recyklujeme
    # (šetří API volání a umožní dokončit sběr přerušený rate-limitem).
    cache = {}
    out_path = Path(output_file)
    if out_path.exists():
        try:
            with open(out_path, encoding="utf-8") as f:
                for t in (json.load(f).get("treninky") or []):
                    if t.get("activity_id") is not None and (t.get("useky") or t.get("serie")):
                        cache[t["activity_id"]] = t
        except Exception as e:
            print(f"  [WARN] predchozi {out_path.name} nelze precist: {e}")
    if cache:
        print(f"  z predchoziho behu recykluji detaily {len(cache)} aktivit")

    print(f"  nalezeno {len(acts)} aktivit, stahuji detaily...")

    for a in acts:
        if not isinstance(a, dict):
            continue
        act_id = a.get("activityId")
        name   = str(a.get("activityName") or "").strip()
        typ_key = ((a.get("activityType") or {}).get("typeKey") or "").lower()
        vtp     = _vtp_name_in(name)
        matched = day_index.get(vtp) if vtp else None

        rec = {
            "activity_id": act_id,
            "datum":       (a.get("startTimeLocal") or "")[:10],
            "nazev":       name,
            "vtp_nazev":   vtp,
            "typ_garmin":  typ_key,
            "souhrn": {
                "vzdalenost_m": _num(a.get("distance")),
                "cas_s":        _num(a.get("duration")),
                "cas_pohyb_s":  _num(a.get("movingDuration")),
                "tempo_mps":    _num(a.get("averageSpeed"), 3),
                "hr_avg":       a.get("averageHR"),
                "hr_max":       a.get("maxHR"),
                "kalorie":      a.get("calories"),
                "te_aerobni":   a.get("aerobicTrainingEffect"),
                "te_anaerobni": a.get("anaerobicTrainingEffect"),
            },
        }

        if matched:
            rec["plan"] = {
                "tyden": matched["tyden"],
                "den":   matched["den_code"],
                "typ":   matched["typ"],
            }
            # kontrolni_test nema realne krokove cile - autoritou jsou minima
            if matched["typ"] == "kontrolni_test":
                rec["plan"]["minima"] = matched["day_data"].get("minima")
            else:
                workout = _api_try(
                    f"plan kroky {name}",
                    day_to_workout, matched["day_data"], name, pauza_faktor,
                )
                if isinstance(workout, dict):
                    segs = workout.get("workoutSegments") or [{}]
                    rec["plan"]["kroky"] = _trim_plan_steps(segs[0].get("workoutSteps"))
        else:
            rec["plan"] = None   # neodpovida zadnemu VTP dni (mimo plan / bez hodinek)

        cached = cache.get(act_id)
        if cached:
            # detaily z predchoziho behu (aktivita v minulosti se uz nemeni)
            for k in ("hr_zony", "useky", "serie"):
                if cached.get(k) is not None:
                    rec[k] = cached[k]
        elif act_id is not None:
            try:
                zones = _api_try(f"hr zony {act_id}", api.get_activity_hr_in_timezones, act_id)
                if isinstance(zones, list):
                    rec["hr_zony"] = [
                        {"zona": z.get("zoneNumber"), "s": _num(z.get("secsInZone"))}
                        for z in zones if isinstance(z, dict)
                    ]
                if "strength" in typ_key:
                    rec["serie"] = _trim_sets(
                        _api_try(f"serie {act_id}", api.get_activity_exercise_sets, act_id))
                else:
                    rec["useky"] = _trim_laps(
                        _api_try(f"useky {act_id}", api.get_activity_splits, act_id))
                time.sleep(0.3)   # knihovna netlumi 429 sama, radeji nespamovat
            except Exception as e:
                # 429 apod. -> nedokoncene detaily nesmi zahodit uz nasbirana data
                print(f"  [WARN] detaily {act_id} preruseny ({e}); ukladam co mam")
                result["treninky"].append(rec)
                break

        result["treninky"].append(rec)

    # ── Vynechané tréninky: naplánováno v kalendáři, ale nic se neodběhlo ─────
    hotovo = {t["vtp_nazev"] for t in result["treninky"] if t.get("vtp_nazev")}
    result["nesplneno"] = [
        ev for ev in result["naplanovano"]
        if ev["nazev"] not in hotovo and ev["datum"] < today.isoformat()
    ]

    result["meta"]["poznamky"] = (
        "pauza_faktor ovlivnuje jen silovy/kombinace dny - u typu 'beh' je pauza v"
        " plan.kroky presne ta, ktera byla na hodinkach."
        " Leh-sedy a kliky z kontrolniho testu Garmin strukturovane neuklada,"
        " z testu je pouzitelna jen vzdalenost 12min behu."
        " treninky[].plan == null znamena aktivitu mimo VTP plan (nebo bez hodinek)."
    )

    # ── Zápis ──────────────────────────────────────────────────────────────────
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    matched_n = sum(1 for t in result["treninky"] if t.get("plan"))
    print(f"\nUlozeno {len(result['treninky'])} treninku "
          f"({matched_n} naparovanych na plan), {len(result['nesplneno'])} vynechanych, "
          f"{len(result['vaha'])} zaznamu vahy "
          f"-> {out_path.resolve()} ({size_kb:.0f} kB)")
    if not result["treninky"]:
        print("[WARN] Zadne aktivity - zkontroluj obdobi (--start) nebo prihlaseni.")
    elif not matched_n:
        print("[WARN] Zadna aktivita se nenaparovala na plan podle nazvu "
              "(VTP-T*) - analyza planovane vs. skutecne nebude mozna.")


def push_plan(plan_name="muzi", weeks_limit=None, dry_run=False,
              email=None, password=None, no_save=False, start_override=None,
              pauza_faktor=1.0, from_week=1, max_hr=None,
              vlastni=None, bez_vlastnich=False):
    plan_file = PLAN_DIR / f"vtp-plan-{plan_name}.yaml"
    if not plan_file.exists():
        print(f"CHYBA: soubor {plan_file} neexistuje.")
        sys.exit(1)
    with open(plan_file, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    overlay = load_overlay(vlastni, bez_vlastnich)
    plan, osirele = apply_overlay(plan, overlay)
    if osirele:
        print(f"Overlay: {len(osirele)} workoutu zmenilo den"
              f" - stare nazvy se smazou ({', '.join(osirele)})")

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

    # Uklid po overlay: workout, ktery se presunul na jiny den, zustal na Garminu
    # pod starym nazvem a naplanoval by se navek. Maze se bez ohledu na
    # --od-tydne, protoze nejde o nahravani, ale o odstraneni duchu.
    for stary in osirele:
        if dry_run:
            if stary in existing_by_name:
                print(f"  [DRY] smazal bych osirely workout {stary}")
            continue
        wid = existing_by_name.pop(stary, None)
        if wid:
            try:
                api.delete_workout(wid)
                print(f"  smazan osirely workout {stary} (presun/zruseni v overlay)")
            except Exception as e:
                print(f"  [WARN] {stary}: smazani selhalo: {e}")

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
            name    = _vtp_name(tyden, den_key, typ)
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


def _parse_time_arg(start_time):
    """Převede --time 'HH:MM' na datetime.time (None = celodenní události)."""
    if not start_time:
        return None
    h, m = map(int, start_time.split(":"))
    return datetime.time(h, m)


def _ics_vevent(uid, summary, date, desc=None, t=None, duration_min=45):
    """Sestaví řádky jednoho VEVENT bloku (list[str], řádky ukončené \\r\\n).

    Bez `t` celodenní událost (VALUE=DATE, DTEND = den+1 dle RFC 5545),
    s `t` časovaná událost ve floating local time, DTEND = start + duration_min.
    """
    lines = []
    lines.append("BEGIN:VEVENT\r\n")
    lines.append(_ics_fold(f"UID:{uid}"))
    if t:
        dt_start = datetime.datetime.combine(date, t)
        dt_end   = dt_start + datetime.timedelta(minutes=duration_min)
        lines.append(_ics_fold(f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%S')}"))
        lines.append(_ics_fold(f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}"))
    else:
        dtend = date + datetime.timedelta(days=1)
        lines.append(_ics_fold(f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}"))
        lines.append(_ics_fold(f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}"))
    lines.append(_ics_fold(f"SUMMARY:{summary}"))
    if desc:
        lines.append(_ics_fold(f"DESCRIPTION:{_ics_escape(desc)}"))
    lines.append("END:VEVENT\r\n")
    return lines


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
        # combo dny nesou cviky v 'bloky', ne v 'cviky' - driv byl popis prazdny
        if day_data.get("cviky") or day_data.get("bloky"):
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
                 out_file="vtp-plan.ics", start_time=None,
                 vlastni=None, bez_vlastnich=False):
    """Vygeneruje ICS soubor pro import do Google Kalendáře."""
    plan_file = PLAN_DIR / f"vtp-plan-{plan_name}.yaml"
    if not plan_file.exists():
        print(f"CHYBA: soubor {plan_file} neexistuje.")
        sys.exit(1)
    with open(plan_file, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    overlay = load_overlay(vlastni, bez_vlastnich)
    plan, _ = apply_overlay(plan, overlay)

    if start_override:
        start_date = datetime.date.fromisoformat(start_override)
    else:
        start_str = plan["meta"].get("start_datum")
        if not start_str:
            print("CHYBA: 'start_datum' neni nastaven v YAML. Pouzij --start YYYY-MM-DD.")
            sys.exit(1)
        start_date = datetime.date.fromisoformat(str(start_str))

    _validate_start(start_date)

    t = _parse_time_arg(start_time)

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
            name    = _vtp_name(tyden, den_key, typ)
            label   = TYP_LABEL.get(typ, typ.replace("_", " ").capitalize())
            summary = f"VTP T{tyden:02d} {DEN_CODE[den_key]} - {label}"
            uid     = name.lower() + "@garmin-treninky"
            desc    = _ics_description(day_data)

            ics_lines.extend(_ics_vevent(uid, summary, date, desc=desc, t=t,
                                         duration_min=_estimate_duration_min(day_data)))
            count += 1

    # vlastni pravidelne treninky (hazena) - jen do kalendare, ne na Garmin
    tydnu = weeks_limit or len(plan.get("tydny", [])) or 12
    for ev in vlastni_ics_events(overlay, start_date,
                                 start_date + datetime.timedelta(weeks=tydnu)
                                 - datetime.timedelta(days=1)):
        ics_lines.extend(_ics_vevent(
            f"vlastni-{ev['klic']}-{ev['date']:%Y%m%d}@garmin-treninky",
            ev["nazev"], ev["date"], desc=ev["popis"], t=t,
            duration_min=ev["delka_min"]))
        count += 1

    ics_lines.append("END:VCALENDAR\r\n")

    out_path = Path(out_file)
    out_path.write_bytes("".join(ics_lines).encode("utf-8"))
    print(f"Vygenerovano {count} udalosti -> {out_path.resolve()}")
    print("Import: Google Calendar -> + (Dalsi kalendare) -> Importovat")


def _index_plan_by_name(plan):
    """Mapuje VTP název workoutu -> info o dni v YAML plánu.

    Slouží ke zpětnému dohledání popisu a odhadu délky podle názvu
    tréninku naplánovaného na Garmin kalendáři (nezávisle na datu).
    """
    index = {}
    for tyden_data in plan.get("tydny", []):
        tyden = tyden_data["tyden"]
        for den_key, day_data in tyden_data.get("dny", {}).items():
            if not day_data:
                continue
            typ = day_data.get("typ", "volno")
            if typ in ("volno", "aktivni_odpocinek"):
                continue
            index[_vtp_name(tyden, den_key, typ)] = {
                "tyden": tyden,
                "den_code": DEN_CODE[den_key],
                "typ": typ,
                "day_data": day_data,
            }
    return index


def _next_month(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _fetch_garmin_vtp_events(api, start_date, end_date):
    """Načte z Garmin kalendáře (/calendar-service) naplánované VTP-T* tréninky.

    Iteruje měsíc po měsíci od start_date do end_date (včetně) a vrací
    seřazený seznam {"date": date, "name": str}. JSON parsuje defenzivně
    (tvar není oficiálně dokumentovaný). Duplicitní (name, date) tiše
    slučuje — měsíční pohled obsahuje i okrajové dny sousedních měsíců.
    """
    events = {}
    y, m = start_date.year, start_date.month
    while (y, m) <= (end_date.year, end_date.month):
        try:
            data = api.get_scheduled_workouts(y, m)
        except Exception as e:
            print(f"  [WARN] Nepodarilo se nacist kalendar {y}-{m:02d}: {e}")
            y, m = _next_month(y, m)
            continue
        items = data.get("calendarItems", []) if isinstance(data, dict) else []
        for item in items:
            item_type = str(item.get("itemType") or item.get("type") or "").lower()
            if item_type and item_type != "workout":
                continue
            title = str(item.get("title") or item.get("workoutName")
                        or item.get("name") or "").strip()
            if not title.startswith("VTP-T"):
                continue
            date_str = item.get("date") or item.get("calendarDate")
            if not date_str:
                continue
            try:
                d = datetime.date.fromisoformat(str(date_str)[:10])
            except ValueError:
                continue
            if start_date <= d <= end_date:
                events[(title, d)] = {"date": d, "name": title}
        y, m = _next_month(y, m)
    return sorted(events.values(), key=lambda e: (e["date"], e["name"]))


def generate_ics_from_garmin(plan_name="muzi", out_file="vtp-garmin.ics",
                             start_time=None, email=None, password=None,
                             no_save=False, max_hr=None,
                             vlastni=None, bez_vlastnich=False):
    """Vygeneruje ICS ze SKUTEČNĚ naplánovaných VTP-T* tréninků na Garmin
    kalendáři (od dneška dál) + vlastních pravidelných tréninků z overlay.

    Autoritou pro data je Garmin kalendář — použij po ručním přeházení
    termínů na Garminu, kdy lokální YAML + --start už neodpovídá realitě.
    Popis a odhad délky se dohledávají zpětně z YAML plánu podle názvu.

    Vlastní tréninky (házená) na Garminu nejsou a nikdy nebudou, takže se
    doplňují z overlay podle dne v týdnu — jinak by ze sdíleného Google
    kalendáře po přesynchronizování zmizely.
    """
    plan_file = PLAN_DIR / f"vtp-plan-{plan_name}.yaml"
    if not plan_file.exists():
        print(f"CHYBA: soubor {plan_file} neexistuje.")
        sys.exit(1)
    with open(plan_file, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    overlay = load_overlay(vlastni, bez_vlastnich)
    # index se staví z EFEKTIVNÍHO plánu, aby přesunutý den (VTP-T10-PO-SIL)
    # našel svůj popis
    plan, _ = apply_overlay(plan, overlay)
    day_index = _index_plan_by_name(plan)
    t = _parse_time_arg(start_time)

    print("Prihlasování do Garmin Connect...")
    api = _connect(email, password, no_save)
    # HR zóny z Connectu -> popisky dostanou reálné bpm místo % SFmax
    _load_hr_state(api, max_hr_override=max_hr)

    total_weeks = len(plan.get("tydny", []))
    today = datetime.date.today()
    # rezerva pro případ, že byl plán na Garminu posunut o pár týdnů dopředu
    end_date = today + datetime.timedelta(weeks=total_weeks + 6)

    print(f"Nacitám Garmin kalendar {today} az {end_date}...")
    events = _fetch_garmin_vtp_events(api, today, end_date)
    # vlastni treninky jen do posledni skutecne naplanovane udalosti - dal uz
    # plan nepokracuje a hazena by se sypala do nekonecna
    vlastni_do = events[-1]["date"] if events else today
    vlastni_ev = vlastni_ics_events(overlay, today, vlastni_do)
    if not events and not vlastni_ev:
        print(f"Zadne naplanovane VTP-T* treninky v rozsahu {today} az {end_date}.")
        return

    ics_lines = []
    ics_lines.append("BEGIN:VCALENDAR\r\n")
    ics_lines.append("VERSION:2.0\r\n")
    ics_lines.append("PRODID:-//VTP Treninkovy plan//CS\r\n")
    ics_lines.append("CALSCALE:GREGORIAN\r\n")
    ics_lines.append("METHOD:PUBLISH\r\n")

    count = 0
    seen_names = set()
    weeks_found = set()
    for ev in events:
        name, date = ev["name"], ev["date"]
        uid = name.lower() + "@garmin-treninky"
        if name in seen_names:
            # stejný workout naplánovaný vícekrát -> UID rozlišit datem,
            # jinak by Google Kalendář při importu nechal jen jednu událost
            uid = f"{name.lower()}-{date:%Y%m%d}@garmin-treninky"
            print(f"  [WARN] {name}: naplanovan vickrat, dalsi vyskyt {date}.")
        seen_names.add(name)

        info = day_index.get(name)
        if info:
            day_data     = info["day_data"]
            label        = TYP_LABEL.get(info["typ"],
                                         info["typ"].replace("_", " ").capitalize())
            summary      = f"VTP T{info['tyden']:02d} {info['den_code']} - {label}"
            desc         = _ics_description(day_data)
            duration_min = _estimate_duration_min(day_data)
            weeks_found.add(info["tyden"])
        else:
            print(f"  [WARN] {name} ({date}): nenalezen v YAML planu"
                  " - bez popisu, odhad delky 45 min.")
            summary, desc, duration_min = name, "", 45

        print(f"  {date}  {name}")
        ics_lines.extend(_ics_vevent(uid, summary, date, desc=desc, t=t,
                                     duration_min=duration_min))
        count += 1

    for ev in vlastni_ev:
        print(f"  {ev['date']}  {ev['nazev']} (vlastni, mimo Garmin)")
        ics_lines.extend(_ics_vevent(
            f"vlastni-{ev['klic']}-{ev['date']:%Y%m%d}@garmin-treninky",
            ev["nazev"], ev["date"], desc=ev["popis"], t=t,
            duration_min=ev["delka_min"]))
        count += 1

    ics_lines.append("END:VCALENDAR\r\n")

    out_path = Path(out_file)
    out_path.write_bytes("".join(ics_lines).encode("utf-8"))
    print(f"\nVygenerovano {count} udalosti ze skutecneho Garmin kalendare"
          f" -> {out_path.resolve()}")
    if vlastni_ev:
        print(f"  z toho {len(vlastni_ev)} vlastnich treninku z overlay")
    if events:
        print(f"Rozsah: {events[0]['date']} az {events[-1]['date']}")
    if weeks_found and max(weeks_found) < total_weeks:
        print(f"  [WARN] Posledni nalezeny tyden je T{max(weeks_found):02d}"
              f" z {total_weeks} - zkontroluj Garmin kalendar, plan mozna"
              " pokracuje za hranici hledani.")
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
  python push_plan.py --ics-garmin --time 06:30          # ICS ze skutecneho Garmin kalendare
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
    p.add_argument("--ics-garmin", nargs="?", const="vtp-garmin.ics", metavar="SOUBOR",
                   help="Vygenerovat ICS ze SKUTECNE naplanovanych VTP-T* treninku"
                        " na Garmin kalendari, od dneska dal (default: vtp-garmin.ics)."
                        " --start/--weeks se ignoruji, autoritou je Garmin kalendar")
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
    p.add_argument("--zkontroluj-plan", "--lint", dest="lint", action="store_true",
                   help="Offline kontrola převodu YAML -> Garmin kroky (bez přihlášení)."
                        " Hlásí prázdné workouty, cviky bez odpočtu/počtu a záměnu jednotek."
                        " Návratový kód 1 při nálezu — použitelné v CI")
    p.add_argument("--fetch-vykon", nargs="?", const="vykon-garmin.json", metavar="SOUBOR",
                   help="Stáhne reálný výkon + kondiční data z Garminu do JSON"
                        " (default: vykon-garmin.json). Bez --start bere 140 dní dozadu."
                        " Použij --pauza-faktor stejný jako při nahrávání plánu")
    p.add_argument("--od-tydne", type=int, default=1, metavar="N",
                   help="Začít nahrávat od týdne N (přeskočí týdny 1..N-1); default: 1")
    p.add_argument("--vlastni", default=None, metavar="SOUBOR",
                   help="Overlay s vlastními tréninky a úpravami mimo armádní plán"
                        f" (default: {VLASTNI_FILE.name} v plan/, pokud existuje)")
    p.add_argument("--bez-vlastnich", action="store_true",
                   help="Ignorovat overlay — čistý armádní plán (např. rozběhání po zranění)")
    p.add_argument("--max-hr", type=int, default=None, metavar="N",
                   help="Ruční max. SF pro výpočet HR cílů (override / fallback pro --dry-run)."
                        " Priorita: --max-hr > zóny z Garmin Connect > bez HR cíle")
    args = p.parse_args()

    if args.lint:
        sys.exit(1 if lint_plan(plan_name=args.plan,
                                pauza_faktor=args.pauza_faktor,
                                vlastni=args.vlastni,
                                bez_vlastnich=args.bez_vlastnich) else 0)
    elif args.validate_cviky:
        validate_exercise_map(args.validate_cviky)
    elif args.fetch_cviky is not None:
        api = _connect(args.email, args.password, args.no_save)
        fetch_garmin_cviky(api, args.fetch_cviky)
    elif args.fetch_vykon is not None:
        api = _connect(args.email, args.password, args.no_save)
        fetch_garmin_vykon(
            api,
            output_file=args.fetch_vykon,
            plan_name=args.plan,
            pauza_faktor=args.pauza_faktor,
            start_override=args.start,
            max_hr=args.max_hr,
            vlastni=args.vlastni,
            bez_vlastnich=args.bez_vlastnich,
        )
    elif args.ics:
        # Pro ICS popisky využijeme --max-hr (jinak HR cíle zůstanou jen jako %)
        _apply_max_hr(args.max_hr)
        generate_ics(
            plan_name=args.plan,
            weeks_limit=args.weeks,
            start_override=args.start,
            out_file=args.ics,
            start_time=args.time,
            vlastni=args.vlastni,
            bez_vlastnich=args.bez_vlastnich,
        )
    elif args.ics_garmin is not None:
        generate_ics_from_garmin(
            plan_name=args.plan,
            out_file=args.ics_garmin,
            start_time=args.time,
            email=args.email,
            password=args.password,
            no_save=args.no_save,
            max_hr=args.max_hr,
            vlastni=args.vlastni,
            bez_vlastnich=args.bez_vlastnich,
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
            vlastni=args.vlastni,
            bez_vlastnich=args.bez_vlastnich,
        )


if __name__ == "__main__":
    main()
