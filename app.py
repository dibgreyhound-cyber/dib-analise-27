import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7 - Projeção", layout="wide")
st.title("🐾 Análise DIB 2.7")

# =========================================================
# 🔧 FUNÇÕES AUXILIARES
# =========================================================
def parse_going(g):
    if pd.isna(g) or g is None: return 0.0
    g = str(g).strip().upper().replace(" ", "")
    if g in ["N", "NORMAL"]: return 0.0
    m = re.match(r"([+-]?)(\d+)", g)
    if not m: return 0.0
    val = int(m.group(2)) / 100.0
    return -val if m.group(1) == "-" else val

def parse_traffic(remarks):
    if pd.isna(remarks): return 0.0
    r = str(remarks).upper()
    if "BAULKED" in r or "BLK" in r: return 0.20
    if "CRD" in r or "BMP" in r or "FCD" in r: return 0.10
    return 0.0

def is_traffic(remarks):
    if pd.isna(remarks): return False
    r = str(remarks).upper()
    return any(x in r for x in ["CRD", "BMP", "BLK", "BAULKED", "FCD", "MVDOFF", "EVCH"])

def get_bends(b_str):
    if pd.isna(b_str): return 4, 4
    digits = [int(c) for c in str(b_str) if c.isdigit()]
    if len(digits) >= 4: return digits[0], digits[-1]
    return 4, 4

def get_cat_base(grade_str):
    mapping = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}
    match = re.search(r'A(\d+)', str(grade_str).upper())
    if match:
        return mapping.get(f"A{match.group(1)}", 10)
    return 10

def calc_prop_points(series, max_pts, min_pts):
    s = pd.to_numeric(series, errors="coerce").fillna(series.median())
    if s.max() == s.min(): return pd.Series([(max_pts+min_pts)/2] * len(s), index=s.index)
    min_val, max_val = s.min(), s.max()
    return max_pts - ((s - min_val) / (max_val - min_val) * (max_pts - min_pts))

# =========================================================
# EXTRAIR DADOS (API RACING POST) - BLINDADO
# =========================================================
def extrair_dados(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)

        if not race_id_match or not r_date_match:
            st.error("Link inválido. Certifique-se de que copiou o link completo com 'race_id' e 'r_date'.")
            return None

        race_id = race_id_match.group(1)
        r_date_str = r_date_match.group(1)
        r_date_obj = datetime.strptime(r_date_str, "%Y-%m-%d")

        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={race_id}&r_date={r_date_str}&blocks=form"
        
        # Headers melhorados para evitar bloqueio
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://greyhoundbet.racingpost.com/",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        response = requests.get(api_url, headers=headers, timeout=15)
        
        # Verifica se o site respondeu com erro
        if response.status_code != 200:
            st.error(f"Erro no site: {response.status_code}. O site pode ter bloqueado a requisição.")
            return None
            
        try:
            data = response.json()
        except ValueError:
            st.error("O site não retornou dados válidos (JSON). Verifique se o link expirou ou se o site bloqueou o robô.")
            return None

        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado de galgo encontrado no link.")
            return None

        registros = []
        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = int(dog.get("trapNum", 0))
            peso_atual = float(dog.get("weight", 0) or 0)
            forms = dog.get("forms", [])
            if not forms: continue

            for corrida in forms:
                grade_val = "A6"
                for k in ["grade", "gr", "raceGrade", "grde", "class", "cls"]:
                    if k in corrida and corrida[k]:
                        val = str(corrida[k]).upper().strip()
                        match = re.search(r'^[A-Z]\d{1,2}', val)
                        if match:
                            grade_val = match.group(0)
                            break
                
                data_str = str(corrida.get("raceTime", ""))[:10]
                try:
                    data_obj = datetime.strptime(data_str, "%Y-%m-%d")
                    dias = (r_date_obj - data_obj).days
                except:
                    data_obj = None
                    dias = 0

                reg = {
                    "Galgo": nome, "Trap": trap, 
                    "Split": float(corrida.get("sectionalTime", 0) or 0),
                    "CalTm": float(corrida.get("calcRTimes", 0) or 0), 
                    "Going": corrida.get("goingType", "N"),
                    "Bends": corrida.get("bndPos", "4444"), 
                    "Fin": str(corrida.get("outcomeDesc", "6")),
                    "Remarks": corrida.get("closeUpCmnt", ""), 
                    "Peso_Atual": peso_atual,
                    "Dias": dias, "Grade": grade_val, 
                    "Data_Obj": data_obj,
                    "Distancia": int(corrida.get("dist", 0))
                }
                registros.append(reg)
        return pd.DataFrame(registros)
    except Exception as e:
        st.error(f"Erro na extração: {e}")
        return None

# =========================================================
# INTERFACE E LÓGICA DIB 2.7
# =========================================================
url_input = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/race_id=...")
classe_hoje = st.text_input("Classe da Corrida Hoje (ex: A4, A5, A6)", value="A4").upper().strip()

if st.button("Analisar Corrida", type="primary") and url_input:
    with st.spinner("Processando DIB 2.7..."):
        df_bruto = extrair_dados(url_input)
        
        if df_bruto is not None:
            try:
                # Filtrar distância exata e remover corridas sem tempo
                dist_hoje = df_bruto["Distancia"].iloc[0]
                df = df_bruto[(df_bruto["Distancia"] == dist_hoje) & (df_bruto["CalTm"] > 0)].copy()
                
                # Ordenar por data decrescente
                df = df.sort_values("Data_Obj", ascending=False)

                # Filtrar apenas classes A oficiais
                df = df[df["Grade"].str.match(r'^A\d{1,2}$', na=False)]

                if df.empty:
                    st.warning("Nenhum galgo com corrida oficial válida nesta distância.")
                else:
                    df["Going_adj"] = df["Going"].apply(parse_going)
                    df["Traffic_adj"] = df["Remarks"].apply(parse_traffic)
                    df["Time_Ajust"] = df["CalTm"] - df["Going_adj"] - df["Traffic_adj"]
                    df["Has_Traffic"] = df["Remarks"].apply(is_traffic)
                    
                    bends_split = df["Bends"].apply(lambda x: pd.Series(get_bends(x)))
                    df["Bend_1"] = bends_split[0]
                    df["Fin_num"] = pd.to_numeric(df["Fin"].str.extract(r'(\d+)')[0], errors="coerce").fillna(6)

                    res = []
                    for nome, group in df.groupby("Galgo"):
                        group = group.sort_values("Data_Obj", ascending=False)
                        ult = group.iloc[0]
                        
                        w = np.array([5, 4, 3, 2, 1][:len(group)])
                        m_time = np.average(group["CalTm"], weights=w)
                        m_split = np.average(group["Split"], weights=w)
                        m_ajust = group["Time_Ajust"].mean()
                        ritmo = m_time - m_split
                        
                        clean_runs = group[~group["Has_Traffic"]]
                        if not clean_runs.empty:
                            recup_vals = ((clean_runs["Bend_1"] - clean_runs["Fin_num"]) / 6) * 100
                            recup_med = recup_vals.mean()
                            ganhou = (recup_vals > 0).sum()
                            perdeu = (recup_vals < 0).sum()
                            recup_str = f"{recup_med:.2f}% ({ganhou}/{perdeu})"
                        else:
                            recup_med = 0.0
                            recup_str = "0.00% (0/0)"
                        
                        match_h = re.search(r'A(\d+)', classe_hoje)
                        match_u = re.search(r'A(\d+)', ult["Grade"])
                        n_h = int(match_h.group(1)) if match_h else 6
                        n_u = int(match_u.group(1)) if match_u else 6
                        
                        cat_base = get_cat_base(classe_hoje)
                        
                        if n_u < n_h:
                            cat_mod = 2 # Desceu
                        elif n_u > n_h:
                            cat_mod = -2 # Subiu
                        else:
                            cat_mod = 0
                            
                        cat_final = cat_base + cat_mod
                        
                        f_mom = 3.0 if ult["Fin"] == "1st" else (-2.0 if ult["Fin_num"] >= 4 and n_u <= n_h else 0.0)
                        f_peso = 0.0
                        f_dias = -5.0 if ult["Dias"] < 4 else (-3.0 if 29 <= ult["Dias"] <= 45 else (-5.0 if ult["Dias"] > 45 else 0.0))
                        
                        rems = str(ult["Remarks"]).upper()
                        f_rem = 1.5 if "EP" in rems or "LD" in rems else 0.0
                        f_rem += 5.0 if "CLRRN" in rems else 0.0
                        f_rem -= 10.0 if "SAW" in rems else 0.0
                        f_rem -= 7.0 if "CRD1" in rems or "BMP1" in rems else 0.0
                        
                        f_total = f_mom + f_peso + f_dias + f_rem
                        
                        t_count = group["Has_Traffic"].sum()
                        perfil = "✅ Limpo" if t_count <= 1 else ("⚠️ Irregular" if t_count == 2 else "🔴 Trombador")
                        p_pts = 10 if t_count <= 1 else (5 if t_count == 2 else 2.5)
                        
                        conf = len(group) * 20
                        block = ult["Grade"].startswith("T") or conf < 60

                        res.append({
                            "Trap": ult["Trap"], "Galgo": nome, 
                            "Cat": cat_final, "Mod": cat_mod,
                            "Fatores": f_total, "Perfil": perfil, "P_pts": p_pts,
                            "Grade": "·".join(group["Grade"].head(5)), 
                            "Peso": ult["Peso_Atual"], "Dias": ult["Dias"],
                            "Split": ult["Split"], "Time": ult["CalTm"], "Time_Ajust": m_ajust, 
                            "M_Split": m_split, "M_Time": m_time, "Ritmo": ritmo,
                            "Recup": recup_med, "Recup_Str": recup_str, 
                            "Confianca": conf, "Block": block
                        })
                    
                    agg = pd.DataFrame(res)
                    
                    pts_ajust = calc_prop_points(agg["Time_Ajust"], 40, 5)
                    pts_mtime = calc_prop_points(agg["M_Time"], 30, 5)
                    pts_msplit = calc_prop_points(agg["M_Split"], 15, 2)
                    pts_ritmo = calc_prop_points(agg["Ritmo"], 15, 2)
                    
                    agg["Vel_pts"] = pts_ajust + pts_mtime + pts_msplit + pts_ritmo
                    
                    recup_pts = (5 + (agg["Recup"] / 10)).clip(0, 10)
                    
                    agg["Overall"] = agg["Vel_pts"] + agg["Cat"] + agg["P_pts"] + recup_pts + agg["Fatores"]
                    agg = agg.sort_values("Overall", ascending=False).reset_index(drop=True)
                    
                    top3_splits = agg["M_Split"].nsmallest(3).tolist()
                    agg["Is_Target"] = (agg["M_Split"] > top3_splits[-1]) & (agg["Recup"] <= 0)
                    
                    st.markdown(f"### 🏁 {classe_hoje} · {dist_hoje}m")
                    medals = ["🥇", "🥈", "🥉", "4º", "5º", "6º"]
                    ranking = " > ".join([f"{medals[i]} [{row['Trap']}] {row['Galgo']}" for i, row in agg.iterrows()])
                    st.info(ranking)

                    cols = ["Trap", "Galgo", "Overall", "Cat", "Mod", "Fatores", "Perfil", "Grade", "Dias", "Split", "Time", "Time_Ajust", "M_Split", "M_Time", "Recup_Str", "Confianca"]
                    st.dataframe(agg[cols].round(2), use_container_width=True, hide_index=True)

                    elegiveis = agg[~agg["Block"]].reset_index(drop=True)
                    
                    def calc_forca(v, d):
                        return (v["Overall"] - d["Overall"]) + 100*(d["M_Time"] - v["M_Time"]) + (v["Recup"] - d["Recup"])/2 + (v["Cat"] - d["Cat"])*2

                    avbs_alvo, avbs_princ, avbs_sec = [], [], []
                    
                    for _, tgt in agg[agg["Is_Target"]].iterrows():
                        for _, atk in elegiveis[elegiveis["Overall"] > tgt["Overall"]].iterrows():
                            f = calc_forca(atk, tgt)
                            if f >= 50: avbs_alvo.append((atk, tgt, f))

                    for i in range(min(3, len(elegiveis))):
                        v = elegiveis.iloc[i]
                        for j in [i+2, i+3]:
                            if j < len(elegiveis):
                                d = elegiveis.iloc[j]
                                if d["Is_Target"]: continue
                                f = calc_forca(v, d)
                                if f >= 50: avbs_princ.append((v, d, f))
                                elif f >= 40: avbs_sec.append((v, d, f))

                    st.markdown("### 🎯 Planilha de AVB do Alvo")
                    if avbs_alvo:
                        for v, d, f in avbs_alvo:
                            star = "⭐ " if v["Galgo"] in elegiveis["Galgo"].head(3).values else ""
                            st.success(f"{star}**[{v['Trap']}] {v['Galgo']}** vence 🎯 **[{d['Trap']}] {d['Galgo']}** (Força: {f:.2f})")
                    else: st.info("Nenhum AVB de Alvo.")

                    st.markdown("### 🎯 Planilha de AVB Principal")
                    if avbs_princ:
                        for v, d, f in avbs_princ:
                            st.success(f"**[{v['Trap']}] {v['Galgo']}** vence **[{d['Trap']}] {d['Galgo']}** (Força: {f:.2f})")
                    else: st.info("Nenhum AVB Principal.")

                    st.markdown("### 🎯 Planilha de AVB Secundário")
                    if avbs_sec:
                        for v, d, f in avbs_sec:
                            st.warning(f"**[{v['Trap']}] {v['Galgo']}** vence **[{d['Trap']}] {d['Galgo']}** (Força: {f:.2f})")
                    else: st.info("Nenhum AVB Secundário.")

            except Exception as e:
                st.error(f"Erro no processamento: {e}")