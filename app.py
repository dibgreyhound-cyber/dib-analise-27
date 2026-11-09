# -*- coding: utf-8 -*-
"""
DIB 2.7 - Analise de corridas de galgos (Streamlit)
- Extracao: mesmo fluxo do app anterior (link do Racing Post -> blocks.sd?blocks=form)
- Calculo: regras do DIB 2.7 (projecao + 3 planilhas de AVB)
- Exibicao: tabelas no estilo do artefato (emojis de posicao, stacked V/D, medalhas)
"""
import re
import html
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st

# =====================================================================
# CONFIGURACAO (ajuste aqui sem mexer no resto do codigo)
# =====================================================================
CFG = {
    "N_RUNS": 5,                       # ultimas corridas lidas por galgo
    "WEIGHTS": [5, 4, 3, 2, 1],        # Time Decay
    "POND_MODE": "validas",            # "validas": 5,4,3.. so entre corridas validas | "posicao": peso pela posicao entre as 5
    "CAT_BASE_MODE": "media",          # "media" das classes validas | "ultima" corrida valida
    "CAT_BONUS": 2.0,                  # desceu de classe +2 / subiu -2
    "N_CORREDORES": 6,                 # total de corredores para a % de Recup
    "TRAFFIC_ADJ": {"baulk": 0.20, "crd": 0.10, "bmp": 0.10, "fcd": 0.10},  # Blk nao esta no manual
    "VEL_PTS": {"adj": 40, "mtime": 30, "msplit": 15, "ritmo": 15},        # Base de Velocidade (100)
    "VEL_MIN": 0.0,                    # pontos do pior em cada item
    "PERFIL_PTS": {"Limpo": 10.0, "Irregular": 5.0, "Trombador": 2.5},
    "RECUP_PTS": lambda rec: float(np.clip(5 + (rec or 0) / 10.0, 0, 10)),  # 0 a 10 pts
    "REMARKS_PTS": {"early": 1.5, "clear": 5.0, "slowaway": -10.0, "firstbend": -7.0},
    "TRAP_VAZIA": 1.5, "ESMAGAMENTO": -1.5, "TRAFEGO_SEVERO": -2.0, "WIDE": -1.0,
    "H2H": 1.0, "H2H_MARGEM_GRANDE": 3.0, "H2H_GRANDE": 2.0,
    "MOMENTUM_VITORIA": 3.0, "MOMENTUM_DERROTA": -2.0, "DERROTA_POS_MIN": 5,
    "PESO_DIAS_NO_OVERALL": True,      # soma os pontos de Peso e Dias no Overall
    "FORCA_PRINCIPAL": 50.0, "FORCA_SECUNDARIO": 40.0,
    "CONF_MIN_VENCEDOR": 60.0,
}

# Nomes possiveis dos campos no JSON do Racing Post (primeiro = o que seu app ja usava).
# Rode o app uma vez e abra "Diagnostico" para ver quais campos foram encontrados.
FIELD_MAP = {
    "date":    ["raceTime", "raceDate", "date"],
    "track":   ["trackName", "track"],
    "dist":    ["distMetres", "distance", "dist", "raceDistance"],
    "grade":   ["raceClass", "raceGrade", "grade", "raceClassDesc"],
    "trap":    ["trapNum", "trap"],
    "split":   ["sectionalTime", "split"],
    "bends":   ["bndPos", "bends"],
    "fin":     ["outcomeDesc", "fin", "finPos"],
    "by":      ["distBtn", "by", "beatenDistance", "btnDist"],
    "wntm":    ["winTimeS", "winTime", "wnTm", "winnerTime"],
    "gng":     ["goingType", "gng", "going"],
    "weight":  ["weight", "dogWeight", "wght"],
    "remarks": ["closeUpCmnt", "remarks"],
    "caltm":   ["calcRTimes", "calTm", "calcTime"],
}

TRAP_EMOJI = {1: "🟥", 2: "🟦", 3: "⬜", 4: "⬛", 5: "🟧", 6: "🔳"}
RANK_EMOJI = {1: "🟢", 2: "🟡", 3: "⚪", 4: "🔵", 5: "🟠", 6: "🔴"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


# =====================================================================
# UTILIDADES DE LEITURA
# =====================================================================
def pick(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


def to_float(x):
    if x is None:
        return None
    try:
        s = re.sub(r"[^\d.\-+]", "", str(x).strip().replace(",", "."))
        return float(s) if s not in ("", "+", "-", ".") else None
    except Exception:
        return None


def going_offset(g):
    """Gng em centesimos de segundo: +40 -> 0.40. N/vazio -> 0."""
    s = str(g or "").strip().upper()
    if s in ("", "N", "NORMAL", "NONE", "NAN"):
        return 0.0
    v = to_float(s)
    return 0.0 if v is None else v / 100.0


def fin_num(x):
    m = re.search(r"\d+", str(x or ""))
    return int(m.group()) if m else None


def parse_lengths(x):
    if x in (None, ""):
        return None
    s = str(x).strip().lower()
    words = {"shd": 0.1, "hd": 0.2, "nk": 0.3, "dist": 30.0, "dis": 30.0}
    if s in words:
        return words[s]
    m = re.fullmatch(r"(\d+)?\s*(\d+)/(\d+)", s)
    if m:
        return float(m.group(1) or 0) + int(m.group(2)) / int(m.group(3))
    s = s.replace("¼", ".25").replace("½", ".5").replace("¾", ".75")
    try:
        return float(s)
    except Exception:
        return None


def bends_digits(b):
    return [int(c) for c in str(b or "") if c.isdigit()]


def grade_num(g):
    m = re.fullmatch(r"A(\d{1,2})", str(g or "").strip().upper())
    return int(m.group(1)) if m else None


def parse_date(s):
    if not s:
        return None
    s = str(s)[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass