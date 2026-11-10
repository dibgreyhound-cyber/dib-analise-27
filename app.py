# -*- coding: utf-8 -*-
"""
DIB 2.7 - Analise de corridas de galgos (Streamlit)
- Atualizado com as novas regras de Overall, Fatores, Médias Simples, Travas e Probabilidade Normal (CDF).
- Corrigido erro de extração JSON do Racing Post (Headers e Tratamento de Exceção).
"""
import re
import html
import math
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st

# =====================================================================
# CONFIGURACAO GLOBAL E REGRAS (DIB 2.7 ATUALIZADO)
# =====================================================================

CFG = {
    "N_RUNS": 5,                       # Últimas 5 corridas lidas
    "N_CORREDORES": 6,                 # Para cálculo de Recuperação
    "CAT_BONUS": 2.0,                  # Desceu de classe +2 / subiu -2
    "TRAFFIC_ADJ": {"baulk": 0.20, "crd": 0.10, "bmp": 0.10, "fcd": 0.10},
    
    # Pontuações de Fatores
    "PERFIL_PTS": {"Limpo": 3.0, "Irregular": 2.0, "Trombador": 1.0},
    "REMARKS_PTS": {"early": 1.0, "slowaway": -1.0, "firstbend": -1.0},
    "TRAP_VAZIA": 1.0, 
    "TRAFEGO_SEVERO": -2.0,
    
    # Travas
    "CONF_MIN_VENCEDOR": 60.0,
    
    # Escalas do Overall (Realista)
    "VEL_PTS": {"tadj": 80, "mtime": 60, "msplit": 30, "ritmo": 30},
    "CONSIST_PTS": 30,
    "PICO_PTS": 20,
    "RECUP_PTS": 20,
}

FIELD_MAP = {
    "date": ["raceTime", "raceDate", "date"],
    "track": ["trackName", "track"],
    "dist": ["distMetres", "distance", "dist", "raceDistance"],
    "grade": ["raceClass", "raceGrade", "grade", "raceClassDesc"],
    "trap": ["trapNum", "trap"],
    "split": ["sectionalTime", "split"],
    "bends": ["bndPos", "bends"],
    "fin": ["outcomeDesc", "fin", "finPos"],
    "by": ["distBtn", "by", "beatenDistance", "btnDist"],
    "wntm": ["winTimeS", "winTime", "wnTm", "winnerTime"],
    "gng": ["goingType", "gng", "going"],
    "weight": ["weight", "dogWeight", "wght"],
    "remarks": ["closeUpCmnt", "remarks"],
    "caltm": ["calcRTimes", "calTm", "calcTime"],
}

TRAP_EMOJI = {1: "🟥", 2: "🟦", 3: "⬜", 4: "⬛", 5: "🟧", 6: "🔳"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# =====================================================================
# UTILIDADES DE EXTRAÇÃO E PARSING
# =====================================================================

def pick(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default

def to_float(x):
    if x is None: return None
    try:
        s = re.sub(r"[^\d.\-+]", "", str(x).strip().replace(",", "."))
        return float(s) if s not in ("", "+", "-", ".") else None
    except Exception:
        return None

def fin_num(x):
    m = re.search(r"\d+", str(x or ""))
    return int(m.group()) if m else None

def parse_lengths(x):
    if x in (None, ""): return None
    s = str(x).strip().lower()
    words = {"shd": 0.1, "hd": 0.2, "nk": 0.3, "dist": 30.0, "dis": 30.0}
    if s in words: return words[s]
    m = re.fullmatch(r"(\d+)?\s*(\d+)/(\d+)", s)
    if m: return float(m.group(1) or 0) + int(m.group(2)) / int(m.group(3))
    s = s.replace("¼", ".25").replace("½", ".5").replace("¾", ".75")
    try: return float(s)
    except Exception: return None

def bends_digits(b):
    return [int(c) for c in str(b or "") if c.isdigit()]

def grade_num(g):
    m = re.fullmatch(r"A(\d{1,2})", str(g or "").strip().upper())
    return int(m.group(1)) if m else None

def parse_date(s):
    if not s: return None
    s = str(s)[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try: return datetime.strptime(s, fmt)
        except Exception: pass
    return None

RE_TRAF = re.compile(r"(crd|bmp|blk)")
RE_NOFREE = re.compile(r"(crd|bmp|blk|baulk|fcd-?ck|evch|mvdoff)")

def parts_of(rem):
    for tok in re.split(r"[,\s]+", str(rem or "").lower()):
        if tok:
            for p in tok.split("-"):
                if p: yield p

def count_traf(rem):
    return sum(1 for p in parts_of(rem) if RE_TRAF.search(p))

def not_free(rem):
    return bool(RE_NOFREE.search(str(rem or "").lower()))

def first_bend_traffic(rem):
    s = str(rem or "").lower()
    if "baulk" in s: return True
    return any(RE_TRAF.search(p) and "1" in re.findall(r"\d", p) for p in parts_of(rem))

def wmean(vals):
    valid = [v for v in vals if v is not None]
    return float(np.mean(valid)) if valid else None

def traffic_penalty(rem):
    s = str(rem or "").lower()
    for key in ("baulk", "crd", "bmp", "fcd"):
        if key in s and key in CFG["TRAFFIC_ADJ"]:
            return CFG["TRAFFIC_ADJ"][key] if key == "baulk" else max(
                CFG["TRAFFIC_ADJ"][k] for k in ("crd", "bmp", "fcd") if k in s)
    return 0.0

def norm_run(f):
    g = lambda k: pick(f, FIELD_MAP[k])
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

# =====================================================================
# EXTRAÇÃO RACING POST (CORRIGIDO)
# =====================================================================

def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)
        if not race_id_match or not r_date_match:
            st.error("Link inválido. Precisa ter 'race_id' e 'r_date'.")
            return None, None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://greyhoundbet.racingpost.com/",
        }
        
        with st.spinner("Buscando dados no Racing Post..."):
            api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={race_id_match.group(1)}&r_date={r_date_match.group(1)}&blocks=form"
            
            resp = requests.get(api_url, headers=headers, timeout=15)
            
            if resp.status_code != 200:
                st.error(f"Erro na API do Racing Post (Status {resp.status_code}). O site pode estar bloqueando temporariamente.")
                return None, None
            
            try:
                data = resp.json()
            except json.JSONDecodeError:
                st.error("Erro: O Racing Post não retornou dados válidos (JSON). Tente novamente em alguns segundos.")
                return None, None

        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado encontrado para esta corrida.")
            return None, None
            
        out = []
        for dog in dogs:
            out.append({
                "name": dog.get("dogName", "Desconhecido"),
                "trap": fin_num(dog.get("trapNum")) or 0,
                "peso_atual": to_float(dog.get("weight")),
                "runs": [norm_run(f) for f in dog.get("forms", [])],
            })
            
        meta = {"r_date": r_date_match.group(1)}
        return out, meta
    except Exception as e:
        st.error(f"Erro inesperado na extração: {e}")
        return None, None

# =====================================================================
# CÁLCULOS DIB 2.7
# =====================================================================

def oficial(r, ctx):
    return (grade_num(r["grade"]) is not None and r["dist"] is not None
            and abs(r["dist"] - ctx["dist"]) < 1 and r["caltm"] is not None)

def analisar_galgo(dog, ctx):
    runs = sorted(dog["runs"], key=lambda r: r["date"] or datetime.min, reverse=True)[:CFG["N_RUNS"]]
    R = [r for r in runs if oficial(r, ctx)]
    
    d = {"name": dog["name"], "trap": dog["trap"], "runs": runs, "val": R, "nd": not R,
         "conf": min(100.0, len(R) * 20.0)}
    
    ultima_any = runs[0] if runs else None
    d["dias"] = (ctx["today"] - ultima_any["date"]).days if ultima_any and ultima_any["date"] else 0
    
    # Trava de Forma: Última é T E tem >= 2 T no histórico
    d["forma_trial"] = False
    if ultima_any and re.match(r"^T", ultima_any["grade"] or ""):
        count_t = sum(1 for r in runs if re.match(r"^T", r["grade"] or ""))
        if count_t >= 2:
            d["forma_trial"] = True

    if not R: return d

    # Categoria
    today_n = ctx.get("classe_n")
    last_n = grade_num(R[0]["grade"])
    base = 16.0 - (today_n if today_n else last_n)
    mod = 0.0
    if today_n and last_n:
        mod = CFG["CAT_BONUS"] if today_n > last_n else (-CFG["CAT_BONUS"] if today_n < last_n else 0.0)
    d["cat_mod"], d["cat"] = mod, base + mod

    # Peso e Dias (Apenas visual)
    last_w = R[0]["weight"]
    atual = dog.get("peso_atual") or last_w
    d["peso"] = atual

    # Tempos e Splits (Média Simples)
    d["split"], d["time"] = R[0]["split"], R[0]["caltm"]
    d["msplit"] = wmean([r["split"] for r in R])
    d["mtime"] = wmean([r["caltm"] for r in R])
    d["ritmo"] = d["mtime"] - d["msplit"] if d["mtime"] and d["msplit"] else None
    
    # Time Ajustado (Sem going, com tráfego escalonado)
    adj_times = []
    for r in R:
        t_pen = traffic_penalty(r["remarks"])
        dist_scale = (r["dist"] - 300) / 1000.0 if t_pen > 0 else 0.0
        adj_times.append(r["caltm"] - (t_pen + dist_scale))
    d["tadj"] = float(np.mean(adj_times)) if adj_times else None
    
    # Consistência e Pico
    cal = [r["caltm"] for r in R]
    d["sd"] = float(np.std(cal)) if len(cal) > 1 else 0.0
    d["pico"] = min(cal) if cal else None

    # Recuperação (Blindada, 0 se não tiver)
    recs = []
    for r in R:
        b = bends_digits(r["bends"])
        if b and r["fin"] and not not_free(r["remarks"]):
            recs.append((b[0] - r["fin"]) / CFG["N_CORREDORES"] * 100.0)
    d["rec"] = float(np.mean(recs)) if recs else 0.0
    tag = "Ganhou" if d["rec"] > 0.005 else ("Perdeu" if d["rec"] < -0.005 else "Manteve")
    d["rec_txt"] = f"{d['rec']:+.2f}% ({tag})"

    # Perfil
    n_traf = sum(count_traf(r["remarks"]) for r in R)
    d["perfil"] = "Limpo" if n_traf <= 1 else ("Irregular" if n_traf == 2 else "Trombador")
    
    # Fatores (Acumulados nas últimas 5)
    d["early_cnt"] = sum(1 for r in R if any(re.match(r"^(ep|ald|snld|ld)", t) for t in re.split(r"[,\s]+", str(r["remarks"]).lower())))
    d["saw_cnt"] = sum(1 for r in R if any(t.startswith("saw") or t.startswith("vsaw") for t in re.split(r"[,\s]+", str(r["remarks"]).lower())))
    d["fbt_cnt"] = sum(1 for r in R if first_bend_traffic(r["remarks"]))

    return d

def finalizar(ds, ctx):
    ok = [d for d in ds if not d["nd"]]
    vac = [t for t in range(1, 7) if t not in {d["trap"] for d in ds}]
    
    # Top 3 Split
    ms_rank = sorted([d for d in ok if d["msplit"]], key=lambda x: x["msplit"])
    top3_ms = {d["name"] for d in ms_rank[:3]}

    # Helper para pontos proporcionais
    def pts_prop(key, maxp, d, invert=True):
        vals = [x[key] for x in ok if x.get(key) is not None]
        if d.get(key) is None or not vals: return 0.0
        lo, hi = min(vals), max(vals)
        if hi == lo: return float(maxp)
        if invert: # Menor é melhor (Tempo)
            return maxp * (hi - d[key]) / (hi - lo)
        else: # Maior é melhor (Recuperação)
            return maxp * (d[key] - lo) / (hi - lo)

    for d in ok:
        pts_cat = d["cat"] * 2
        pts_perfil = CFG["PERFIL_PTS"][d["perfil"]]
        
        # Velocidade Base (200 pts)
        vel = (pts_prop("tadj", CFG["VEL_PTS"]["tadj"], d) + 
               pts_prop("mtime", CFG["VEL_PTS"]["mtime"], d) + 
               pts_prop("msplit", CFG["VEL_PTS"]["msplit"], d) + 
               pts_prop("ritmo", CFG["VEL_PTS"]["ritmo"], d))
        
        # Consistência e Pico
        pts_consist = pts_prop("sd", CFG["CONSIST_PTS"], d, invert=True)
        pts_pico = pts_prop("pico", CFG["PICO_PTS"], d, invert=True)
        
        # Recuperação
        pts_rec = pts_prop("rec", CFG["RECUP_PTS"], d, invert=False)
        
        # Fatores
        f = []
        if d["early_cnt"] > 0: f.append(("Early Pace", d["early_cnt"] * CFG["REMARKS_PTS"]["early"]))
        if d["saw_cnt"] > 0: f.append(("Slow Away", d["saw_cnt"] * CFG["REMARKS_PTS"]["slowaway"]))
        if d["fbt_cnt"] > 0: f.append(("First Bend Traffic", d["fbt_cnt"] * CFG["REMARKS_PTS"]["firstbend"]))
        if any(abs(d["trap"] - v) == 1 for v in vac): f.append(("Trap Vazia", CFG["TRAP_VAZIA"]))
        
        # Tráfego Severo
        if d["perfil"] == "Trombador" and d["trap"] in [1,2,3,4,5] and d["name"] not in top3_ms:
            f.append(("Tráfego Severo", CFG["TRAFEGO_SEVERO"]))
            
        pts_fat = sum(v for _, v in f)
        d["fatores"] = f
        
        # Overall Final
        d["overall"] = vel + pts_cat + pts_perfil + pts_consist + pts_pico + pts_rec + pts_fat

    ok.sort(key=lambda x: -x["overall"])
    for i, d in enumerate(ok, 1):
        d["pos"] = i
        d["bloqueado"] = d["conf"] < CFG["CONF_MIN_VENCEDOR"] or d["forma_trial"]
        d["alvo"] = (d["name"] not in top3_ms) and (d["rec"] <= 0)
        d["elegivel"] = not d["bloqueado"]
        
    return ok, top3_ms

# =====================================================================
# AVB E PROBABILIDADE
# =====================================================================

def calc_prob(V, D, ctx):
    t_V = V["tadj"]
    t_D = D["tadj"]
    
    if V["trap"] in ctx["post_pick"]: t_V -= 0.05
    if V["trap"] in [1,2,3]: t_V -= 0.04
    if any(abs(V["trap"] - v) == 1 for v in ctx["vazias"]): t_V -= 0.03
    if V["perfil"] == "Trombador" and V["trap"] in [1,2,3,4,5] and V["name"] not in ctx["top3_ms"]: t_V += 0.05
    
    sd_V = max(V["sd"], 0.05)
    sd_D = max(D["sd"], 0.05)
    
    z = (t_D - t_V) / math.sqrt(sd_V**2 + sd_D**2)
    prob = 0.5 * (1 + math.erf(z / math.sqrt(2))) * 100
    return prob

def montar_avbs(rank, ctx):
    elig = [d for d in rank if d["elegivel"]]
    s1, s2, s3 = [], [], []
    
    # Matchmaking de Elite (para estrela)
    elite_pairs = set()
    for k, slots in enumerate([(3,4), (4,5), (5,6)]):
        if k < len(elig):
            V = elig[k]
            for pos in slots:
                if pos <= len(rank) and rank[pos-1]["elegivel"]:
                    elite_pairs.add((V["name"], rank[pos-1]["name"]))

    # Todos vs Todos
    for V in elig:
        for D in elig:
            if V["name"] == D["name"]: continue
            
            prob = calc_prob(V, D, ctx)
            if prob < 55.0: continue
            
            # Funil de Excelência
            if V["overall"] <= D["overall"]: continue
            if V["name"] not in ctx["top3_ms"]: continue
            if V["tadj"] > D["tadj"] - 0.03: continue
            if V["mtime"] > D["mtime"] - 0.03: continue
            if V["ritmo"] > D["ritmo"]: continue
            if V["rec"] < D["rec"]: continue
            
            # Distribuição nas Planilhas
            is_star = (V["name"], D["name"]) in elite_pairs
            
            if D["alvo"] and prob >= 65.0:
                s1.append((V, D, prob, is_star))
            elif not D["alvo"] and prob >= 65.0:
                s2.append((V, D, prob, False))
            elif not D["alvo"] and 55.0 <= prob < 65.0:
                s3.append((V, D, prob, False))
                
    return sorted(s1, key=lambda x: -x[2]), sorted(s2, key=lambda x: -x[2]), sorted(s3, key=lambda x: -x[2])

# =====================================================================
# EXIBIÇÃO E VISUAL
# =====================================================================

def get_rank_html(val, rank, invert=False):
    if val is None or rank is None: return "-"
    txt = f"{val:.3f}" if val < 10 else f"{val:.2f}"
    sup = {1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶"}.get(rank, "")
    color = ""
    if invert: # Maior é melhor (Recuperação)
        if rank == 1: color = "color:green;font-weight:bold"
        elif rank >= 5: color = "color:red"
    else: # Menor é melhor (Tempos)
        if rank == 1: color = "color:green;font-weight:bold"
        elif rank >= 5: color = "color:red"
    return f"<span style='{color}'>{txt}{sup}</span>"

def tbl(headers, rows):
    h = "".join(f"<th>{x}</th>" for x in headers)
    out = []
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    return f"<div style='overflow-x:auto;'><table style='width:100%; border-collapse: collapse; text-align:center; font-size:13px;'><tr>{h}</tr>{''.join(out)}</table></div>"

def nome_marcado(d):
    n = html.escape(d["name"])
    if d["bloqueado"]: n += " 🚫"
    if d["alvo"]: n = "🎯 " + n
    return n

def trap_label(d):
    return f"{TRAP_EMOJI.get(d['trap'], '')} {d['trap']}"

def tabela_projecao(ds):
    cols = ["split", "time", "tadj", "msplit", "mtime", "ritmo", "rec"]
    rk = {c: [None]*len(ds) for c in cols}
    for c in cols:
        vals = [(i, d[c]) for i, d in enumerate(ds) if d.get(c) is not None]
        vals.sort(key=lambda x: x[1], reverse=(c == "rec"))
        for rank, (i, _) in enumerate(vals, 1):
            rk[c][i] = rank

    rows = []
    for i, d in enumerate(ds):
        if d["nd"]:
            rows.append([trap_label(d), nome_marcado(d), "-"] * 8)
            continue
            
        fat = "<br>".join(f"{k} ({v:+.1f})" for k, v in d["fatores"]) or "-"
        perfil_e = {"Limpo": "✅", "Irregular": "⚠️", "Trombador": "🔴"}[d["perfil"]]
        medal = MEDALS.get(d["pos"], f"{d['pos']}º")
        
        dias_txt = f"{d['dias']} ⚠️" if d['dias'] > 10 else str(d['dias'])
        
        rows.append([
            trap_label(d), nome_marcado(d), f"{medal} {d['overall']:.1f}",
            f"{d['cat']:.1f} ({d['cat_mod']:+.0f})", fat, f"{perfil_e} {d['perfil']}",
            "-".join((r["grade"] or "?") for r in d["runs"]),
            f"{d['peso']:.1f}", dias_txt,
            get_rank_html(d["split"], rk["split"][i]),
            get_rank_html(d["time"], rk["time"][i]),
            get_rank_html(d["tadj"], rk["tadj"][i]),
            get_rank_html(d["msplit"], rk["msplit"][i]),
            get_rank_html(d["mtime"], rk["mtime"][i]),
            get_rank_html(d["ritmo"], rk["ritmo"][i]),
            get_rank_html(d["rec"], rk["rec"][i], invert=True) + f"<br><small>{d['rec_txt'].split()[1]}</small>",
            f"{d['conf']:.0f}%"
        ])
    heads = ["Trap", "Galgo", "Overall", "Cat", "Fatores", "Perfil", "Grades", "Peso", "Dias", "Split", "Time", "Time Ajust.", "Méd. Split", "Méd. Time", "Ritmo", "Recup. Média", "Conf."]
    return tbl(heads, rows)

def tabela_avb(lista, titulo):
    st.markdown(f"#### {titulo}")
    if not lista:
        st.info("Nenhum AVB nesta categoria.")
        return
    rows = []
    for i, (V, D, prob, star) in enumerate(lista):
        if i > 0:
            rows.append(["<hr style='border:0;border-top:1px solid #ccc;margin:0'>"] + ["-"] * 15)
            
        avb_cell = f"{'⭐ ' if star else ''}{trap_label(V)}<br>{trap_label(D)}"
        pv = lambda x: f"{x:.3f}" if x < 10 else f"{x:.2f}"
        
        rows.append([
            avb_cell,
            f"{V['overall']:.1f}<br>{D['overall']:.1f} ({V['overall']-D['overall']:+.1f})",
            f"{V['cat']:.1f}<br>{D['cat']:.1f}",
            f"{V['perfil']}<br>{D['perfil']}",
            "-".join((r["grade"] or "?") for r in V["runs"]) + "<br>" + "-".join((r["grade"] or "?") for r in D["runs"]),
            f"{V['peso']:.1f}<br>{D['peso']:.1f}",
            f"{V['dias']}<br>{D['dias']}",
            f"{pv(V['split'])}<br>{pv(D['split'])}",
            f"{pv(V['time'])}<br>{pv(D['time'])}",
            f"{pv(V['tadj'])}<br>{pv(D['tadj'])}",
            f"{pv(V['msplit'])}<br>{pv(D['msplit'])}",
            f"{pv(V['mtime'])}<br>{pv(D['mtime'])}",
            f"{pv(V['ritmo'])}<br>{pv(D['ritmo'])}",
            f"{V['rec']:+.1f}%<br>{D['rec']:+.1f}%",
            f"{V['conf']:.0f}%<br>{D['conf']:.0f}%",
            f"<b>{prob:.1f}%</b><br>{100-prob:.1f}% ({prob - (100-prob):+.1f}%)"
        ])
    heads = ["AvB", "Overall", "Cat", "Perfil", "Grades", "Peso", "Dias", "Split", "Time", "Time Ajust.", "Méd. Split", "Méd. Time", "Ritmo", "Recup.", "Conf.", "Probabilidade"]
    st.markdown(tbl(heads, rows), unsafe_allow_html=True)

# =====================================================================
# APP STREAMLIT MAIN
# =====================================================================

def main():
    st.set_page_config(page_title="DIB 2.7 Pro", layout="wide")
    st.title("🐾 Análise DIB 2.7 - Alta Performance")

    url = st.text_input("Link da corrida (Racing Post)", placeholder="https://greyhoundbet...")
    
    with st.sidebar:
        st.header("Dados da Corrida")
        classe = st.text_input("Classe de hoje (ex: A4)", value="A4")
        dist_in = st.number_input("Distância (m)", value=480)
        pp_in = st.text_input("Post Pick (ex: 1-2-3)", value="")
        
    if st.button("Analisar", type="primary") and url:
        dogs, meta = extrair_dados_racingpost(url)
        if dogs:
            dist = float(dist_in)
            today = parse_date(meta["r_date"])
            ctx = {
                "dist": dist, "today": today, "classe_n": grade_num(classe),
                "post_pick": [int(x) for x in re.findall(r"\d", pp_in)],
                "vazias": [t for t in range(1, 7) if t not in {d["trap"] for d in dogs}]
            }
            
            ds = [analisar_galgo(d, ctx) for d in dogs]
            rank, top3_ms = finalizar(ds, ctx)
            ctx["top3_ms"] = top3_ms
            
            ds.sort(key=lambda d: d["trap"])
            
            st.markdown(f"### {classe} · {int(dist)}m · POST PICK: {pp_in or '-'}")
            
            st.markdown("#### Planilha de Projeção")
            st.markdown(tabela_projecao(ds), unsafe_allow_html=True)
            
            st.markdown("**Classificação:** " + " > ".join(f"{MEDALS.get(d['pos'], str(d['pos'])+'º')} {TRAP_EMOJI[d['trap']]} {d['trap']}" for d in rank))
            
            s1, s2, s3 = montar_avbs(rank, ctx)
            tabela_avb(s1, "1ª Planilha — AVB do Alvo 🎯 (Prob ≥ 65%)")
            tabela_avb(s2, "2ª Planilha — AVB Principal (Prob ≥ 65%)")
            tabela_avb(s3, "3ª Planilha — AVB Secundário (Prob 55% - 64.9%)")

if __name__ == "__main__":
    main()