import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7", layout="wide")
st.title("🐾 Análise DIB 2.7")

def parse_going(g):
    if pd.isna(g): return 0.0
    g = str(g).strip().upper().replace(" ", "")
    if g in ["N", "NORMAL"]: return 0.0
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

def get_cat(g):
    m = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}
    match = re.search(r'A(\d+)', str(g).upper())
    return m.get(f"A{match.group(1)}", 10) if match else 10

def calc_prop(s, max_p, min_p):
    s = pd.to_numeric(s, errors="coerce").fillna(s.median())
    if s.max() == s.min(): return pd.Series([(max_p+min_p)/2] * len(s), index=s.index)
    return max_p - ((s - s.min()) / (s.max() - s.min()) * (max_p - min_p))

def get_emoji(t):
    return {1: "🟥 1", 2: "🟦 2", 3: "⬜ 3", 4: "⬛ 4", 5: "🟧 5", 6: "🔳 6"}.get(int(t), str(t))

def extrair(url):
    try:
        rid = re.search(r"race_id=(\d+)", url).group(1)
        dt = re.search(r"r_date=([\d-]+)", url).group(1)
        d_obj = datetime.strptime(dt, "%Y-%m-%d")
        
        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={rid}&r_date={dt}&blocks=card,form"
        
        proxies = [
            f"https://api.allorigins.win/raw?url={requests.utils.quote(api_url)}",
            f"https://corsproxy.io/?url={requests.utils.quote(api_url)}",
            f"https://api.cors.lol/?url={requests.utils.quote(api_url)}",
            f"https://api.codetabs.com/v1/proxy?quest={requests.utils.quote(api_url)}"
        ]
        
        data = None
        for proxy_url in proxies:
            try:
                h = {"User-Agent": "Mozilla/5.0"}
                res = requests.get(proxy_url, headers=h, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    break
            except:
                continue
        
        if data is None:
            return None, None, "Todos os proxies falharam. O Racing Post está bloqueando ou fora do ar."
            
        meta = {"pista": "KINSLEY", "hora": "00:00", "br": "00:00", "num": "X", "cat": "A5"}
        try:
            for r in data.get('card', {}).get('races', []):
                if str(r.get('raceId')) == str(rid):
                    meta["pista"] = str(r.get("course", meta["pista"])).upper()
                    meta["num"] = str(r.get("raceNo", meta["num"]))
                    tm = str(r.get("time", ""))
                    if tm:
                        match = re.search(r'(\d{2}:\d{2})', tm)
                        if match:
                            meta["hora"] = match.group(1)
                            meta["br"] = f"{(int(meta['hora'][:2])-3)%24:02d}:{meta['hora'][3:]}"
                    cls = str(r.get("raceClass", meta["cat"])).upper()
                    c_match = re.search(r'A\d+', cls)
                    if c_match: meta["cat"] = c_match.group(0)
                    break
        except: 
            pass
        
        dogs = data.get("form", {}).get("dogs", [])
        if not dogs: return None, None, "Sem galgos no arquivo."
        
        regs, dist = [], "480"
        total = len(dogs)
        for dog in dogs:
            n, t, p_card = dog.get("dogName", ""), int(dog.get("trapNum", 0)), float(dog.get("weight", 0) or 0)
            forms = dog.get("forms", [])
            if not forms: continue
            dist = re.sub(r'[^\d]', '', str(forms[0].get("distance", "480")))
            for c in forms:
                g = c.get("gr") or c.get("grade") or "A5"
                if not re.match(r'^A\d+', str(g)):
                    for v in c.values():
                        if isinstance(v, str) and re.match(r'^([A-Z]\d{1,2})$', v.strip().upper()):
                            g = v.strip().upper(); break
                regs.append({
                    "Galgo": n, "Trap_Num": t, "Trap": get_emoji(t),
                    "Split": float(c.get("sectionalTime", 0) or 0), "CalTm": float(c.get("calcRTimes", 0) or 0), 
                    "Going": c.get("goingType", "N"), "Bends": c.get("bndPos", "4444"), 
                    "Fin": str(c.get("outcomeDesc", "6")), "Remarks": c.get("closeUpCmnt", ""), 
                    "Peso_Atual_Card": p_card, "Peso_Corrida": float(c.get("weight", 0) or 0),
                    "Dias": (d_obj - datetime.strptime(c.get("raceTime", dt)[:10], "%Y-%m-%d")).days, 
                    "Grade": str(g), "Data_Corrida": c.get("raceTime", "")[:10], 
                    "Distancia": re.sub(r'[^\d]', '', str(c.get("distance", "480"))), "Total_Caes": total
                })
        return pd.DataFrame(regs), meta, None
    except Exception as e: 
        return None, None, str(e)

def render_avb(v, d, f):
    cols = ["AvB", "Overall", "Cat", "Perfil", "Histórico", "Peso", "Dias", "Split", "Time", "Time_Ajust", "M_Split", "M_Time", "Ritmo", "Recup_Str", "Confianca", "Força"]
    def fmt(x, y, i=False):
        try:
            diff = float(x) - float(y)
            return f"{int(x)} ({int(diff):+d})" if i else f"{float(x):.2f} ({diff:+.2f})"
        except: return str(x)
    rv = {"AvB": f"⭐ {v['Trap']} {v['Galgo']}", "Overall": round(v['Overall'], 2), "Cat": v['Cat'], "Perfil": v['Perfil'], "Histórico": v['Histórico'], "Peso": v['Peso'], "Dias": v['Dias'], "Split": round(v['Split'], 2), "Time": round(v['Time'], 2), "Time_Ajust": round(v['Time_Ajust'], 2), "M_Split": round(v['M_Split'], 2), "M_Time": round(v['M_Time'], 2), "Ritmo": round(v['Ritmo'], 2), "Recup_Str": v['Recup_Str'], "Confianca": f"{v['Confianca']}%", "Força": round(f, 2)}
    rd = {"AvB": f"   {d['Trap']} {d['Galgo']}", "Overall": fmt(d['Overall'], v['Overall']), "Cat": fmt(d['Cat'], v['Cat'], True), "Perfil": d['Perfil'], "Histórico": d['Histórico'], "Peso": fmt(d['Peso'], v['Peso']), "Dias": fmt(d['Dias'], v['Dias'], True), "Split": fmt(d['Split'], v['Split']), "Time": fmt(d['Time'], v['Time']), "Time_Ajust": fmt(d['Time_Ajust'], v['Time_Ajust']), "M_Split": fmt(d['M_Split'], v['M_Split']), "M_Time": fmt(d['M_Time'], v['M_Time']), "Ritmo": fmt(d['Ritmo'], v['Ritmo']), "Recup_Str": f"{d['Recup']:.2f}% ({d['Recup'] - v['Recup']:+.2f}%)", "Confianca": f"{d['Confianca']}% ({d['Confianca'] - v['Confianca']:+d}%)", "Força": ""}
    sep = {c: "-" for c in cols}; sep["AvB"] = "-"
    return pd.DataFrame([rv, rd, sep])

url = st.text_input("Link da corrida")
if st.button("Analisar", type="primary") and url:
    with st.spinner("Buscando dados via Proxy..."):
        df_b, meta, err = extrair(url)
        if err: 
            st.error(err)
        elif df_b is not None and not df_b.empty:
            try:
                cat_h, d_h = meta["cat"], df_b["Distancia"].iloc[0]
                df = df_b[(df_b["Distancia"] == d_h) & (df_b["CalTm"] > 0)].copy()
                if df.empty: 
                    st.warning("Sem corridas válidas.")
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
                        val = g[g['Grade'].str.match(r'^A\d{1,2}$', na=False)].copy()
                        if val.empty: continue
                        u_o = val.iloc[0]
                        wa = lambda c: np.average(val[c], weights=[5,4,3,2,1][:len(val)])
                        m_t, m_s = wa("CalTm"), wa("Split")
                        clean = val[~val["Has_Traffic"]]
                        rec_med = ((clean["Bend_1"] - clean["Fin_num"]) / g["Total_Caes"].iloc[0] * 100).mean() if not clean.empty else 0.0
                        rec_str = f"{rec_med:.2f}% ({(clean['Bend_1'] > clean['Fin_num']).sum()}/{(clean['Bend_1'] < clean['Fin_num']).sum()})" if not clean.empty else "0.00% (0/0)"
                        m_h = re.search(r'A(\d+)', cat_h); m_u = re.search(r'A(\d+)', u_o["Grade"])
                        n_h = int(m_h.group(1)) if m_h else 5
                        n_u = int(m_u.group(1)) if m_u else 5
                        c_b = get_cat(cat_h)
                        c_m = 2 if n_u < n_h else (-2 if n_u > n_h else 0)
                        f_m = 3.0 if u_o["Fin_num"] == 1 else (-2.0 if u_o["Fin_num"] >= 4 and n_u >= n_h else 0.0)
                        d_p = abs(u_g["Peso_Atual_Card"] - u_o["Peso_Corrida"])
                        f_p = -5.0 if d_p > 2.0 else (-2.0 if 1.1 <= d_p <= 1.9 else 0.0)
                        f_d = -5.0 if u_g["Dias"] < 4 else (-3.0 if 29 <= u_g["Dias"] <= 45 else (-5.0 if u_g["Dias"] > 45 else 0.0))
                        rms = str(u_o["Remarks"]).upper()
                        f_r = (1.5 if "EP" in rms or "LD" in rms else 0) + (5.0 if "CLRRN" in rms else 0) - (10.0 if "SAW" in rms else 0) - (7.0 if "CRD1" in rms or "BMP1" in rms else 0)
                        t_c = val["Has_Traffic"].sum()
                        perf = "✅ Limpo" if t_c <= 1 else ("⚠️ Irregular" if t_c == 2 else "🔴 Trombador")
                        p_p = 10 if t_c <= 1 else (5 if t_c == 2 else 2.5)
                        cnf = len(val) * 20
                        blk = u_g["Grade"].startswith("T") or cnf < 60
                        
                        res.append({
                            "Trap": u_g["Trap"], "Galgo_Original": n, "Galgo": f"[BLOQUEADO] {n}" if blk else n, 
                            "Cat_Base": c_b, "Mod": c_m, "Cat": c_b + c_m, "Fatores": round(f_m + f_p + f_d + f_r, 2), 
                            "Perfil": perf, "P_pts": p_p, "Histórico": "·".join(val["Grade"].head(5)), 
                            "Peso": u_o["Peso_Corrida"], "Dias": u_g["Dias"], "Split": u_o["Split"], "Time": u_o["CalTm"], 
                            "Time_Ajust": val["Time_Ajust"].mean(), "M_Split": m_s, "M_Time": m_t, "Ritmo": m_t - m_s, 
                            "Recup": rec_med, "Recup_Str": rec_str, "Confianca": cnf, "Block": blk
                        })
                    if res:
                        agg = pd.DataFrame(res)
                        agg["Overall"] = (calc_prop(agg["Time_Ajust"], 40, 5) + calc_prop(agg["M_Time"], 30, 5) + calc_prop(agg["M_Split"], 15, 2) + calc_prop(agg["Ritmo"], 15, 2) + agg["Cat"] + agg["P_pts"] + (5 + (agg["Recup"] / 10)).clip(0, 10) + agg["Fatores"])
                        agg = agg.sort_values("Overall", ascending=False).reset_index(drop=True)
                        t3_s = agg["M_Split"].nsmallest(3).tolist()
                        agg["Is_Target"] = (agg["M_Split"] > t3_s[-1]) & (agg["Recup"] <= 0)
                        
                        st.markdown(f"### 🏁 {meta['pista']} {meta['hora']} (BR {meta['br']}) · Race {meta['num']} · {cat_h} · {d_h}m")
                        st.info(" > ".join([f"{['🥇','🥈','🥉','4º','5º','6º'][i]} {r['Trap']} {r['Galgo'].replace('[BLOQUEADO] ', '')}" for i, r in agg.iterrows()]))
                        
                        cols = ["Trap", "Galgo", "Overall", "Cat_Base", "Mod", "Cat", "Fatores", "Perfil", "Histórico", "Peso", "Dias", "Split", "Time", "Time_Ajust", "M_Split", "M_Time", "Ritmo", "Recup_Str", "Confianca"]
                        st.dataframe(agg[cols].round(2), use_container_width=True, hide_index=True)
                        
                        elig = agg[~agg["Block"]].reset_index(drop=True)
                        cf = lambda v, d: (v["Overall"] - d["Overall"]) + 100*(d["M_Time"] - v["M_Time"]) + (v["Recup"] - d["Recup"])/2 + (v["Cat"] - d["Cat"])*2
                        
                        a_alvo, a_princ, a_sec = [], [], []
                        for _, t in agg[agg["Is_Target"]].iterrows():
                            for _, a in elig[elig["Overall"] > t["Overall"]].iterrows():
                                f = cf(a, t)
                                if f >= 50: a_alvo.append((a, t, f))
                                
                        for i in range(min(3, len(elig))):
                            v = elig.iloc[i]
                            for j in [i+2, i+3]:
                                if j < len(elig):
                                    d = elig.iloc[j]
                                    if not d["Is_Target"]:
                                        f = cf(v, d)
                                        if f >= 50: a_princ.append((v, d, f))
                                        elif f >= 40: a_sec.append((v, d, f))
                                        
                        st.markdown("---")
                        for title, arr in [("🎯 AVB do Alvo", a_alvo), ("⚔️ AVB Principal", a_princ), ("🛡️ AVB Secundário", a_sec)]:
                            st.markdown(f"### {title}")
                            if arr:
                                for v, d, f in arr: 
                                    st.dataframe(render_avb(v, d, f), use_container_width=True, hide_index=True)
                            else: 
                                st.info("Nenhum confronto.")
            except Exception as e:
                st.error(f"Erro no processamento: {e}")