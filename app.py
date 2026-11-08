import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7", layout="wide")
st.title("🐾 Análise DIB 2.7")

# =========================================================
# FUNÇÕES AUXILIARES
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
    return any(x in r for x in ["CRD", "BMP", "BLK", "BAULKED", "FCD", "MVDOFF", "EVCH"])

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
# EXTRAÇÃO E CÁLCULOS
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

        regs, total = [], len(dogs)
        for dog in dogs:
            n, t = dog.get("dogName", ""), int(dog.get("trapNum", 0))
            p_card = float(dog.get("weight", 0) or 0)
            forms = dog.get("forms", [])
            
            for c in forms:
                if get_dist_val(c.get("distance")) != meta["dist"]: continue
                g = c.get("gr") or c.get("grade") or "A5"
                
                regs.append({
                    "Galgo": n, "Trap_Num": t, "Trap": get_emoji(t), 
                    "Split": float(c.get("sectionalTime", 0) or 0), "CalTm": float(c.get("calcRTimes", 0) or 0), 
                    "Going": c.get("goingType", "N"), "Bends": c.get("bndPos", "4444"), 
                    "Fin": str(c.get("outcomeDesc", "6")), "Remarks": c.get("closeUpCmnt", ""), 
                    "Peso_Atual_Card": p_card, "Peso_Corrida": float(c.get("weight", 0) or 0),
                    "Dias": (d_obj - datetime.strptime(c.get("raceTime", dt)[:10], "%Y-%m-%d")).days, 
                    "Grade_Str": str(g), "Data_Corrida": c.get("raceTime", "")[:10], "Total_Caes": total
                })
                
        if not regs: return None, None, f"Nenhum galgo possui histórico na distância de {meta['dist']}m."
        return pd.DataFrame(regs), meta, None
    except Exception as e: return None, None, f"Erro: {str(e)}"

# =========================================================
# RENDERIZAÇÃO AVB
# =========================================================
def render_avb(v, d, f):
    def fmt(x, y, i=False):
        try:
            diff = float(x) - float(y)
            return f"{int(x)} ({int(diff):+d})" if i else f"{float(x):.2f} ({diff:+.2f})"
        except: return str(x)
    # AQUI FOI TROCADO 'Histórico' POR 'Grade'
    rv = {"AvB": f"⭐ {v['Trap']} {v['Galgo']}", "Overall": round(v['Overall'], 2), "Cat": v['Cat'], "Perfil": v['Perfil'], "Grade": v['Grade'], "Peso": v['Peso'], "Dias": v['Dias'], "Split": round(v['Split'], 2), "Time": round(v['Time'], 2), "Time_Ajust": round(v['Time_Ajust'], 2), "M_Split": round(v['M_Split'], 2), "M_Time": round(v['M_Time'], 2), "Ritmo": round(v['Ritmo'], 2), "Recup_Str": v['Recup_Str'], "Confianca": f"{v['Confianca']}%", "Força": round(f, 2)}
    rd = {"AvB": f"   {d['Trap']} {d['Galgo']}", "Overall": fmt(d['Overall'], v['Overall']), "Cat": fmt(d['Cat'], v['Cat'], True), "Perfil": d['Perfil'], "Grade": d['Grade'], "Peso": fmt(d['Peso'], v['Peso']), "Dias": fmt(d['Dias'], v['Dias'], True), "Split": fmt(d['Split'], v['Split']), "Time": fmt(d['Time'], v['Time']), "Time_Ajust": fmt(d['Time_Ajust'], v['Time_Ajust']), "M_Split": fmt(d['M_Split'], v['M_Split']), "M_Time": fmt(d['M_Time'], v['M_Time']), "Ritmo": fmt(d['Ritmo'], v['Ritmo']), "Recup_Str": f"{d['Recup']:.2f}% ({d['Recup'] - v['Recup']:+.2f}%)", "Confianca": f"{d['Confianca']}% ({d['Confianca'] - v['Confianca']:+d}%)", "Força": ""}
    return pd.DataFrame([rv, rd, {c: "-" for c in rv.keys()}])

# =========================================================
# LÓGICA PRINCIPAL DIB 2.7
# =========================================================
url = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/...")
if st.button("Analisar", type="primary") and url:
    with st.spinner("Calculando DIB 2.7..."):
        df_b, meta, err = extrair(url)
        if err: st.error(err)
        elif df_b is not None and not df_b.empty:
            try:
                cat_h, d_h = meta["cat"], meta["dist"]
                df = df_b[df_b["CalTm"] > 0].copy()
                if df.empty: st.warning("Sem tempos válidos.")
                else:
                    df["Time_Ajust"] = df["CalTm"] - df["Going"].apply(parse_going) - df["Remarks"].apply(parse_traffic)
                    df["Has_Traffic"] = df["Remarks"].apply(is_traffic)
                    b_s = df["Bends"].apply(lambda x: pd.Series(get_bends(x)))
                    df["Bend_1"] = b_s[0]
                    df["Fin_num"] = pd.to_numeric(df["Fin"].str.extract(r'(\d+)')[0], errors="coerce").fillna(6)
                    
                    res = []
                    for n, g in df.groupby("Galgo"):
                        g = g.sort_values("Data_Corrida", ascending=False)
                        u_g = g.iloc[0]
                        val = g[g['Grade_Str'].str.match(r'^A\d{1,2}$', na=False)].copy()
                        if val.empty: continue
                        
                        u_o = val.iloc[0]
                        wa = lambda c: np.average(val[c], weights=[5,4,3,2,1][:len(val)])
                        m_t, m_s = wa("CalTm"), wa("Split")
                        
                        # Recuperação Blindada
                        clean = val[~val["Has_Traffic"]]
                        rec_med = ((clean["Bend_1"] - clean["Fin_num"]) / g["Total_Caes"].iloc[0] * 100).mean() if not clean.empty else 0.0
                        rec_str = f"{rec_med:.2f}% ({(clean['Bend_1'] > clean['Fin_num']).sum()}/{(clean['Bend_1'] < clean['Fin_num']).sum()})" if not clean.empty else "0.00% (0/0)"
                        
                        # Categoria
                        m_h = re.search(r'A(\d+)', cat_h); m_u = re.search(r'A(\d+)', u_o["Grade_Str"])
                        n_h = int(m_h.group(1)) if m_h else 5; n_u = int(m_u.group(1)) if m_u else 5
                        c_b = get_cat_base(cat_h); c_m = 2 if n_u < n_h else (-2 if n_u > n_h else 0)
                        cat_final = c_b + c_m
                        
                        # Fatores
                        f_mom = 3.0 if u_o["Fin_num"] == 1 else (-2.0 if u_o["Fin_num"] >= 4 and n_u >= n_h else 0.0)
                        d_p = abs(u_g["Peso_Atual_Card"] - u_o["Peso_Corrida"])
                        f_peso = -5.0 if d_p > 2.0 else (-2.0 if 1.1 <= d_p <= 1.9 else 0.0)
                        f_dias = -5.0 if u_g["Dias"] < 4 else (-3.0 if 29 <= u_g["Dias"] <= 45 else (-5.0 if u_g["Dias"] > 45 else 0.0))
                        
                        rms = str(u_o["Remarks"]).upper()
                        f_rem = (1.5 if "EP" in rms or "LD" in rms else 0) + (5.0 if "CLRRN" in rms else 0) - (10.0 if "SAW" in rms else 0) - (7.0 if "CRD1" in rms or "BMP1" in rms else 0)
                        
                        t_c = val["Has_Traffic"].sum()
                        perf = "✅ Limpo" if t_c <= 1 else ("⚠️ Irregular" if t_c == 2 else "🔴 Trombador")
                        p_pts = 10 if t_c <= 1 else (5 if t_c == 2 else 2.5)
                        
                        cnf = len(val) * 20
                        blk = u_g["Grade_Str"].startswith("T") or cnf < 60
                        
                        # AQUI FOI TROCADO 'Histórico' POR 'Grade'
                        res.append({
                            "Trap": u_g["Trap"], "Galgo_Original": n, "Galgo": f"[BLOQUEADO] {n}" if blk else n, 
                            "Cat_Base": c_b, "Mod": c_m, "Cat": cat_final, "Fatores": round(f_mom + f_peso + f_dias + f_rem, 2), 
                            "Perfil": perf, "P_pts": p_pts, "Grade": "·".join(val["Grade_Str"].head(5)), 
                            "Peso": u_o["Peso_Corrida"], "Dias": u_g["Dias"], "Split": u_o["Split"], "Time": u_o["CalTm"], 
                            "Time_Ajust": val["Time_Ajust"].mean(), "M_Split": m_s, "M_Time": m_t, "Ritmo": m_t - m_s, 
                            "Recup": rec_med, "Recup_Str": rec_str, "Confianca": cnf, "Block": blk
                        })
                        
                    if not res: st.error("Sem corridas oficiais (A).")
                    else:
                        agg = pd.DataFrame(res)
                        
                        agg["Overall"] = (
                            calc_prop(agg["Time_Ajust"], 40, 5) + 
                            calc_prop(agg["M_Time"], 30, 5) + 
                            calc_prop(agg["M_Split"], 15, 2) + 
                            calc_prop(agg["Ritmo"], 15, 2) + 
                            agg["Cat"] + agg["P_pts"] + (5 + (agg["Recup"] / 10)).clip(0, 10) + agg["Fatores"]
                        )
                        agg = agg.sort_values("Overall", ascending=False).reset_index(drop=True)
                        
                        t3_s = agg["M_Split"].nsmallest(3).tolist()
                        agg["Is_Target"] = (agg["M_Split"] > t3_s[-1]) & (agg["Recup"] <= 0)
                        
                        st.markdown(f"### 🏁 {meta['pista']} {meta['hora']} (BR {meta['br']}) · Race {meta['num']} · {cat_h} · {d_h}m")
                        st.info(" > ".join([f"{['🥇','🥈','🥉','4º','5º','6º'][i]} {r['Trap']} {r['Galgo'].replace('[BLOQUEADO] ', '')}" for i, r in agg.iterrows()]))
                        
                        # AQUI FOI TROCADO 'Histórico' POR 'Grade'
                        cols = ["Trap", "Galgo", "Overall", "Cat_Base", "Mod", "Cat", "Fatores", "Perfil", "Grade", "Peso", "Dias", "Split", "Time", "Time_Ajust", "M_Split", "M_Time", "Ritmo", "Recup_Str", "Confianca"]
                        st.dataframe(agg[cols].round(2), use_container_width=True, hide_index=True)
                        
                        # AVB (Força) e Matchmaking
                        elig = agg[~agg["Block"]].reset_index(drop=True)
                        
                        def calc_forca(v, d):
                            base = (v["Overall"] - d["Overall"]) + 100*(d["M_Time"] - v["M_Time"]) + (v["Recup"] - d["Recup"])/2 + (v["Cat"] - d["Cat"])*2
                            aj = 0
                            if int(v["Trap"].split()[-1]) <= 2 and int(d["Trap"].split()[-1]) > 2: aj += 5
                            if v["Galgo"] == elig.iloc[0]["Galgo"] and d["Galgo"] != elig.iloc[1]["Galgo"]: aj += 5
                            return base + aj

                        a_alvo, a_princ, a_sec = [], [], []
                        
                        for _, tgt in agg[agg["Is_Target"]].iterrows():
                            for _, atk in elig.iterrows():
                                if atk["Galgo"] != tgt["Galgo"] and atk["Overall"] > tgt["Overall"]:
                                    f = calc_forca(atk, tgt)
                                    if f >= 50: a_alvo.append((atk, tgt, f))
                                    
                        if len(elig) >= 3:
                            for j in [2, 3]:
                                if j < len(elig) and not elig.iloc[j]["Is_Target"]:
                                    f = calc_forca(elig.iloc[0], elig.iloc[j])
                                    if f >= 50: a_princ.append((elig.iloc[0], elig.iloc[j], f))
                                    elif f >= 40: a_sec.append((elig.iloc[0], elig.iloc[j], f))
                            for j in [3, 4]:
                                if j < len(elig) and not elig.iloc[j]["Is_Target"]:
                                    f = calc_forca(elig.iloc[1], elig.iloc[j])
                                    if f >= 50: a_princ.append((elig.iloc[1], elig.iloc[j], f))
                                    elif f >= 40: a_sec.append((elig.iloc[1], elig.iloc[j], f))
                            for j in [4, 5]:
                                if j < len(elig) and not elig.iloc[j]["Is_Target"]:
                                    f = calc_forca(elig.iloc[2], elig.iloc[j])
                                    if f >= 50: a_princ.append((elig.iloc[2], elig.iloc[j], f))
                                    elif f >= 40: a_sec.append((elig.iloc[2], elig.iloc[j], f))

                        st.markdown("---")
                        for title, arr in [("🎯 AVB do Alvo", a_alvo), ("⚔️ AVB Principal (Elite)", a_princ), ("🛡️ AVB Secundário", a_sec)]:
                            st.markdown(f"### {title}")
                            if arr:
                                for v, d, f in arr: st.dataframe(render_avb(v, d, f), use_container_width=True, hide_index=True)
                            else: st.info("Nenhum confronto.")
            except Exception as e: st.error(f"Erro no processamento: {e}")