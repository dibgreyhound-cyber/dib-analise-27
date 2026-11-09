# -*- coding: utf-8 -*-
"""
DIB 2.7 - Analise de corridas de galgos (Streamlit)
- Extracao automatica de metadados (Pista, Horario, Race, Classe, Post Pick)
- Calculo: regras do DIB 2.7 (projecao + 3 planilhas de AVB)
- Exibicao: tabelas otimizadas com colunas fixas e fundo escuro solido
"""
import re
import html
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st

# =====================================================================
# CONFIGURACAO
# =====================================================================

CFG = {
    "N_RUNS": 5,                       # ultimas corridas lidas por galgo
    "WEIGHTS": [5, 4, 3, 2, 1],        # Time Decay
    "POND_MODE": "validas",            # "validas": 5,4,3.. so entre corridas validas | "posicao": peso pela posicao entre as 5
    "CAT_BASE_MODE": "media",          # "media" das classes validas | "ultima" corrida valida
    "CAT_BONUS": 2.0,                  # desceu de classe +2 / subiu -2
    "N_CORREDORES": 6,                 # total de corredores para a % de Recup
    "TRAFFIC_ADJ": {"baulk": 0.20, "crd": 0.10, "bmp": 0.10, "fcd": 0.10},
    "VEL_PTS": {"adj": 40, "mtime": 30, "msplit": 15, "ritmo": 15},        # Base de Velocidade (100)
    "VEL_MIN": 0.0,                    # pontos do pior em cada item
    "PERFIL_PTS": {"Limpo": 10.0, "Irregular": 5.0, "Trombador": 2.5},
    "RECUP_PTS": lambda rec: float(np.clip(5 + (rec or 0) / 10.0, 0, 10)),  # 0 a 10 pts
    "REMARKS_PTS": {"early": 1.5, "clear": 5.0, "slowaway": -10.0, "firstbend": -7.0},
    "TRAP_VAZIA": 1.5, "ESMAGAMENTO": -1.5, "TRAFEGO_SEVERO": -2.0, "WIDE": -1.0,
    "H2H": 1.0, "H2H_MARGEM_GRANDE": 3.0, "H2H_GRANDE": 2.0,
    "MOMENTUM_VITORIA": 3.0, "MOMENTUM_DERROTA": -2.0, "DERROTA_POS_MIN": 5,
    "PESO_DIAS_NO_OVERALL": True,      # soma os pontos de Peso e Dias no Overall
    "FORCA_PRINCIPAL": 50.0, 
    "FORCA_SECUNDARIO": 45.0,          # Intervalo 45.0 a 49.9
    "CONF_MIN_VENCEDOR": 60.0,
}

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
# UTILIDADES DE LEITURA E EXTRACAO
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
    return None

RE_TRAF = re.compile(r"(crd|bmp|blk)")
RE_NOFREE = re.compile(r"(crd|bmp|blk|baulk|fcd-?ck|evch|mvdoff)")

def parts_of(rem):
    for tok in re.split(r"[,\s]+", str(rem or "").lower()):
        if tok:
            for p in tok.split("-"):
                if p:
                    yield p

def count_traf(rem):
    return sum(1 for p in parts_of(rem) if RE_TRAF.search(p))

def traffic_penalty(rem):
    s = str(rem or "").lower()
    for key in ("baulk", "crd", "bmp", "fcd"):
        if key in s and key in CFG["TRAFFIC_ADJ"]:
            return CFG["TRAFFIC_ADJ"][key] if key == "baulk" else max(
                CFG["TRAFFIC_ADJ"][k] for k in ("crd", "bmp", "fcd") if k in s)
    return 0.0

def not_free(rem):
    return bool(RE_NOFREE.search(str(rem or "").lower()))

def first_bend_traffic(rem):
    s = str(rem or "").lower()
    if "baulk" in s:
        return True
    return any(RE_TRAF.search(p) and "1" in re.findall(r"\d", p) for p in parts_of(rem))

def has_w(rem):
    return any(re.fullmatch(r"w\d*", t) for t in re.split(r"[,\-&/\s]+", str(rem or "").lower()) if t)

def remark_points(rem):
    R = CFG["REMARKS_PTS"]
    toks = [t for t in re.split(r"[,\s]+", str(rem or "").lower()) if t]
    pts, tags = 0.0, []
    if any(re.match(r"^(ep|ald|snld|ld)", t) for t in toks):
        pts += R["early"]; tags.append("Early Pace/Led")
    if any(t.startswith("clrrn") for t in toks):
        pts += R["clear"]; tags.append("Clear Run")
    if any(t.startswith("saw") or t.startswith("vsaw") for t in toks):
        pts += R["slowaway"]; tags.append("Slow Away")
    if first_bend_traffic(rem):
        pts += R["firstbend"]; tags.append("First Bend Traffic")
    return pts, tags

def wmean(vals, ws):
    pairs = [(v, w) for v, w in zip(vals, ws) if v is not None]
    return sum(v * w for v, w in pairs) / sum(w for _, w in pairs) if pairs else None

# =====================================================================
# EXTRACAO (Racing Post)
# =====================================================================

HINTS = {
    "dist": (("dist", "metre", "meter"), ("btn", "beat", "by")),
    "grade": (("class", "grade"), ()),
    "by": (("btn", "beaten"), ()),
    "wntm": (("win", "time"), ()),
}

def pick_fb(f, k):
    v = pick(f, FIELD_MAP[k])
    if v is not None or k not in HINTS:
        return v
    inc, exc = HINTS[k]
    for key, val in f.items():
        kl = str(key).lower()
        ok = all(x in kl for x in inc) if k == "wntm" else any(x in kl for x in inc)
        if ok and not any(x in kl for x in exc) and val not in (None, ""):
            return val
    return None

def norm_run(f):
    g = lambda k: pick_fb(f, k)
    return {
        "date": parse_date(g("date")),
        "date_str": str(g("date") or "")[:10],
        "track": str(g("track") or ""),
        "dist": to_float(g("dist")),
        "grade": str(g("grade") or "").strip().upper(),
        "trap": fin_num(g("trap")),
        "split": to_float(g("split")),
        "bends": str(g("bends") or ""),
        "fin": fin_num(g("fin")),
        "by": parse_lengths(g("by")),
        "wntm": to_float(g("wntm")),
        "gng": g("gng"),
        "weight": to_float(g("weight")),
        "remarks": str(g("remarks") or ""),
        "caltm": to_float(g("caltm")),
    }

GRADE_RE = re.compile(r"^(A\d{1,2}|T\d?|HP|OR|IT|S\d|D\d|B\d|ON\d)$")

def descobrir_chaves(dogs):
    vals = {}
    for dog in dogs:
        for f in dog.get("forms", []):
            for k, v in f.items():
                if isinstance(v, (str, int, float)) and v not in ("", None):
                    vals.setdefault(k, []).append(v)
    for k, vs in vals.items():
        kl = str(k).lower()
        if any(x in kl for x in ("btn", "beat", "weight", "time", "id")):
            continue
        nums = [to_float(v) for v in vs]
        if all(n is not None and 150 <= n <= 900 for n in nums) and len(set(nums)) <= 6:
            if k not in FIELD_MAP["dist"]:
                FIELD_MAP["dist"].insert(0, k)
            break
    for k, vs in vals.items():
        if sum(1 for v in vs if GRADE_RE.match(str(v).strip().upper())) >= 0.8 * len(vs):
            if k not in FIELD_MAP["grade"]:
                FIELD_MAP["grade"].insert(0, k)
            break

def extrair_metadados_json(data, dogs):
    """Extrai pista, horario, race, classe e post pick de forma inteligente do JSON."""
    info = {"pista": "", "hora": "", "race": "", "classe": "", "post_pick": ""}
    
    # 1. Pista
    pista = data.get("trackName") or data.get("track") or data.get("meetingName") or data.get("courseName")
    if not pista and dogs and dogs[0].get("runs"):
        # Tenta pegar da primeira corrida do primeiro galgo
        pista = dogs[0]["runs"][0].get("track")
    info["pista"] = str(pista or "Desconhecida").strip()
    
    # 2. Horário da prova
    t_raw = data.get("raceTime") or data.get("time") or data.get("offTime") or data.get("displayTime")
    if not t_raw:
        # Tenta procurar em strings do JSON
        def achar_hora(obj):
            nonlocal t_raw
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and re.search(r"\d{1,2}:\d{2}", v) and not t_raw:
                        m_h = re.search(r"(\d{1,2}:\d{2})", v)
                        if m_h:
                            t_raw = m_h.group(1)
                    elif isinstance(v, (dict, list)):
                        achar_hora(v)
            elif isinstance(obj, list):
                for item in obj:
                    achar_hora(item)
        achar_hora(data)
    
    if t_raw:
        m_time = re.search(r"(\d{1,2}:\d{2})", str(t_raw))
        if m_time:
            info["hora"] = f"{m_time.group(1)}"

    # 3. Número da Race
    r_num = data.get("raceNum") or data.get("raceNumber") or data.get("rNum") or data.get("raceNumberDesc")
    if not r_num:
        def achar_racenum(obj):
            nonlocal r_num
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if "racenumber" in k.lower() or "racenum" in k.lower() or k.lower() == "rnum":
                        r_num = v
                    elif isinstance(v, (dict, list)):
                        achar_racenum(v)
            elif isinstance(obj, list):
                for item in obj:
                    achar_racenum(item)
        achar_racenum(data)
    if r_num:
        info["race"] = str(r_num).replace("Race", "").strip()

    # 4. Classe (Grade)
    grade = data.get("raceClass") or data.get("grade") or data.get("class")
    if not grade and dogs and dogs[0].get("runs"):
        grade = dogs[0]["runs"][0].get("grade")
    info["classe"] = str(grade or "").strip().upper()

    # 5. Post Pick
    pp_val = data.get("postPick") or data.get("post_pick")
    if not pp_val:
        def achar_pp(obj):
            nonlocal pp_val
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and "post pick" in v.lower():
                        m_pp = re.search(r"post\s*pick[:\s]*([\d\-_/]+)", v, re.IGNORECASE)
                        if m_pp:
                            pp_val = m_pp.group(1)
                    elif isinstance(v, (dict, list)):
                        achar_pp(v)
            elif isinstance(obj, list):
                for item in obj:
                    achar_pp(item)
        achar_pp(data)
    if pp_val:
        info["post_pick"] = str(pp_val).strip()

    return info

def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)
        if not race_id_match or not r_date_match:
            st.error("Link inválido. Precisa ter 'race_id' e 'r_date'.")
            return None, None, None
        race_id, r_date_str = race_id_match.group(1), r_date_match.group(1)
        api_url = (f"https://greyhoundbet.racingpost.com/card/blocks.sd?"
                   f"race_id={race_id}&r_date={r_date_str}&blocks=form")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://greyhoundbet.racingpost.com/",
        }
        with st.spinner("Buscando dados no Racing Post..."):
            resp = requests.get(api_url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado encontrado.")
            return None, None, None
        descobrir_chaves(dogs)
        out = []
        for dog in dogs:
            trap = fin_num(dog.get("trapNum"))
            runs = [norm_run(f) for f in dog.get("forms", [])]
            out.append({
                "name": dog.get("dogName", "Desconhecido"),
                "trap": trap or 0,
                "peso_atual": to_float(dog.get("weight")),
                "runs": runs,
            })
        meta_info = extrair_metadados_json(data, out)
        return out, {"r_date": r_date_str, "raw_first": dogs[0]}, meta_info
    except Exception as e:
        st.error(f"Erro: {e}")
        return None, None, None

def diagnostico_campos(dogs):
    runs = [r for d in dogs for r in d["runs"]]
    rows = []
    for k in ["date", "track", "dist", "grade", "trap", "split", "bends", "fin", "by",
              "wntm", "gng", "weight", "remarks", "caltm"]:
        n = sum(1 for r in runs if r.get(k) not in (None, "", [], 0.0) or (k == "gng" and r.get(k) is not None))
        rows.append({"Campo": k, "Candidatos no FIELD_MAP": ", ".join(FIELD_MAP[k]),
                     "Preenchido em": f"{n}/{len(runs)} corridas"})
    return pd.DataFrame(rows)

# =====================================================================
# CALCULO DO DIB 2.7
# =====================================================================

 def oficial(r, ctx):
    return (grade_num(r["grade"]) is not None and r["dist"] is not None
            and abs(r["dist"] - ctx["dist"]) < 1
            and r["caltm"] is not None and r["caltm"] > 0)

def peso_pts(v):
    if v is None:
        return 0.0
    return -5.0 if v >= 2.0 else (-2.0 if v >= 1.1 else 0.0)

def dias_pts(d):
    if d is None:
        return 0.0
    if d < 4:
        return -5.0
    if d <= 28:
        return 0.0
    if d <= 45:
        return -3.0
    return -5.0

def analisar_galgo(dog, ctx):
    runs = sorted(dog["runs"], key=lambda r: r["date"] or datetime.min, reverse=True)[:CFG["N_RUNS"]]
    val = [(i, r) for i, r in enumerate(runs) if oficial(r, ctx)]
    W = CFG["WEIGHTS"]
    ws = [W[j] for j in range(len(val))] if CFG["POND_MODE"] == "validas" else [W[i] for i, _ in val]
    R = [r for _, r in val]
    d = {"name": dog["name"], "trap": dog["trap"], "runs": runs, "val": R,
         "nd": not R, "conf": min(100.0, len(R) * 20.0),
         "hist": "·".join((r["grade"] or "?") for r in runs)}
    ultima_any = runs[0] if runs else None
    d["dias"] = (ctx["today"] - ultima_any["date"]).days if ultima_any and ultima_any["date"] else None
    d["dias_pts"] = dias_pts(d["dias"])
    d["forma_trial"] = bool(ultima_any and re.match(r"^T", ultima_any["grade"] or ""))
    if not R:
        return d

    pts = [16 - grade_num(r["grade"]) for r in R]
    base = float(np.mean(pts)) if CFG["CAT_BASE_MODE"] == "media" else float(pts[0])
    last_n, today_n = grade_num(R[0]["grade"]), ctx.get("classe_n")
    mod = 0.0
    if today_n and last_n:
        mod = CFG["CAT_BONUS"] if today_n > last_n else (-CFG["CAT_BONUS"] if today_n < last_n else 0.0)
    d["cat_mod"], d["cat"] = mod, base + mod

    last_w = R[0]["weight"]
    atual = dog.get("peso_atual")
    if atual is None and len(R) > 1:
        atual, last_w = R[0]["weight"], R[1]["weight"]
    d["peso"] = atual if atual is not None else last_w
    d["peso_var"] = abs(atual - last_w) if atual is not None and last_w is not None else None
    d["peso_pts"] = peso_pts(d["peso_var"])

    d["split"], d["time"] = R[0]["split"], R[0]["caltm"]
    d["peso_ult"] = last_w
    d["msplit"] = wmean([r["split"] for r in R], ws)
    d["mtime"] = wmean([r["caltm"] for r in R], ws)
    d["ritmo"] = d["mtime"] - d["msplit"] if d["mtime"] is not None and d["msplit"] is not None else None
    adj = [r["caltm"] - going_offset(r["gng"]) - traffic_penalty(r["remarks"])
           for r in R if r["caltm"] is not None]
    d["tadj"] = float(np.mean(adj)) if adj else None
    cal = [r["caltm"] for r in R if r["caltm"] is not None]
    d["sd"] = float(np.std(cal)) if len(cal) > 1 else 0.0

    recs = []
    for r in R:
        b = bends_digits(r["bends"])
        if b and r["fin"] and not not_free(r["remarks"]):
            recs.append((b[0] - r["fin"]) / CFG["N_CORREDORES"] * 100.0)
    d["rec"] = float(np.mean(recs)) if recs else None
    d["rec_n"] = len(recs)
    if d["rec"] is None:
        d["rec_txt"] = "n/d"
    else:
        tag = "Ganhou" if d["rec"] > 0.005 else ("Perdeu" if d["rec"] < -0.005 else "Manteve")
        d["rec_txt"] = f"{d['rec']:+.2f}% ({tag})"

    n_traf = sum(count_traf(r["remarks"]) for r in R)
    d["n_traf"] = n_traf
    d["perfil"] = "Limpo" if n_traf <= 1 else ("Irregular" if n_traf == 2 else "Trombador")
    firsts = [bends_digits(r["bends"])[0] for r in R if bends_digits(r["bends"])]
    d["first_avg"] = float(np.mean(firsts)) if firsts else None
    n_w = sum(1 for r in R if has_w(r["remarks"]))
    if n_w >= 3:
        d["estilo"] = "Aberto"
    elif d["first_avg"] is not None and d["first_avg"] <= 2.5:
        d["estilo"] = "Rápido"
    elif d["first_avg"] is not None and d["first_avg"] >= 4 and (d["rec"] or 0) > 0:
        d["estilo"] = "Fecha forte"
    else:
        d["estilo"] = "Meio"
    fins = [r["fin"] for r in R if r["fin"]]
    d["posmed"] = float(np.mean(fins)) if fins else None

    d["remark_pts"], d["remark_tags"] = remark_points(R[0]["remarks"])
    f0 = R[0]["fin"]
    d["momentum"] = 0.0
    if f0 == 1:
        d["momentum"] = CFG["MOMENTUM_VITORIA"]
    elif f0 and f0 >= CFG["DERROTA_POS_MIN"] and mod <= 0:
        d["momentum"] = CFG["MOMENTUM_DERROTA"]
    return d

def h2h_pairs(dogs):
    res = {}
    for a in dogs:
        for b in dogs:
            if a["name"] >= b["name"]:
                continue
            idx_b = {}
            for r in b["runs"]:
                if r["wntm"] and r["fin"] is not None:
                    idx_b[(r["date_str"], r["track"], r["dist"], r["grade"], round(r["wntm"], 2))] = r
            best = None
            for r in sorted(a["runs"], key=lambda x: x["date"] or datetime.min, reverse=True):
                if not r["wntm"] or r["fin"] is None:
                    continue
                k = (r["date_str"], r["track"], r["dist"], r["grade"], round(r["wntm"], 2))
                if k in idx_b:
                    best = (r, idx_b[k])
                    break
            if best and best[0]["fin"] != best[1]["fin"]:
                ra, rb = best
                beh = lambda x: 0.0 if x["fin"] == 1 else (x["by"] or 0.0)
                margem = abs(beh(ra) - beh(rb))
                win, lose = (a, b) if ra["fin"] < rb["fin"] else (b, a)
                res[(a["name"], b["name"])] = (win["name"], lose["name"], margem)
    return res

def finalizar(ds, ctx):
    ok = [d for d in ds if not d["nd"]]
    vac = [t for t in range(1, CFG["N_CORREDORES"] + 1) if t not in {d["trap"] for d in ds}]
    ctx["vazias"] = vac

    def pts_item(key, maxp, d):
        vals = [x[key] for x in ok if x[key] is not None]
        if d[key] is None:
            return (maxp + CFG["VEL_MIN"]) / 2
        lo, hi = min(vals), max(vals)
        if hi == lo:
            return float(maxp)
        return CFG["VEL_MIN"] + (maxp - CFG["VEL_MIN"]) * (hi - d[key]) / (hi - lo)

    split_rank = sorted([d for d in ok if d["split"] is not None], key=lambda x: x["split"])
    top2_split = {d["name"] for d in split_rank[:2]}
    ms_rank = sorted([d for d in ok if d["msplit"] is not None], key=lambda x: round(x["msplit"], 2))
    top3_ms = {d["name"] for d in ms_rank[:3]}
    h2h = h2h_pairs(ok)
    h2h_net, h2h_big = {d["name"]: 0 for d in ok}, {d["name"]: 0.0 for d in ok}
    for (w, l, m) in h2h.values():
        h2h_net[w] += 1; h2h_net[l] -= 1
        h2h_big[w] = max(h2h_big[w], m)
    ctx["h2h"] = h2h

    for d in ok:
        V = CFG["VEL_PTS"]
        d["vel"] = (pts_item("tadj", V["adj"], d) + pts_item("mtime", V["mtime"], d)
                    + pts_item("msplit", V["msplit"], d) + pts_item("ritmo", V["ritmo"], d))
        d["perfil_pts"] = CFG["PERFIL_PTS"][d["perfil"]]
        d["rec_pts"] = CFG["RECUP_PTS"](d["rec"])
        fat = []
        t = d["trap"]
        if any(abs(t - v) == 1 for v in vac):
            fat.append(("Trap Vazia", CFG["TRAP_VAZIA"]))
        if t in (4, 5, 6) and d["name"] not in top2_split:
            fat.append(("Esmagamento", CFG["ESMAGAMENTO"]))
        if t in (1, 2, 3) and d["perfil"] == "Trombador":
            fat.append(("Tráfego Severo", CFG["TRAFEGO_SEVERO"]))
        if t in (4, 5, 6) and d["estilo"] == "Aberto":
            fat.append(("Wide", CFG["WIDE"]))
        if h2h_net[d["name"]] > 0:
            fat.append(("H2H", CFG["H2H_GRANDE"] if h2h_big[d["name"]] > CFG["H2H_MARGEM_GRANDE"] else CFG["H2H"]))
        if d["momentum"]:
            fat.append(("Momentum " + ("vitória" if d["momentum"] > 0 else "derrota"), d["momentum"]))
        d["fatores"] = fat
        extra = (d["peso_pts"] + d["dias_pts"]) if CFG["PESO_DIAS_NO_OVERALL"] else 0.0
        d["overall"] = (d["vel"] + d["cat"] + d["perfil_pts"] + d["rec_pts"] + d["remark_pts"]
                        + sum(v for _, v in fat) + extra)

    ok.sort(key=lambda x: (-round(x["overall"], 2), -x["cat"]))
    for i, d in enumerate(ok, 1):
        d["pos"] = i
        d["bloqueado"] = d["conf"] < CFG["CONF_MIN_VENCEDOR"]
        d["trial_block"] = d["forma_trial"]
        fora_top3 = d["name"] not in top3_ms
        d["alvo"] = fora_top3 and d["rec"] is not None and d["rec"] <= 0 \
            and (not d["forma_trial"] or len(d["val"]) >= 3)
        d["elegivel"] = not d["bloqueado"] and not d["forma_trial"]
    for d in ds:
        if d["nd"]:
            d["pos"] = None
    return ok

# =====================================================================
# AVB
# =====================================================================

def forca(V, D, ctx):
    pp = ctx.get("post_pick", [])
    f = (V["overall"] - D["overall"])
    f += 100.0 * ((D["mtime"] or 0) - (V["mtime"] or 0))
    f += ((V["rec"] or 0) - (D["rec"] or 0)) / 2.0
    f += (V["cat"] - D["cat"]) * 2.0
    notes = []
    if V["estilo"] == "Rápido" and D["estilo"] != "Rápido":
        f += 5; notes.append("+5 Rápido")
    key = tuple(sorted([V["name"], D["name"]]))
    h = ctx["h2h"].get(key)
    if h and h[0] == V["name"]:
        f += 5; notes.append("+5 H2H")
    if V["estilo"] == "Rápido" and D["estilo"] == "Rápido" and V["trap"] in (1, 2, 3):
        f += 5; notes.append("+5 trap interna")
    if V["estilo"] == "Fecha forte" and D["estilo"] == "Rápido" and D["trap"] in (1, 2, 3):
        f -= 5; notes.append("−5 Fecha forte vs Rápido interno")
    sd = float(np.clip(10.0 * (D["sd"] - V["sd"]), -5, 5))
    f += sd
    if abs(sd) >= 0.05:
        notes.append(f"{sd:+.1f} desvio")
    if V["trap"] in pp and (D["trap"] not in pp or pp.index(V["trap"]) < pp.index(D["trap"])):
        f += 5; notes.append("+5 Post Pick")
    if any(abs(V["trap"] - v) == 1 for v in ctx["vazias"]):
        f += 5; notes.append("+5 Trap Vazia")
    return f, notes

def montar_avbs(rank, ctx):
    elig = [d for d in rank if d["elegivel"]]
    elite = {}
    slots = [(3, 4), (4, 5), (5, 6)]
    for k, poss in enumerate(slots):
        if k >= len(elig):
            break
        V = elig[k]
        for p in poss:
            if p <= len(rank):
                D = rank[p - 1]
                if D is not V and D["overall"] < V["overall"]:
                    elite[(V["name"], D["name"])] = (V, D)
    alvos = [d for d in rank if d["alvo"]]
    s1, s2, s3 = [], [], []
    for (V, D) in elite.values():
        f, n = forca(V, D, ctx)
        if D["alvo"]:
            continue
        if f >= CFG["FORCA_PRINCIPAL"]:
            s2.append((V, D, f, n, False))
        elif f >= CFG["FORCA_SECUNDARIO"]:
            s3.append((V, D, f, n, False))
    for A in alvos:
        for V in elig:
            if V is A or V["overall"] <= A["overall"]:
                continue
            f, n = forca(V, A, ctx)
            if f >= CFG["FORCA_PRINCIPAL"]:
                s1.append((V, A, f, n, (V["name"], A["name"]) in elite))
    for (V, D) in elite.values():
        if D["alvo"]:
            f, n = forca(V, D, ctx)
            if CFG["FORCA_SECUNDARIO"] <= f < CFG["FORCA_PRINCIPAL"]:
                s3.append((V, D, f, n, False))
    key = lambda x: -x[2]
    return sorted(s1, key=key), sorted(s2, key=key), sorted(s3, key=key)

# =====================================================================
# EXIBICAO
# =====================================================================

CSS = """
<style>
.dib-wrap{overflow-x:auto;border:1px solid rgba(128,128,128,.35);border-radius:10px;margin:6px 0 14px}
.dib{border-collapse:separate;border-spacing:0;font-size:13px;width:max-content;min-width:100%}
.dib th,.dib td{padding:6px 9px;border-bottom:1px solid rgba(128,128,128,.25);white-space:nowrap;text-align:center;vertical-align:middle}
.dib th{background:rgba(128,128,128,.15);font-weight:600}
.dib td.l,.dib th.l{text-align:left;font-weight:600}
.dib .s1{position:sticky;left:0;z-index:2;background-color:#0e1117 !important;}
.dib .s2{position:sticky;left:46px;z-index:2;background-color:#0e1117 !important;box-shadow:2px 0 0 rgba(128,128,128,.35)}
.dib td.w{white-space:normal;min-width:200px;text-align:left}
.g{color:#0b8a3b;font-weight:600}.r{color:#c62828;font-weight:600}
</style>
"""

def tbl(headers, rows, sticky=True):
    h = "".join(f"<th class='{'l' if i < 2 else ''}'>{x}</th>" for i, x in enumerate(headers))
    out = []
    for row in rows:
        cells = []
        for i, c in enumerate(row):
            cls = ""
            if sticky and i == 0: cls = " class='s1'"
            elif sticky and i == 1: cls = " class='s2 l'"
            cells.append(f"<td{cls}>{c}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='dib-wrap'><table class='dib'><tr>{h}</tr>{''.join(out)}</table></div>"

def ranks_low(values):
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    for i in idx:
        out[i] = 1 + sum(1 for j in idx if round(values[j], 2) < round(values[i], 2))
    return out

def f2(x, n=2):
    return "n/d" if x is None else f"{x:.{n}f}"

def nome_marcado(d):
    n = html.escape(d["name"])
    if d.get("bloqueado") or d.get("trial_block"):
        n = "[BLOQUEADO] " + n
    if d.get("alvo"):
        n = "🎯 " + n
    return n

def trap_label(d):
    return f"{TRAP_EMOJI.get(d['trap'], '')} {d['trap']}"

def tabela_projecao(ds):
    cols = ["split", "time", "tadj", "msplit", "mtime", "ritmo"]
    rk = {}
    for c in cols:
        vals = [None if d["nd"] else d[c] for d in ds]
        rk[c] = ranks_low(vals)
    rows = []
    for i, d in enumerate(ds):
        if d["nd"]:
            rows.append([trap_label(d), html.escape(d["name"]), "n/d"] + ["-"] * 15)
            continue

        def cell(c, n=2):
            r = rk[c][i]
            return f"{RANK_EMOJI.get(r, '🔴') if r else ''} {f2(d[c], n)}".strip()
        fat = "<br>".join(f"{k} {v:+.1f}" for k, v in d["fatores"]) or "-"
        if d["remark_tags"]:
            fat += "<br>" + ", ".join(d["remark_tags"]) + f" {d['remark_pts']:+.1f}"
        perfil_e = {"Limpo": "✅", "Irregular": "⚠️", "Trombador": "🔴"}[d["perfil"]]
        medal = MEDALS.get(d["pos"], f"{d['pos']}º")
        rows.append([
            trap_label(d), nome_marcado(d), f"{medal} {d['overall']:.2f}",
            f"{d['cat']:.2f}" + (f" ({d['cat_mod']:+.0f})" if d.get("cat_mod") else ""),
            f"<span style='white-space:normal'>{fat}</span>",
            f"{perfil_e} {d['perfil']} ({d['n_traf']})", d["hist"], f2(d["posmed"], 1),
            f"{f2(d['peso'], 1)} ({d['peso_pts']:+.0f})", f"{d['dias']} ({d['dias_pts']:+.0f})",
            cell("split"), cell("time"), cell("tadj"), cell("msplit"), cell("mtime"), cell("ritmo"),
            d["rec_txt"], f"{d['conf']:.0f}%",
        ])
    heads = ["Trap", "Galgo", "Overall", "Categoria", "Fatores", "Perfil", "Histórico", "Posição Med.",
             "Peso", "Dias", "Split", "Time", "Time Ajustado", "Média Split", "Média Time",
             "Ritmo final", "Recup. Média", "Confiança"]
    return tbl(heads, rows)

def classificacao(rank):
    partes = []
    for d in rank:
        m = MEDALS.get(d["pos"], f"{d['pos']}º")
        partes.append(f"{m} {TRAP_EMOJI.get(d['trap'], '')} {d['trap']}")
    return " > ".join(partes)

def stack(vv, dv, fmt, better="low", sign=True):
    if vv is None or dv is None:
        return f"{'n/d' if vv is None else fmt(vv)}<br>{'n/d' if dv is None else fmt(dv)}"
    diff = vv - dv
    good = (diff < 0) if better == "low" else (diff > 0)
    cls = "" if abs(diff) < 1e-9 or better is None else ("g" if good else "r")
    dtxt = f" ({diff:+.2f})" if sign else ""
    return f"<span class='{cls}'>{fmt(vv)}{dtxt}</span><br>{fmt(dv)}"

def tabela_avb(lista, titulo, ctx):
    st.markdown(f"#### {titulo}")
    if not lista:
        st.info("Nenhum AVB nesta categoria.")
        return
    rows = []
    for (V, D, f, notes, star) in lista:
        pv = lambda x: f"{x:.2f}"
        rows.append([
            f"{'⭐ ' if star else ''}{trap_label(V)} vence {trap_label(D)}<br>"
            f"<span style='font-weight:400'>{html.escape(V['name'])} vs {html.escape(D['name'])}</span>",
            stack(V["overall"], D["overall"], pv, "high"),
            stack(V["cat"], D["cat"], pv, "high"),
            f"{V['perfil']}<br>{D['perfil']}",
            f"{V['hist']}<br>{D['hist']}",
            stack(V["posmed"], D["posmed"], lambda x: f"{x:.1f}", "low"),
            stack(V["peso"], D["peso"], lambda x: f"{x:.1f}", None),
            f"{V['dias']}<br>{D['dias']}",
            stack(V["split"], D["split"], pv, "low"),
            stack(V["time"], D["time"], pv, "low"),
            stack(V["tadj"], D["tadj"], pv, "low"),
            stack(V["msplit"], D["msplit"], pv, "low"),
            stack(V["mtime"], D["mtime"], pv, "low"),
            stack(V["ritmo"], D["ritmo"], pv, "low"),
            f"{V['rec_txt']}<br>{D['rec_txt']}",
            f"{V['conf']:.0f}%<br>{D['conf']:.0f}%",
            f"<b>{f:.2f}</b><br><span style='font-size:11px;white-space:normal'>{', '.join(notes)}</span>",
        ])
    heads = ["AvB", "Overall", "Categoria", "Perfil", "Histórico", "Posição Med.", "Peso", "Dias",
             "Split", "Time", "Time Ajustado", "Média Split", "Média Tempo", "Ritmo final",
             "Recup. Média", "Confiança", "Força"]
    st.markdown(tbl(heads, rows), unsafe_allow_html=True)

def observacoes(rank):
    out = []
    for d in rank:
        pos, neg = [], []
        if d["perfil"] == "Limpo": pos.append("perfil limpo")
        if d["perfil"] == "Trombador": neg.append(f"trombador ({d['n_traf']} ocorrências)")
        if d["rec"] is not None and d["rec"] > 0: pos.append(f"recupera posições ({d['rec']:+.1f}%)")
        if d["rec"] is not None and d["rec"] <= 0: neg.append(f"não recupera ({d['rec']:+.1f}%)")
        pos += [f"{k} ({v:+.1f})" for k, v in d["fatores"] if v > 0]
        neg += [f"{k} ({v:+.1f})" for k, v in d["fatores"] if v < 0]
        if d["remark_tags"]: (neg if d["remark_pts"] < 0 else pos).append(", ".join(d["remark_tags"]))
        if d["bloqueado"]: neg.append(f"confiança {d['conf']:.0f}% (bloqueado como vencedor)")
        if d["trial_block"]: neg.append("última corrida foi trial (bloqueado como vencedor)")
        if d["alvo"]: neg.append("alvo: Média Split fora do Top 3 e Recup ≤ 0")
        if d["dias_pts"] or d["peso_pts"]: neg.append(f"dias {d['dias']} ({d['dias_pts']:+.0f}), peso Δ{f2(d['peso_var'],1)} ({d['peso_pts']:+.0f})")
        out.append(f"- **{trap_label(d)} {d['name']}** — ➕ {'; '.join(pos) or '-'} | ➖ {'; '.join(neg) or '-'}")
    return "\n".join(out)

def hora_br(hhmm):
    if not hhmm:
        return None
    s = str(hhmm).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    h_val = int(m.group(1))
    m_val = int(m.group(2))
    # Se horario for menor que 9, converte formato 12h para 24h (ex: 5:24 -> 17:24)
    if h_val < 9:
        h_val += 12
    t = datetime(2000, 1, 1, h_val, m_val) - timedelta(hours=3)
    return t.strftime("%H:%M")

# =====================================================================
# APP
# =====================================================================
 

def mostrar_diagnostico(dogs, meta):
    st.markdown("**Campos lidos do JSON** (se algum estiver 0, ajuste o `FIELD_MAP` no topo do código):")
    st.dataframe(diagnostico_campos(dogs), use_container_width=True, hide_index=True)
    st.markdown("**Chaves da primeira corrida do primeiro galgo (JSON bruto):**")
    first = meta["raw_first"]
    st.json(first.get("forms", [{}])[0] if first.get("forms") else first)
    linhas = [{"Galgo": d["name"], "Trap": d["trap"], **{k: r[k] for k in
              ["date_str", "track", "dist", "grade", "split", "bends", "fin", "by", "wntm", "gng",
               "weight", "remarks", "caltm"]}} for d in dogs for r in d["runs"]]
    st.dataframe(pd.DataFrame(linhas), use_container_width=True)

def main():
    st.set_page_config(page_title="DIB 2.7 - Projeção", layout="wide")
    st.title("🐾 Análise DIB 2.7")
    st.markdown(CSS, unsafe_allow_html=True)

    # Botão e campo do link no topo
    st.subheader("🔗 Cole o link da corrida do Racing Post")
    url = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/...")

    if st.button("Analisar Corrida", type="primary") and url:
        dogs, meta, meta_info = extrair_dados_racingpost(url)
        if dogs:
            st.session_state["dib_data"] = (dogs, meta, meta_info)
            # Atualiza os valores padrão na sessão para preencher a barra lateral
            st.session_state["s_pista"] = meta_info.get("pista", "")
            st.session_state["s_hora"] = meta_info.get("hora", "")
            st.session_state["s_race"] = meta_info.get("race", "")
            st.session_state["s_classe"] = meta_info.get("classe", "")
            st.session_state["s_pp"] = meta_info.get("post_pick", "")

    # Barra lateral com os inputs preenchidos automaticamente (ou via session_state)
    with st.sidebar:
        st.header("Dados da corrida")
        pista = st.text_input("Pista", value=st.session_state.get("s_pista", ""))
        hora = st.text_input("Horário da pista (ex.: 5:24)", value=st.session_state.get("s_hora", ""))
        race = st.text_input("Race nº", value=st.session_state.get("s_race", ""))
        classe = st.text_input("Classe de hoje (ex.: A3)", value=st.session_state.get("s_classe", ""))
        dist_in = st.number_input("Distância de hoje (m, 0 = detectar)", 0, 1000, 0)
        pp_in = st.text_input("Post Pick (ex.: 2-4-6)", value=st.session_state.get("s_pp", ""))

    if "dib_data" not in st.session_state:
        st.info("👈 Cole o link do Racing Post acima e clique em **Analisar Corrida** para carregar os dados e as projeções.")
    else:
        dogs, meta, meta_info = st.session_state["dib_data"]
        all_runs = [r for d in dogs for r in d["runs"] if r["dist"]]
        dist = float(dist_in) if dist_in else (pd.Series([r["dist"] for r in all_runs]).mode().iloc[0] if all_runs else 0)
        if not dist:
            st.error("Não consegui detectar a distância. Preencha na barra lateral.")
            mostrar_diagnostico(dogs, meta)
            return
        today = parse_date(meta["r_date"])
        
        # Usa a classe da barra lateral ou a detectada
        cls_atual = classe or meta_info.get("classe", "")
        ctx = {"dist": dist, "today": today, "classe_n": grade_num(cls_atual),
               "post_pick": [int(x) for x in re.findall(r"\d", pp_in)]}
        
        ds = [analisar_galgo(d, ctx) for d in dogs]
        rank = finalizar(ds, ctx)
        ds.sort(key=lambda d: d["trap"])

        tab_a, tab_d = st.tabs(["📋 Análise", "🔎 Diagnóstico e dados brutos"])
        with tab_a:
            br = hora_br(hora)
            tit = f"{pista} {hora} (BR {br})" if hora else pista
            st.markdown(f"### {tit} · Race {race} · {cls_atual} · {int(dist)}m · POST PICK: {pp_in or '-'}")
            st.markdown("#### Planilha de Projeção")
            st.markdown(tabela_projecao(ds), unsafe_allow_html=True)
            st.markdown("**Classificação geral:** " + classificacao(rank))
            s1, s2, s3 = montar_avbs(rank, ctx)
            tabela_avb(s1, "1ª Planilha — AVB do Alvo 🎯 (Força ≥ 50)", ctx)
            tabela_avb(s2, "2ª Planilha — AVB Principal (Elite, Força ≥ 50)", ctx)
            tabela_avb(s3, "3ª Planilha — AVB Secundário (Elite, Força 45,0 a 49,9)", ctx)
            st.markdown("#### Observações")
            st.markdown(observacoes(rank))
        with tab_d:
            mostrar_diagnostico(dogs, meta)

if __name__ == "__main__":
    main()