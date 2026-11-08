import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="DIB 2.7 - Projeção", layout="wide")
st.title("🐾 Análise DIB 2.7")

# =========================================================
# 🔧 FUNÇÕES AUXILIARES E CÁLCULOS
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

def get_trap_emoji(trap_num):
    trap_map = {1: "🟥 1", 2: "🟦 2", 3: "⬜ 3", 4: "⬛ 4", 5: "🟧 5", 6: "🔳 6"}
    return trap_map.get(int(trap_num), str(trap_num))

# =========================================================
# EXTRAIR DADOS (PISTA, HORA E CLASSE AUTOMÁTICOS)
# =========================================================
def extrair_dados(url):
    try:
        race_id = re.search(r"race_id=(\d+)", url).group(1)
        r_date_str = re.search(r"r_date=([\d-]+)", url).group(1)
        r_date_obj = datetime.strptime(r_date_str, "%Y-%m-%d")

        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={race_id}&r_date={r_date_str}&blocks=meeting,race,form"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://greyhoundbet.racingpost.com/"
        }
        
        response = requests.get(api_url, headers=headers, timeout=15)
        if response.status_code != 200:
            st.error(f"Bloqueio do Racing Post (Código {response.status_code}).")
            return None, None

        data = response.json()
        
        # --- BUSCA EXATA DOS METADADOS DA CORRIDA DE HOJE ---
        race_info = data.get("race", {})
        if not race_info:
            for r in data.get("meeting", {}).get("races", []):
                if str(r.get("raceId")) == str(race_id):
                    race_info = r
                    break

        pista = str(race_info.get("course") or race_info.get("courseName") or "Desconhecida").upper()
        race_num = str(race_info.get("raceNumber") or race_info.get("raceNo") or "X")
        
        # Pega a hora EXATA da prova de hoje (evita o bug do 14:14)
        raw_time = str(race_info.get("time") or race_info.get("raceTime") or "")
        hora_pista = "00:00"
        hora_br = "00:00"
        if raw_time:
            match_t = re.search(r'(\d{2}:\d{2})', raw_time)
            if match_t:
                hora_pista = match_t.group(1)
                h, m = map(int, hora_pista.split(':'))
                hora_br = f"{(h-3)%24:02d}:{m:02d}"

        # Pega a classe da prova de hoje de forma automática
        classe_hoje = str(race_info.get("raceClass") or race_info.get("class") or race_info.get("grade") or "").upper().strip()
        if not classe_hoje:
            # Se não achar direto, procura no título (ex: "A5 480m")
            title = str(race_info.get("raceTitle", ""))
            match_c = re.search(r'\b(A\d{1,2})\b', title)
            classe_hoje = match_c.group(1) if match_c else "A5"
            
        metadados = {
            "pista": pista,
            "hora_pista": hora_pista,
            "hora_br": hora_br,
            "race_num": race_num,
            "classe": classe_hoje
        }

        # --- EXTRAÇÃO DOS GALGOS ---
        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado encontrado no histórico dos galgos.")
            return None, None

        registros = []
        dist_hoje_str = "480" 
        total_caes = len(dogs)
        
        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = int(dog.get("trapNum", 0))
            peso_atual_card = float(dog.get("weight", 0) or 0)
            
            forms = dog.get("forms", [])
            if not forms: continue

            dist_hoje_str = re.sub(r'[^\d]', '', str(forms[0].get("distance", "480")))

            for corrida in forms:
                grade = corrida.get("gr") or corrida.get("grade")
                if not grade:
                    for v in corrida.values():
                        if isinstance(v, str):
                            m = re.match(r'^([A-Z]\d{1,2})$', v.strip().upper())
                            if m:
                                grade = m.group(1)
                                break
                if not grade: grade = "A5" 
                            
                dist_corrida_str = re.sub(r'[^\d]', '', str(corrida.get("distance", "480")))
                peso_corrida = float(corrida.get("weight", 0) or 0)

                reg = {
                    "Galgo": nome, "Trap_Num": trap, "Trap": get_trap_emoji(trap),
                    "Split": float(corrida.get("sectionalTime", 0) or 0),
                    "CalTm": float(corrida.get("calcRTimes", 0) or 0), 
                    "Going": corrida.get("goingType", "N"),
                    "Bends": corrida.get("bndPos", "4444"), 
                    "Fin": str(corrida.get("outcomeDesc", "6")),
                    "Remarks": corrida.get("closeUpCmnt", ""), 
                    "Peso_Atual_Card": peso_atual_card,
                    "Peso_Corrida": peso_corrida,
                    "Dias": (r_date_obj - datetime.strptime(corrida.get("raceTime", r_date_str)[:10], "%Y-%m-%d")).days, 
                    "Grade": grade, 
                    "Data_Corrida": corrida.get("raceTime", "")[:10],
                    "Distancia": dist_corrida_str,
                    "Total_Caes": total_caes
                }
                registros.append(reg)
                
        if not registros:
            return None, None
            
        return pd.DataFrame(registros), metadados
    except Exception as e:
        st.error(f"Erro na extração: {e}")
        return None, None

# =========================================================
# INTERFACE E LÓGICA DIB 2.7
# =========================================================
url_input = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/race_id=...")

if st.button("Analisar Corrida", type="primary") and url_input:
    with st.spinner("Processando DIB 2.7..."):
        df_bruto, meta = extrair_dados(url_input)
        
        if df_bruto is not None and not df_bruto.empty and meta is not None:
            try:
                classe_hoje = meta["classe"]
                dist_hoje = df_bruto["Distancia"].iloc[0]
                df = df_bruto[(df_bruto["Distancia"] == dist_hoje) & (df_bruto["CalTm"] > 0)].copy()
                
                if df.empty:
                    st.warning(f"Nenhum galgo com corrida válida na distância de {dist_hoje}m.")
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
                        group = group.sort_values("Data_Corrida", ascending=False)
                        ultima_geral = group.iloc[0]
                        
                        validas = group[group['Grade'].str.match(r'^A\d{1,2}$', na=False)].copy()
                        if validas.empty: 
                            continue 
                        
                        ultima_oficial = validas.iloc[0]
                        
                        def weighted_avg(g, col):
                            weights = np.array([5, 4, 3, 2, 1][:len(g)])
                            return np.average(g[col], weights=weights)
                        
                        m_time = weighted_avg(validas, "CalTm")
                        m_split = weighted_avg(validas, "Split")
                        m_ajust = validas["Time_Ajust"].mean()
                        ritmo = m_time - m_split
                        
                        clean_runs = validas[~validas["Has_Traffic"]]
                        if not clean_runs.empty:
                            recup_vals = ((clean_runs["Bend_1"] - clean_runs["Fin_num"]) / group["Total_Caes"].iloc[0]) * 100
                            recup_med = recup_vals.mean()
                            ganhou = (recup_vals > 0).sum()
                            perdeu = (recup_vals < 0).sum()
                            recup_str = f"{recup_med:.2f}% ({ganhou}/{perdeu})"
                        else:
                            recup_med = 0.0
                            recup_str = "0.00% (0/0)"
                        
                        # Categoria (Agora usando a classe automática)
                        match_h = re.search(r'A(\d+)', classe_hoje)
                        match_u = re.search(r'A(\d+)', ultima_oficial["Grade"])
                        
                        n_h = int(match_h.group(1)) if match_h else 5
                        n_u = int(match_u.group(1)) if match_u else 5
                        
                        cat_base = get_cat_base(classe_hoje)
                        
                        if n_u < n_h: cat_mod = 2
                        elif n_u > n_h: cat_mod = -2
                        else: cat_mod = 0
                            
                        cat_final = cat_base + cat_mod
                        
                        # Fatores Táticos
                        f_mom = 3.0 if ultima_oficial["Fin_num"] == 1 else (-2.0 if ultima_oficial["Fin_num"] >= 4 and n_u >= n_h else 0.0)
                        
                        dif_peso = abs(ultima_geral["Peso_Atual_Card"] - ultima_oficial["Peso_Corrida"])
                        f_peso = -5.0 if dif_peso > 2.0 else (-2.0 if 1.1 <= dif_peso <= 1.9 else 0.0)
                        
                        f_dias = -5.0 if ultima_geral["Dias"] < 4 else (-3.0 if 29 <= ultima_geral["Dias"] <= 45 else (-5.0 if ultima_geral["Dias"] > 45 else 0.0))
                        
                        rems = str(ultima_oficial["Remarks"]).upper()
                        f_rem = 1.5 if "EP" in rems or "LD" in rems else 0.0
                        f_rem += 5.0 if "CLRRN" in rems else 0.0
                        f_rem -= 10.0 if "SAW" in rems else 0.0
                        f_rem -= 7.0 if "CRD1" in rems or "BMP1" in rems else 0.0
                        
                        f_total = f_mom + f_peso + f_dias + f_rem
                        
                        t_count = validas["Has_Traffic"].sum()
                        perfil = "✅ Limpo" if t_count <= 1 else ("⚠️ Irregular" if t_count == 2 else "🔴 Trombador")
                        p_pts = 10 if t_count <= 1 else (5 if t_count == 2 else 2.5)
                        
                        conf = len(validas) * 20
                        is_blocked = ultima_geral["Grade"].startswith("T") or conf < 60
                        nome_exibicao = f"[BLOQUEADO] {nome}" if is_blocked else nome

                        res.append({
                            "Trap": ultima_geral["Trap"], "Galgo_Original": nome, "Galgo": nome_exibicao, 
                            "Cat_Base": cat_base, "Mod": cat_mod, "Cat": cat_final, 
                            "Fatores": round(f_total, 2), "Perfil": perfil, "P_pts": p_pts,
                            "Histórico": "·".join(validas["Grade"].head(5)), 
                            "Peso": ultima_oficial["Peso_Corrida"], "Dias": ultima_geral["Dias"],
                            "Split": ultima_oficial["Split"], "Time": ultima_oficial["CalTm"], "Time_Ajust": m_ajust, 
                            "M_Split": m_split, "M_Time": m_time, "Ritmo": ritmo,
                            "Recup": recup_med, "Recup_Str": recup_str, 
                            "Confianca": conf, "Block": is_blocked
                        })
                    
                    if res:
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
                        
                        # CABEÇALHO AUTOMÁTICO
                        header = f"### 🏁 {meta['pista']} {meta['hora_pista']} (BR {meta['hora_br']}) · Race {meta['race_num']} · {classe_hoje} · {dist_hoje}m"
                        st.markdown(header)

                        medals = ["🥇", "🥈", "🥉", "4º", "5º", "6º"]
                        ranking = " > ".join([f"{medals[i]} {row['Trap']} {row['Galgo'].replace('[BLOQUEADO] ', '')}" for i, row in agg.iterrows()])
                        st.info(ranking)

                        cols_proj = ["Trap", "Galgo", "Overall", "Cat_Base", "Mod", "Cat", "Fatores", "Perfil", "Histórico", "Peso", "Dias", "Split", "Time", "Time_Ajust", "M_Split", "M_Time", "Ritmo", "Recup_Str", "Confianca"]
                        st.dataframe(agg[cols_proj].round(2), use_container_width=True, hide_index=True)
                        
                        # AVBs
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

                        st.markdown("---")
                        st.markdown("### 🎯 Planilha de AVB do Alvo")
                        if avbs_alvo:
                            for v, d, f in avbs_alvo:
                                star = "⭐ " if v["Galgo_Original"] in elegiveis["Galgo_Original"].head(3).values else ""
                                st.success(f"{star}**[{v['Trap']}] {v['Galgo'].replace('[BLOQUEADO] ', '')}** vence 🎯 **[{d['Trap']}] {d['Galgo']}** (Força: {f:.2f})")
                        else: st.info("Nenhum confronto de Alvo gerado.")

                        st.markdown("### ⚔️ Planilha de AVB Principal (Elite)")
                        if avbs_princ:
                            for v, d, f in avbs_princ:
                                st.success(f"**[{v['Trap']}] {v['Galgo']}** vence **[{d['Trap']}] {d['Galgo']}** (Força: {f:.2f})")
                        else: st.info("Nenhum AVB Principal gerado (Força ≥ 50.0).")

                        st.markdown("### 🛡️ Planilha de AVB Secundário")
                        if avbs_sec:
                            for v, d, f in avbs_sec:
                                st.warning(f"**[{v['Trap']}] {v['Galgo']}** vence **[{d['Trap']}] {d['Galgo']}** (Força: {f:.2f})")
                        else: st.info("Nenhum AVB Secundário gerado (Força 40.0 a 49.9).")

            except Exception as e:
                st.error(f"Erro no processamento: {e}")