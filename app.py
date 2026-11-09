import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7", layout="wide")

# =========================================================
# FUNÇÕES AUXILIARES E REGEX
# =========================================================
def get_dist_val(val):
    if not val: return ""
    match = re.search(r'(\d+)', str(val))
    return match.group(1) if match else ""

def parse_going(g):
    if pd.isna(g) or not g: return 0.0
    g = str(g).strip().upper().replace(" ", "")
    m = re.match(r"([+-]?)(\d+)", g)
    if not m: return 0.0
    val = int(m.group(2)) / 100.0
    return -val if m.group(1) == "-" else val

def parse_traffic(r):
    if pd.isna(r): return 0.0
    r = str(r).upper()
    if "BAULKED" in r or "BLK" in r: return 0.20
    if "CRD" in r or "BMP" in r or "FCD" in r: return 0.10
    return 0.0

def is_traffic(r):
    if pd.isna(r): return False
    r = str(r).upper()
    forbidden = ["CRD", "BMP", "BLK", "BAULKED", "FCD-CK", "EVCH", "MVDOFF"]
    return any(x in r for x in forbidden)

def get_bends(b):
    if pd.isna(b): return 4, 4
    d = [int(c) for c in str(b) if c.isdigit()]
    return (d[0], d[-1]) if len(d) >= 4 else (4, 4)

def get_cat_base(g):
    m = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}
    match = re.search(r'A(\d+)', str(g).upper())
    return m.get(f"A{match.group(1)}", 10) if match else 10

def calc_prop(s, max_p, min_p):
    s = pd.to_numeric(s, errors="coerce").fillna(s.median())
    if s.max() == s.min(): return pd.Series([(max_p+min_p)/2] * len(s), index=s.index)
    return max_p - ((s - s.min()) / (s.max() - s.min()) * (max_p - min_p))

def get_emoji(t):
    return {1: "🟥 1", 2: "🟦 2", 3: "⬜ 3", 4: "⬛ 4", 5: "🟧 5", 6: "🔳 6"}.get(int(t), str(t))

# =========================================================
# EXTRAÇÃO DE DADOS (RACING POST API & PROXY)
# =========================================================
def extrair(url):
    try:
        rid = re.search(r"race_id=(\d+)", url).group(1)
        dt = re.search(r"r_date=([\d-]+)", url).group(1)
        d_obj = datetime.strptime(dt, "%Y-%m-%d")
        
        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={rid}&r_date={dt}&blocks=card,form"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36", "Accept": "application/json"}
        
        data = None
        try:
            res = requests.get(api_url, headers=headers, timeout=15)
            if res.status_code == 200: data = res.json()
        except: pass
        
        if data is None:
            proxy_url = f"https://api.allorigins.win/raw?url={requests.utils.quote(api_url)}"
            try:
                res = requests.get(proxy_url, timeout=20)
                if res.status_code == 200: data = res.json()
            except: pass
                
        if data is None: return None, None, "Racing Post bloqueou a conexão. Tente novamente."
            
        meta = {"pista": "Desconhecida", "hora": "00:00", "br": "00:00", "num": "X", "cat": "A5", "dist": "480"}
        race_info = {}
        try:
            for r in data.get('card', {}).get('races', []):
                if str(r.get('raceId')) == str(rid): race_info = r; break
        except: pass
            
        if race_info:
            meta["pista"] = str(race_info.get("course", meta["pista"])).upper()
            meta["num"] = str(race_info.get("raceNo", meta["num"]))
            tm = str(race_info.get("time", ""))
            if tm:
                match = re.search(r'(\d{2}:\d{2})', tm)
                if match:
                    meta["hora"] = match.group(1)
                    meta["br"] = f"{(int(meta['hora'][:2])-3)%24:02d}:{meta['hora'][3:]}"
            
            title = str(race_info.get("raceTitle", ""))
            m_dist = re.search(r'(\d{3,4})\s*m', title)
            if m_dist: meta["dist"] = m_dist.group(1)
            else:
                d_raw = race_info.get("distance") or race_info.get("dist") or ""
                if d_raw: meta["dist"] = get_dist_val(d_raw)
            
            cls = str(race_info.get("raceClass", meta["cat"])).upper()
            c_match = re.search(r'A\d+', cls)
            if c_match: meta["cat"] = c_match.group(0)
        
        dogs = data.get("form", {}).get("dogs", [])
        if not dogs: return None, None, "Sem galgos."
        
        if meta["dist"] == "480" and dogs[0].get("forms"):
            meta["dist"] = get_dist_val(dogs[0]["forms"][0].get("distance"))

        regs = []
        for dog in dogs:
            n, t = dog.get("dogName", ""), int(dog.get("trapNum", 0))
            p_card = float(dog.get("weight", 0) or 0)
            forms = dog.get("forms", [])
            
            for c in forms:
                g = c.get("gr") or c.get("grade") or "A5"
                d_corrida = c.get("raceTime", dt)[:10]
                try:
                    dias_calc = (d_obj - datetime.strptime(d_corrida, "%Y-%m-%d")).days
                except:
                    dias_calc = 0
                
                regs.append({
                    "Galgo": n, "Trap_Num": t, "Trap": get_emoji(t) if t > 0 else "vacant", 
                    "Split": float(c.get("sectionalTime", 0) or 0), "CalTm": float(c.get("calcRTimes", 0) or 0), 
                    "Going": c.get("goingType", "N"), "Bends": c.get("bndPos", "4444"), 
                    "Fin": str(c.get("outcomeDesc", "6")), "Remarks": c.get("closeUpCmnt", ""), 
                    "Peso_Atual_Card": p_card, "Peso_Corrida": float(c.get("weight", 0) or 0),
                    "Dias": dias_calc, "Grade_Str": str(g), "Data_Corrida": d_corrida, "Total_Caes": len(dogs),
                    "Distancia": get_dist_val(c.get("distance"))
                })
                
        if not regs: return None, None, "Nenhum histórico encontrado."
        return pd.DataFrame(regs), meta, None
    except Exception as e: return None, None, f"Erro na extração: {str(e)}"

# =========================================================
# ENTRADA DO USUÁRIO & BOTÃO
# =========================================================
url = st.text_input("Link da corrida (Racing Post)", placeholder="https://greyhoundbet.racingpost.com/#card/...")
analisar_btn = st.button("Analisar", type="primary")

if analisar_btn and url:
    with st.spinner("Calculando DIB 2.7..."):
        df_b, meta, err = extrair(url)
        if err: 
            st.error(err)
        elif df_b is not None and not df_b.empty:
            try:
                cat_h, d_h = meta["cat"], meta["dist"]
                
                res = []
                for n, g in df_b.groupby("Galgo"):
                    g = g.sort_values("Data_Corrida", ascending=False).reset_index(drop=True)
                    u_g = g.iloc[0]
                    
                    val_dist = g[g["Distancia"] == d_h].copy()
                    if val_dist.empty: continue
                    u_o = val_dist.iloc[0]
                    
                    oficial_classes = val_dist[~val_dist["Grade_Str"].str.upper().str.contains("T|HP", na=False)]
                    last_grade = oficial_classes.iloc[0]["Grade_Str"] if not oficial_classes.empty else u_o["Grade_Str"]
                        
                    m_h = re.search(r'A(\d+)', cat_h)
                    m_u = re.search(r'A(\d+)', str(last_grade))
                    n_h = int(m_h.group(1)) if m_h else 5
                    n_u = int(m_u.group(1)) if m_u else 5
                    
                    c_b = get_cat_base(cat_h)
                    if n_u < n_h: c_m = 2
                    elif n_u > n_h: c_m = -2
                    else: c_m = 0
                    cat_final = c_b + c_m
                    
                    d_p = abs(u_g["Peso_Atual_Card"] - u_o["Peso_Corrida"])
                    f_peso = -5.0 if d_p > 2.0 else (-2.0 if 1.1 <= d_p <= 1.9 else 0.0)
                    
                    dias_desc = u_g["Dias"]
                    f_dias = -5.0 if dias_desc < 4 else (-3.0 if 29 <= dias_desc <= 45 else (-5.0 if dias_desc > 45 else 0.0))
                    
                    last_5_dist = val_dist.head(5).copy()
                    adj_times = [row["CalTm"] - parse_going(row["Going"]) - parse_traffic(row["Remarks"]) for _, row in last_5_dist.iterrows()]
                    time_ajust_mean = np.mean(adj_times) if adj_times else u_o["CalTm"]
                    
                    w_vals = [5, 4, 3, 2, 1][:len(last_5_dist)]
                    m_t = np.average(last_5_dist["CalTm"], weights=w_vals) if not last_5_dist.empty else u_o["CalTm"]
                    m_s = np.average(last_5_dist["Split"], weights=w_vals) if not last_5_dist.empty else u_o["Split"]
                    ritmo = m_t - m_s
                    
                    clean_races = last_5_dist[~last_5_dist["Remarks"].apply(is_traffic)]
                    rec_vals = []
                    for _, cr in clean_races.iterrows():
                        bends = get_bends(cr["Bends"])
                        fin_num = pd.to_numeric(str(cr["Fin"]).extract(r'(\d+)')[0], errors="coerce") if pd.notna(cr["Fin"]) else 6
                        if pd.isna(fin_num): fin_num = 6
                        rec_vals.append(((bends[0] - fin_num) / (cr["Total_Caes"] if cr["Total_Caes"] > 0 else 6)) * 100)
                    
                    rec_med = np.mean(rec_vals) if rec_vals else 0.0
                    conf = min(len(val_dist), 5) * 20
                    
                    t_c = last_5_dist["Remarks"].apply(is_traffic).sum()
                    if t_c <= 1: perf, p_pts = "✅ Limpo", 10.0
                    
