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
    return None


# ---- remarks ----


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


def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)
        if not race_id_match or not r_date_match:
            st.error("Link inválido. Precisa ter 'race_id' e 'r_date'.")
            return None, None
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
            return None, None
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
        return out, {"r_date": r_date_str, "raw_first": dogs[0]}
    except Exception as e:
        st.error(f"Erro: {e}")
        return None, None


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
    retu