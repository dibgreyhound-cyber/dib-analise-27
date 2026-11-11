# -*- coding: utf-8 -*-
import re
import html
import math
import json
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import streamlit as st

# =====================================================================
# DICIONÁRIO DE REMARKS (TABELA DO MARKO)
# =====================================================================
DICIONARIO_REMARKS = {
    "ald": "Liderou Sempre", "awk": "Desajeitado", "blk": "Trombada Forte",
    "bmp": "Trombou na Curva", "chl": "Desafiado na Curva", "clrrn": "Corrida Limpa",
    "crd": "Truncado na Curva", "crdnrln": "Truncado no Final", "crdrnln": "Truncado na Reta",
    "crdrnup": "Truncado no Início", "crmp": "Espaço Apertado", "disp": "Disputou",
    "dsp": "Disputou na Curva", "dis pld": "Liderou com Disputa", "ep": "Ritmo Acelerado",
    "evch": "Evitou Choque", "fcd": "Forçado a Algo", "fcdck": "Forçado na Curva",
    "fell": "Caiu", "hldon": "Posição Mantida", "imp": "Impedido", "jmp": "Saltou",
    "jmplate": "Saltou Atrasado", "ko": "Derrubado", "lame": "Manco", "ld": "Liderou a Curva",
    "ldnrln": "Liderou na Reta", "in": "Linha de Chegada", "mid": "Corre pelo Meio",
    "msdbrk": "Passou Reto", "on": "Até o Final", "qaw": "Largada Rápida", "rls": "Corre por Dentro",
    "rnln": "Reta Linha", "rnon": "Manteve Galope", "rnonwll": "Galope até o Final",
    "rnup": "Distância Trap 1", "saw": "Largada Lenta", "snled": "Liderou desde o Início",
    "stmb": "Tropeçou", "strfn": "Chegada Forte", "stt": "Início", "struck": "Atingido",
    "styd": "Ficou", "turnedin trps": "Ficou na Trap", "vsaw": "Largada Muito Lenta",
    "vw": "Corredor Aberto", "w": "Curva Ampla"
}

# =====================================================================
# CONFIGURAÇÃO GLOBAL (DIB 3.3 - DUELO DIRETO + CONFLITO DE PACE)
# =====================================================================
CFG = {
    "N_RUNS": 5, "N_CORREDORES": 6, "CAT_BONUS": 2.0,
    "TRAFFIC_ADJ": {"baulk": 0.20, "crd": 0.10, "bmp": 0.10, "fcd": 0.10},
    "PERFIL_PTS": {"Limpo": 5.0, "Irregular": 2.0, "Trombador": 0.0},
    "REMARKS_PTS": {"early": 1.0, "slowaway": -1.0, "firstbend": -1.0},
    "TRAP_VAZIA": 1.0, "TRAFEGO_SEVERO": -2.0, "CONF_MIN_VENCEDOR": 60.0,
    "VEL_PTS": {"tadj": 60, "mtime": 40, "msplit": 60, "ritmo": 40},
    "CONSIST_PTS": 30, "PICO_PTS": 20, "RECUP_PTS": 20,
}

FIELD_MAP = {
    "date": ["raceTime", "raceDate", "date"], "track": ["trackName", "track"],
    "dist": ["distMetres", "distance", "dist", "raceDistance"],
    "grade": ["raceClass", "raceGrade", "grade", "raceClassDesc"],
    "trap": ["trapNum", "trap"], "split": ["sectionalTime", "split"],
    "bends": ["bndPos", "bends"], "fin": ["outcomeDesc", "fin", "finPos"],
    "by": ["distBtn", "by", "beatenDistance", "btnDist"],
    "wntm": ["winTimeS", "winTime", "wnTm", "winnerTime"],
    "gng": ["goingType", "gng", "going"], "weight": ["weight", "dogWeight", "wght"],
    "remarks": ["closeUpCmnt", "remarks"], "caltm": ["calcRTimes", "calTm", "calcTime"],
}

TRAP_EMOJI = {1: "🟥", 2: "🟦", 3: "⬜", 4: "⬛", 5: "🟧", 6: "🔳"}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://greyhoundbet.racingpost.com/",
}

RE_TRAF = re.compile(r"(awk|blk|bmp|crmp|evch|fcd|fell|ko|msdbrk|saw|stmb|struck|vsaw|crd|imp|lame)")
RE_NOFREE = re.compile(r"(awk|blk|bmp|crmp|evch|fcd|fell|ko|msdbrk|saw|stmb|struck|vsaw|crd|imp|lame|baulk)")

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
    except Exception: return None

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

def parts_of(rem):
    for tok in re.split(r"[,\s]+", str(rem or "").lower()):
        if tok:
            for p in tok.split("-"):
                if p: yield p

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
    if "baulk" in s: return True
    return any(RE_TRAF.search(p) and "1" in re.findall(r"\d", p) for p in parts_of(rem))

HINTS = {
    "dist": (("dist", "metre", "meter"), ("btn", "beat", "by")),
    "grade": (("class", "grade"), ()), "by": (("btn", "beaten"), ()),
    "wntm": (("win", "time"), ()),
}

def pick_fb(f, k):
    v = pick(f, FIELD_MAP[k])
    if v is not None or k not in HINTS: return v
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
        "date": parse_date(g("date")), "date_str": str(g("date") or "")[:10],
        "track": str(g("track") or ""), "dist": to_float(g("dist")),
        "grade": str(g("grade") or "").strip().upper(), "trap": fin_num(g("trap")),
        "split": to_float(g("split")), "bends": str(g("bends") or ""),
        "fin": fin_num(g("fin")), "by": parse_lengths(g("by")),
        "wntm": to_float(g("wntm")), "gng": g("gng"),
        "weight": to_float(g("weight")), "remarks": str(g("remarks") or ""),
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
        if any(x in kl for x in ("btn", "beat", "weight", "time", "id")): continue
        nums = [to_float(v) for v in vs]
        if all(n is not None and 150 <= n <= 900 for n in nums) and len(set(nums)) <= 6:
            if k not in FIELD_MAP["dist"]: FIELD_MAP["dist"].insert(0, k)
            break
    for k, vs in vals.items():
        if sum(1 for v in vs if GRADE_RE.match(str(v).strip().upper())) >= 0.8 * len(vs):
            if k not in FIELD_MAP["grade"]: FIELD_MAP["grade"].insert(0, k)
            break

def extrair_metadados_json(data, info_card, dogs):
    info = {"pista": "", "hora": "", "race": "", "classe": "", "post_pick": ""}
    fontes = [info_card] if isinstance(info_card, dict) else []
    for src in [data]:
        if isinstance(src, dict):
            fontes.append(src)
            if isinstance(src.get("race"), dict): fontes.append(src["race"])
            if isinstance(src.get("form"), dict):
                fontes.append(src["form"])
                if isinstance(src["form"].get("race"), dict): fontes.append(src["form"]["race"])
    
    for src in fontes:
        pista = pick(src, ["trackName", "track", "meetingName", "courseName"])
        if pista: info["pista"] = str(pista).strip(); break
    if not info["pista"] and dogs and dogs[0].get("runs"):
        info["pista"] = str(dogs[0]["runs"][0].get("track", "Desconhecida")).strip()
        
    for src in fontes:
        for k in ["offTime", "scheduledTime", "displayTime", "time", "raceTime"]:
            val = src.get(k)
            if val:
                m = re.search(r"\b([1-9]|1[0-2]):\d{2}\b", str(val))
                if m: info["hora"] = m.group(0); break
        if info["hora"]: break

    for src in fontes:
        r_num = pick(src, ["raceNum", "raceNumber", "rNum", "raceNumberDesc", "number"])
        if r_num is not None:
            info["race"] = str(r_num).replace("Race", "").strip(); break

    for src in fontes:
        grade = pick(src, ["raceClass", "grade", "class", "raceClassDesc", "raceGrade"])
        if grade: info["classe"] = str(grade).strip().upper(); break
    if not info["classe"] and dogs and dogs[0].get("runs"):
        info["classe"] = str(dogs[0]["runs"][0].get("grade", "")).strip().upper()

    for src in fontes:
        pp = pick(src, ["postPick", "post_pick", "tips", "tip"])
        if pp:
            m = re.search(r"\b([1-6][-/.][1-6][-/.][1-6])\b", str(pp))
            if m:
                info["post_pick"] = m.group(1).strip().replace("/", "-").replace(".", "-"); break
            elif re.search(r"[1-6]", str(pp)):
                info["post_pick"] = str(pp).strip().replace("/", "-").replace(".", "-"); break
    return info

def extrair_dados_racingpost(url):
    try:
        if not url.startswith("http"):
            url = "https://greyhoundbet.racingpost.com/" + url

        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)
        if not race_id_match or not r_date_match:
            st.error("Não foi possível extrair o ID da corrida do link.")
            return None, None, None
        race_id, r_date_str = race_id_match.group(1), r_date_match.group(1)
        
        card_api_url = f"https://greyhoundbet.racingpost.com/card/race.sd?race_id={race_id}&r_date={r_date_str}"
        info_card = {}
        try:
            resp_card = requests.get(card_api_url, headers=HEADERS, timeout=10)
            if resp_card.status_code == 200:
                info_card = resp_card.json()
        except Exception: pass

        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={race_id}&r_date={r_date_str}&blocks=form"
        resp = requests.get(api_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado encontrado para esta corrida.")
            return None, None, None
            
        descobrir_chaves(dogs)
        out = []
        for dog in dogs:
            trap = fin_num(dog.get("trapNum"))
            runs = [norm_run(f) for f in dog.get("forms", [])]
            out.append({
                "name": dog.get("dogName", "Desconhecido"),
                "trap": trap or 0, "peso_atual": to_float(dog.get("weight")), "runs": runs,
            })
            
        existing_traps = {d["trap"] for d in out}
        for t in range(1, 7):
            if t not in existing_traps:
                out.append({"name": "vacant", "trap": t, "peso_atual": None, "runs": []})
        out.sort(key=lambda x: x["trap"])
            
        meta_info = extrair_metadados_json(data, info_card, out)
        return out, {"r_date": r_date_str, "raw_first": dogs[0]}, meta_info
    except Exception as e:
        st.error(f"Erro ao extrair dados: {e}")
        return None, None, None

def oficial(r, ctx):
    return (grade_num(r["grade"]) is not None and r["dist"] is not None
            and abs(r["dist"] - ctx["dist"]) < 1 and r["caltm"] is not None and r["caltm"] > 0)

def analisar_galgo(dog, ctx):
    if dog.get("name") == "vacant":
        return {"name": "vacant", "trap": dog["trap"], "runs": [], "val": [], "nd": True,
                "conf": 0.0, "bloqueado": False, "alvo": False, "pos": 0, "elegivel": False}
                
    runs = sorted(dog["runs"], key=lambda r: r["date"] or datetime.min, reverse=True)[:CFG["N_RUNS"]]
    R = [r for r in runs if oficial(r, ctx)]
    
    d = {"name": dog["name"], "trap": dog["trap"], "runs": runs, "val": R, "nd": not R,
         "conf": min(100.0, len(R) * 20.0), "bloqueado": False, "alvo": False, "pos": 0, "elegivel": False}
    
    ultima_any = runs[0] if runs else None
    d["dias"] = (ctx["today"] - ultima_any["date"]).days if ultima_any and ultima_any["date"] else 0
    
    d["forma_trial"] = False
    if ultima_any and re.match(r"^T", ultima_any["grade"] or ""):
        count_t = sum(1 for r in runs if re.match(r"^T", r["grade"] or ""))
        if count_t >= 2: d["forma_trial"] = True
    if not R: return d

    today_n = ctx.get("classe_n")
    last_n = grade_num(R[0]["grade"])
    base = 16.0 - (today_n if today_n else last_n)
    mod = 0.0
    if today_n and last_n:
        mod = CFG["CAT_BONUS"] if today_n > last_n else (-CFG["CAT_BONUS"] if today_n < last_n else 0.0)
    d["cat_mod"], d["cat"] = mod, base + mod

    d["peso"] = dog.get("peso_atual") or R[0]["weight"]
    d["split"], d["time"] = R[0]["split"], R[0]["caltm"]
    
    d["msplit"] = float(np.mean([r["split"] for r in R if r["split"] is not None])) if any(r["split"] for r in R) else None
    d["mtime"] = float(np.mean([r["caltm"] for r in R if r["caltm"] is not None])) if any(r["caltm"] for r in R) else None
    d["ritmo"] = d["mtime"] - d["msplit"] if d["mtime"] and d["msplit"] else None
    
    adj_times = [r["caltm"] - (traffic_penalty(r["remarks"]) + ((r["dist"] - 300) / 1000.0 if traffic_penalty(r["remarks"]) > 0 else 0.0)) for r in R]
    d["tadj"] = float(np.mean(adj_times)) if adj_times else None
    
    cal = [r["caltm"] for r in R]
    d["sd"] = float(np.std(cal)) if len(cal) > 1 else 0.0
    d["pico"] = min(cal) if cal else None

    recs = [(bends_digits(r["bends"])[0] - r["fin"]) / CFG["N_CORREDORES"] * 100.0 for r in R if bends_digits(r["bends"]) and r["fin"] and not not_free(r["remarks"])]
    d["rec"] = float(np.mean(recs)) if recs else 0.0
    d["rec_txt"] = f"{d['rec']:+.2f}% ({'Ganhou' if d['rec'] > 0.005 else ('Perdeu' if d['rec'] < -0.005 else 'Manteve')})"

    n_traf = sum(count_traf(r["remarks"]) for r in R)
    d["perfil"] = "Limpo" if n_traf <= 1 else ("Irregular" if n_traf == 2 else "Trombador")
    
    d["early_cnt"] = sum(1 for r in R if any(re.match(r"^(ep|ald|snld|ld)", t) for t in re.split(r"[,\s]+", str(r["remarks"]).lower())))
    d["saw_cnt"] = sum(1 for r in R if any(t.startswith("saw") or t.startswith("vsaw") for t in re.split(r"[,\s]+", str(r["remarks"]).lower())))
    d["fbt_cnt"] = sum(1 for r in R if first_bend_traffic(r["remarks"]))
    
    d["remarks_translated"] = []
    for r in R:
        for token in re.split(r"[,\s]+", str(r["remarks"]).lower()):
            if token in DICIONARIO_REMARKS:
                d["remarks_translated"].append(DICIONARIO_REMARKS[token])
                
    return d

def finalizar(ds, ctx):
    ok = [d for d in ds if not d["nd"]]
    vac = [t for t in range(1, 7) if t not in {d["trap"] for d in ds if d["name"] != "vacant"}]
    
    ms_rank = sorted([d for d in ok if d["msplit"]], key=lambda x: x["msplit"])
    top3_ms = {d["name"] for d in ms_rank[:3]}
    ctx["top3_ms"] = top3_ms
    
    ritmo_rank = sorted([d for d in ok if d["ritmo"]], key=lambda x: x["ritmo"])
    top3_ritmo = {d["name"] for d in ritmo_rank[:3]}
    ctx["top3_ritmo"] = top3_ritmo

    def pts_prop(key, maxp, d, invert=True):
        vals = [x[key] for x in ok if x.get(key) is not None]
        if d.get(key) is None or not vals: return 0.0
        lo, hi = min(vals), max(vals)
        if hi == lo: return float(maxp)
        return maxp * (hi - d[key]) / (hi - lo) if invert else maxp * (d[key] - lo) / (hi - lo)

    for d in ok:
        pts_cat, pts_perfil = d["cat"] * 2, CFG["PERFIL_PTS"][d["perfil"]]
        vel = (pts_prop("tadj", CFG["VEL_PTS"]["tadj"], d) + 
               pts_prop("mtime", CFG["VEL_PTS"]["mtime"], d) + 
               pts_prop("msplit", CFG["VEL_PTS"]["msplit"], d) + 
               pts_prop("ritmo", CFG["VEL_PTS"]["ritmo"], d))
        
        f = []
        if d["early_cnt"] > 0 and d["perfil"] == "Limpo": 
            f.append(("Ritmo Acelerado", d["early_cnt"] * 1.0))
        if d["saw_cnt"] > 0: 
            f.append(("Largada Lenta", d["saw_cnt"] * -1.0))
        if d["fbt_cnt"] > 0: 
            f.append(("Tráfego 1ª Curva", d["fbt_cnt"] * -1.0))
        if any(abs(d["trap"] - v) == 1 for v in vac): 
            f.append(("Trap Vazia", 1.0))
        if d["perfil"] == "Trombador" and d["trap"] in [1,2,3,4,5] and d["name"] not in top3_ms:
            f.append(("Tráfego Severo", -2.0))
            
        d["fatores"] = f
        d["overall"] = vel + pts_cat + pts_perfil + pts_prop("sd", CFG["CONSIST_PTS"], d, True) + pts_prop("pico", CFG["PICO_PTS"], d, True) + pts_prop("rec", CFG["RECUP_PTS"], d, False) + sum(v for _, v in f)

    ok.sort(key=lambda x: -x["overall"])
    for i, d in enumerate(ok, 1):
        d["pos"] = i
        d["bloqueado"] = d["conf"] < CFG["CONF_MIN_VENCEDOR"] or d["forma_trial"]
        d["alvo"] = (d["name"] not in top3_ms) and (d["rec"] <= 0)
        d["elegivel"] = not d["bloqueado"]
    return ok, top3_ms

# =====================================================================
# NOVO CÁLCULO DE AVB (DIB 3.3 - DUELO DIRETO + CONFLITO DE PACE)
# =====================================================================
def calc_prob(V, D, rank, ctx):
    prob = 50.0
    if V.get("tadj") is None or D.get("tadj") is None: return 50.0

    # 1. PILAR VELOCIDADE
    diff_tadj = D["tadj"] - V["tadj"]
    diff_mtime = D["mtime"] - V["mtime"] if D.get("mtime") is not None and V.get("mtime") is not None else 0
    pts_vel = ((diff_tadj + diff_mtime) / 0.10) * 4.0
    pts_vel = max(-15.0, min(15.0, pts_vel))
    prob += pts_vel
    
    # 2. PILAR LARGADA
    if V.get("msplit") and D.get("msplit"):
        diff_split = D["msplit"] - V["msplit"]
        pts_split = (diff_split / 0.05) * 3.0
        pts_split = max(-10.0, min(10.0, pts_split))
        prob += pts_split
        
    # 3. PILAR RITMO FINAL
    if V.get("ritmo") and D.get("ritmo"):
        diff_ritmo = D["ritmo"] - V["ritmo"]
        pts_ritmo = (diff_ritmo / 0.05) * 2.0
        pts_ritmo = max(-6.0, min(6.0, pts_ritmo))
        prob += pts_ritmo
        
    # 4. PILAR SEGURANÇA E RECUPERAÇÃO
    pts_seguranca = 0.0
    if V.get("rec") is not None and D.get("rec") is not None:
        diff_rec = V["rec"] - D["rec"]
        pts_seguranca += (diff_rec * 0.1)
        pts_seguranca = max(-5.0, min(5.0, pts_seguranca))
        
    val_perfil = {"Limpo": 0, "Irregular": 1, "Trombador": 2}
    diff_perfil = val_perfil.get(D["perfil"], 1) - val_perfil.get(V["perfil"], 1)
    pts_seguranca += (diff_perfil * 2.5)
    prob += pts_seguranca

    # 5. CONFLITO DE PACE (NOVA REGRA)
    top3_ms = ctx.get("top3_ms", set())
    top3_ritmo = ctx.get("top3_ritmo", set())
    epfs = [d for d in rank if d["name"] in top3_ms] # Cães com largada rápida no páreo

    if V["name"] in top3_ms:
        if D["name"] in top3_ms:
            prob -= 3.0 # Ambos são rápidos, vão brigar diretamente
        else:
            prob -= 5.0 # V vai ter que brigar com outro cão da prova pela ponta
    elif D["name"] in top3_ms:
        prob += 5.0 # D vai se atrapalhar brigando pela ponta

    if V["name"] in top3_ritmo and V["name"] not in top3_ms:
        if len(epfs) >= 2:
            prob += 5.0 # V é um "Closer" e há 2+ cães rápidos brigando na frente

    # Ajustes Táticos
    if V["trap"] in ctx["post_pick"]: prob += 2.0
    if V["trap"] in [1,2,3] and D["trap"] in [4,5,6]: prob += 2.0
    if any(abs(V["trap"] - v) == 1 for v in ctx["vazias"]): prob += 1.5
    if any(abs(D["trap"] - v) == 1 for v in ctx["vazias"]): prob -= 1.5

    return max(25.0, min(75.0, prob))

def montar_avbs(rank, ctx):
    top4 = [d for d in rank if d.get("name") != "vacant"][:4]
    if len(top4) < 2: return [], [], []
    
    s1, s2 = [], []
    
    for i in range(len(top4)):
        for j in range(i+1, len(top4)):
            A, B = top4[i], top4[j]
            prob_A = calc_prob(A, B, rank, ctx)
            
            if prob_A >= 50.0:
                V, D, prob = A, B, prob_A
            else:
                V, D, prob = B, A, 100.0 - prob_A
                
            if prob >= 60.0:
                s1.append((V, D, prob, True))
            else:
                s2.append((V, D, prob, True))
                
    return sorted(s1, key=lambda x: -x[2]), sorted(s2, key=lambda x: -x[2]), []

def get_rank_html(val, rank, max_rank):
    if val is None or rank is None: return "-"
    sup = {1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶"}.get(rank, "")
    color = "color:#00ff00;font-weight:bold" if rank == 1 else ("color:#ff4b4b" if rank == max_rank and max_rank > 1 else "")
    return f"<span style='{color}'>{val:.2f}{sup}</span>"

def tbl(headers, rows):
    css = """<style>.dib-container{overflow-x:auto;width:100%;margin-bottom:20px}.dib-table{width:100%;border-collapse:collapse;text-align:center;font-size:15px;table-layout:auto}.dib-table th,.dib-table td{padding:8px 6px;border-bottom:1px solid rgba(128,128,128,0.2);white-space:nowrap;line-height:1.3}.dib-table th{background-color:rgba(128,128,128,0.1);font-weight:600}.dib-table td.sep{padding:0;height:2px;background-color:rgba(128,128,128,0.4)}.dib-table td.sep-avb{padding:0;height:1px;background-color:rgba(128,128,128,0.15)}</style>"""
    out = []
    for row in rows:
        if len(row) == 1 and "<hr" in str(row[0]): out.append(f"<tr><td class='sep' colspan='{len(headers)}'></td></tr>"); continue
        if len(row) == 1 and "sep-avb" in str(row[0]): out.append(f"<tr><td class='sep-avb' colspan='{len(headers)}'></td></tr>"); continue
        cells = [c if isinstance(c, str) and c.strip().startswith("<td") else f"<td>{c}</td>" for c in row]
        out.append("<tr>" + "".join(cells) + "</tr>")
    return f"{css}<div class='dib-container'><table class='dib-table'><thead><tr>{''.join(f'<th>{x}</th>' for x in headers)}</tr></thead><tbody>{''.join(out)}</tbody></table></div>"

def nome_marcado(d):
    n = html.escape(d["name"])
    if d.get("bloqueado", False): n += " 🚫"
    if d.get("alvo", False): n = "🎯 " + n
    return n

def trap_label(d): return f"{TRAP_EMOJI.get(d['trap'], '')} {d['trap']}"

def tabela_projecao(ds):
    cols = ["split", "time", "tadj", "msplit", "mtime", "ritmo", "rec"]
    rk = {c: [None]*len(ds) for c in cols}
    max_rk = {}
    for c in cols:
        vals = [(i, d[c]) for i, d in enumerate(ds) if d.get(c) is not None]
        max_rk[c] = len(vals)
        vals.sort(key=lambda x: x[1], reverse=(c == "rec"))
        for rank, (i, _) in enumerate(vals, 1): rk[c][i] = rank

    rows = []
    for i, d in enumerate(ds):
        if d["nd"]:
            rows.append([trap_label(d), nome_marcado(d)] + ["-"] * 15); continue
        fat = "<br>".join(f"{k} ({v:+.1f})" for k, v in d["fatores"]) or "-"
        if d.get("remarks_translated"):
            rem_txt = ", ".join(set(d["remarks_translated"]))
            fat += f"<br><small style='color:#aaa'>{rem_txt}</small>"
            
        perfil_e = {"Limpo": "✅", "Irregular": "⚠️", "Trombador": "🔴"}[d["perfil"]]
        dias_txt = f"{d['dias']} ⚠️" if d['dias'] > 21 else str(d['dias'])
        
        rows.append([
            trap_label(d), nome_marcado(d), f"{MEDALS.get(d['pos'], str(d['pos'])+'º')} {d['overall']:.1f}",
            f"{d['cat']:.1f} ({d['cat_mod']:+.0f})", fat, f"{perfil_e} {d['perfil']}",
            "-".join((r["grade"] or "?") for r in d["runs"]), f"{d['peso']:.1f}", dias_txt,
            get_rank_html(d["split"], rk["split"][i], max_rk["split"]), get_rank_html(d["time"], rk["time"][i], max_rk["time"]),
            get_rank_html(d["tadj"], rk["tadj"][i], max_rk["tadj"]), get_rank_html(d["msplit"], rk["msplit"][i], max_rk["msplit"]),
            get_rank_html(d["mtime"], rk["mtime"][i], max_rk["mtime"]), get_rank_html(d["ritmo"], rk["ritmo"][i], max_rk["ritmo"]),
            get_rank_html(d["rec"], rk["rec"][i], max_rk["rec"]) + f"<br><small>{d['rec_txt'].split()[1]}</small>", f"{d['conf']:.0f}%"
        ])
    return tbl(["Trap", "Galgo", "Overall", "Cat", "Fatores", "Perfil", "Grades", "Peso", "Dias", "Split", "Time", "Time Ajust.", "Méd. Split", "Méd. Time", "Ritmo", "Recup. Média", "Conf."], rows)

def tabela_avb(lista, titulo):
    st.markdown(f"#### {titulo}")
    if not lista: st.info("Nenhum AVB nesta categoria."); return

    def fmt_pair(val_v, val_d, is_time=False, precision=2, is_pct=False):
        if val_v is None or val_d is None: return "-", "-"
        p, suffix = f".{precision}f", "%" if is_pct else ""
        v_str, d_str = f"{val_v:{p}}{suffix}", f"{val_d:{p}}{suffix}"
        diff = val_v - val_d
        if val_v <= val_d: v_str += f" ({diff:{p}}{suffix})"
        else: d_str += f" (+{abs(diff):{p}}{suffix})"
        if is_time:
            if val_v < val_d: v_str, d_str = f"<span style='color:#00ff00;font-weight:bold'>{v_str}</span>", f"<span style='color:#ff4b4b'>{d_str}</span>"
            elif val_v > val_d: v_str, d_str = f"<span style='color:#ff4b4b'>{v_str}</span>", f"<span style='color:#00ff00;font-weight:bold'>{d_str}</span>"
        else:
            if val_v > val_d: v_str, d_str = f"<span style='color:#00ff00;font-weight:bold'>{v_str}</span>", f"<span style='color:#ff4b4b'>{d_str}</span>"
            elif val_v < val_d: v_str, d_str = f"<span style='color:#ff4b4b'>{v_str}</span>", f"<span style='color:#00ff00;font-weight:bold'>{d_str}</span>"
        return v_str, d_str

    rows = []
    for i, (V, D, prob, star) in enumerate(lista):
        if i > 0: rows.append(["<hr>"])
        
        ov_v, ov_d = fmt_pair(V['overall'], D['overall'], False, 1)
        cat_v, cat_d = fmt_pair(V['cat'], D['cat'], False, 1)
        sp_v, sp_d = fmt_pair(V['split'], D['split'], True, 2)
        t_v, t_d = fmt_pair(V['time'], D['time'], True, 2)
        ta_v, ta_d = fmt_pair(V['tadj'], D['tadj'], True, 2)
        ms_v, ms_d = fmt_pair(V['msplit'], D['msplit'], True, 2)
        mt_v, mt_d = fmt_pair(V['mtime'], D['mtime'], True, 2)
        r_v, r_d = fmt_pair(V['ritmo'], D['ritmo'], True, 2)
        rec_v, rec_d = fmt_pair(V['rec'], D['rec'], False, 1, True)

        prob_cell = f"<td rowspan='2' style='vertical-align:middle;font-weight:bold;font-size:16px;'><span style='color:#00ff00'>{prob:.1f}%</span></td>"
        
        rows.append([
            f"{'⭐ ' if star else ''}{trap_label(V)} - {html.escape(V['name'])}", 
            ov_v, cat_v, V['perfil'], "-".join((r["grade"] or "?") for r in V["runs"]),
            f"{V['peso']:.1f}", f"{V['dias']}", sp_v, t_v, ta_v, ms_v, mt_v, r_v, rec_v, f"{V['conf']:.0f}%", 
            prob_cell
        ])
        
        rows.append([
            f"{trap_label(D)} - {html.escape(D['name'])}", 
            ov_d, cat_d, D['perfil'], "-".join((r["grade"] or "?") for r in D["runs"]),
            f"{D['peso']:.1f}", f"{D['dias']}", sp_d, t_d, ta_d, ms_d, mt_d, r_d, rec_d, f"{D['conf']:.0f}%"
        ])
        
    heads = ["AvB", "Overall", "Cat", "Perfil", "Grades", "Peso", "Dias", "Split", "Time", "Time Ajust.", "Méd. Split", "Méd. Time", "Ritmo", "Recup.", "Conf.", "Probabilidade"]
    st.markdown(tbl(heads, rows), unsafe_allow_html=True)

def main():
    st.set_page_config(page_title="DIB GREYHOUND 3.3", layout="wide")
    st.title("🐾 DIB GREYHOUND 3.3")

    url_alvo = st.text_input("Link", placeholder="Cole o link da corrida aqui...", label_visibility="collapsed")

    with st.sidebar:
        st.header("Ajustes da Corrida")
        classe = st.text_input("Classe (ex: A4)", value="A4")
        dist_in = st.number_input("Distância (m) - 0 = Auto", value=0, step=10)
        pp_in = st.text_input("Post Pick (ex: 1-2-3)", value="")

    if st.button("Analisar Corrida", type="primary") and url_alvo:
        dogs, meta, meta_info = extrair_dados_racingpost(url_alvo)
        if dogs:
            dist = float(dist_in) if dist_in > 0 else (float(pd.Series([r["dist"] for d in dogs for r in d["runs"] if r["dist"]]).mode().iloc[0]) if any(r["dist"] for d in dogs for r in d["runs"]) else 480.0)
            ctx = {"dist": dist, "today": parse_date(meta["r_date"]), "classe_n": grade_num(classe),
                   "post_pick": [int(x) for x in re.findall(r"\d", pp_in)],
                   "vazias": [t for t in range(1, 7) if t not in {d["trap"] for d in dogs if d["name"] != "vacant"}]}
            
            ds = [analisar_galgo(d, ctx) for d in dogs]
            rank, top3_ms = finalizar(ds, ctx)
            ds.sort(key=lambda d: d["trap"])
            
            st.markdown(f"### {classe} · {int(dist)}m · POST PICK: {pp_in or '-'}")
            st.markdown("#### Planilha de Projeção")
            st.markdown(tabela_projecao(ds), unsafe_allow_html=True)
            
            st.markdown("**Classificação:** " + " > ".join(f"{MEDALS.get(d['pos'], str(d['pos'])+'º')} {TRAP_EMOJI[d['trap']]} {d['trap']}" for d in rank))
            
            s1, s2, s3 = montar_avbs(rank, ctx)
            tabela_avb(s1, "1ª Planilha — AVB Principal (Prob ≥ 60%)")
            tabela_avb(s2, "2ª Planilha — AVB Secundário (Prob < 60%)")

if __name__ == "__main__":
    main()
