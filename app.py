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

def calc_prop_points(series, is_reverse=False):
    s = pd.to_numeric(series, errors="coerce").fillna(series.median())
    if s.max() == s.min(): return pd.Series([40] * len(s), index=s.index)
    min_val, max_val = s.min(), s.max()
    if not is_reverse: 
        return 40 - ((s - min_val) / (max_val - min_val) * 35)
    else: 
        return 5 + ((s - min_val) / (max_val - min_val) * 35)

def get_cat_base(grade):
    mapping = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}
    g = str(grade).strip().upper()
    return mapping.get(g, 10)

def check_alvo(split_med, top3_splits, recup_med):
    if pd.isna(split_med) or len(top3_splits) < 3: return False
    is_split_bad = split_med > top3_splits[-1]
    is_recup_bad = recup_med <= 0
    return is_split_bad and is_recup_bad

# =========================================================
# EXTRAIR DADOS DO RACING POST
# =========================================================
def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)

        if not race_id_match or not r_date_match:
            st.error("Link inválido. Precisa ter 'race_id' e 'r_date'.")
            return None

        race_id = race_id_match.group(1)
        r_date_str = r_date_match.group(1)
        r_date_obj = datetime.strptime(r_date_str, "%Y-%m-%d")

        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={race_id}&r_date={r_date_str}&blocks=form"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*"
        }
        
        response = requests.get(api_url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado de galgo encontrado no link.")
            return None

        registros = []
        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = dog.get("trapNum", "0")
            peso = float(dog.get("weight", 0) or 0)
            
            forms = dog.get("forms", [])
            if not forms: continue

            data_ultima = datetime.strptime(forms[0].get("raceTime", r_date_str)[:10], "%Y-%m-%d")
            dias_sem_correr = (r_date_obj - data_ultima).days

            for corrida in forms:
                reg = {
                    "Galgo": nome, 
                    "Trap_Num": int(trap) if str(trap).isdigit() else 0,
                    "Split": float(corrida.get("sectionalTime", 0) or 0), 
                    "CalTm": float(corrida.get("calcRTimes", 0) or 0),
                    "Going": corrida.get("goingType", "N"),
                    "Bends": corrida.get("bndPos", "4444"),
                    "Fin": str(corrida.get("outcomeDesc", "6")),
                    "Remarks": corrida.get("closeUpCmnt", ""),
                    "Peso_Atual": peso, 
                    "Dias_Sem_Correr": dias_sem_correr,
                    "Grade": corrida.get("grade", "A6"),
                    "Data_Corrida": corrida.get("raceTime", "")[:10]
                }
                registros.append(reg)
        
        df_final = pd.DataFrame(registros)
        if df_final.empty:
            st.warning("A tabela de dados ficou vazia após a extração.")
            return None
            
        return df_final
    except Exception as e:
        st.error(f"Erro na extração: {e}")
        return None

# =========================================================
# INTERFACE E LÓGICA DIB 2.7
# =========================================================
url_input = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/race_id=...")

# NOVO CAMPO: Classe da corrida
class_hoje = st.text_input("Classe da Corrida (ex: A4, A5, A6)", value="A4").upper()

if st.button("Analisar Corrida", type="primary") and url_input:
    with st.spinner("Processando DIB 2.7..."):
        df = extrair_dados_racingpost(url_input)
        
        if df is not None:
            try:
                # 1. Filtragem de Classes Oficiais e Tratamento
                df = df[~df["Grade"].str.contains("T|HP", na=False)]
                df = df[df["CalTm"] > 0] 

                if df.empty:
                    st.warning("Nenhum galgo com corrida oficial válida nesta distância.")
                else:
                    # 2. Cálculos Base
                    df["Going_adj"] = df["Going"].apply(parse_going)
                    df["Traffic_adj"] = df["Remarks"].apply(parse_traffic)
                    df["CalTm_Ajust"] = df["CalTm"] - df["Going_adj"] - df["Traffic_adj"]
                    df["Has_Traffic"] = df["Remarks"].apply(is_traffic)
                    
                    bends_split = df["Bends"].apply(lambda x: pd.Series(get_bends(x)))
                    df["Bend_1"] = bends_split[0]
                    df["Bend_Fin"] = bends_split[1]
                    
                    df["Fin_num"] = pd.to_numeric(df["Fin"].str.extract(r'(\d+)')[0], errors="coerce").fillna(6)

                    # 3. Agrupamento e Médias Ponderadas
                    def weighted_avg(group, col):
                        weights = np.array([5, 4, 3, 2, 1][:len(group)])
                        return np.average(group[col], weights=weights)

                    res = []
                    for nome, group in df.groupby("Galgo"):
                        group = group.sort_values("Data_Corrida", ascending=False)
                        
                        m_time = weighted_avg(group, "CalTm")
                        m_split = weighted_avg(group, "Split")
                        m_ajust = group["CalTm_Ajust"].mean()
                        ritmo = m_time - m_split
                        
                        clean_runs = group[~group["Has_Traffic"]]
                        if not clean_runs.empty:
                            recup_vals = ((clean_runs["Bend_1"] - clean_runs["Fin_num"]) / 6) * 100
                            recup_med = recup_vals.mean()
                        else:
                            recup_med = 0.0
                        
                        # Categoria (Usando a classe inserida pelo usuário)
                        cat_ult = group.iloc[0]["Grade"]
                        nivel_hoje = int(re.search(r'\d+', class_hoje).group()) if re.search(r'\d+', class_hoje) else 6
                        nivel_ult = int(re.search(r'\d+', cat_ult).group()) if re.search(r'\d+', cat_ult) else 6
                        cat_base = get_cat_base(class_hoje)
                        cat_final = cat_base + (2 if nivel_ult < nivel_hoje else (-2 if nivel_ult > nivel_hoje else 0))

                        confianca = len(group) * 20
                        is_trial = str(group.iloc[0]["Grade"]).startswith("T")
                        
                        res.append({
                            "Trap": group.iloc[0]["Trap_Num"],
                            "Galgo": nome,
                            "Categoria": cat_final,
                            "Media Time": m_time,
                            "Media Split": m_split,
                            "Time Ajustado": m_ajust,
                            "Ritmo final": ritmo,
                            "Recup. Média": recup_med,
                            "Confiança": confianca,
                            "Block_Winner": is_trial or confianca < 60,
                            "Perfil": "⚠️ Irregular" if group["Has_Traffic"].sum() > 1 else "✅ Limpo",
                            "Histórico": "·".join(group["Grade"].head(5)),
                            "Peso": group.iloc[0]["Peso_Atual"],
                            "Dias": group.iloc[0]["Dias_Sem_Correr"],
                            "Split": group.iloc[0]["Split"],
                            "Time": group.iloc[0]["CalTm"]
                        })

                    agg = pd.DataFrame(res)
                    
                    # 4. Travas e Alvos
                    top3_splits = agg["Media Split"].nsmallest(3).tolist()
                    agg["Is_Target"] = agg.apply(lambda x: check_alvo(x["Media Split"], top3_splits, x["Recup. Média"]), axis=1)

                    # 5. Pontuação Overall
                    pts_ajust = calc_prop_points(agg["Time Ajustado"])
                    pts_mtime = calc_prop_points(agg["Media Time"])
                    pts_msplit = calc_prop_points(agg["Media Split"])
                    pts_ritmo = calc_prop_points(agg["Ritmo final"], is_reverse=True)
                    
                    agg["Base_Velocidade"] = pts_ajust + pts_mtime + pts_msplit + pts_ritmo
                    
                    perfil_pts = agg["Perfil"].apply(lambda x: 10 if "Limpo" in x else 5)
                    recup_pts = (5 + (agg["Recup. Média"] / 10)).clip(0, 10)
                    
                    agg["Overall"] = agg["Base_Velocidade"] + agg["Categoria"] + perfil_pts + recup_pts
                    agg = agg.sort_values("Overall", ascending=False).reset_index(drop=True)
                    
                    # 6. Matchmaking
                    elegiveis = agg[~agg["Block_Winner"]].reset_index(drop=True)
                    
                    def calc_forca(v, d):
                        diff_over = v["Overall"] - d["Overall"]
                        diff_tempo = 100 * (d["Media Time"] - v["Media Time"])
                        diff_recup = (v["Recup. Média"] - d["Recup. Média"]) / 2
                        diff_cat = (v["Categoria"] - d["Categoria"]) * 2
                        return diff_over + diff_tempo + diff_recup + diff_cat

                    avbs_alvo = []
                    targets = agg[agg["Is_Target"]].sort_values("Overall")
                    for _, tgt in targets.iterrows():
                        attackers = elegiveis[elegiveis["Overall"] > tgt["Overall"]]
                        for _, atk in attackers.iterrows():
                            f = calc_forca(atk, tgt)
                            if f >= 50.0:
                                is_star = atk["Galgo"] in elegiveis["Galgo"].head(4).values
                                avbs_alvo.append({"V": atk, "D": tgt, "Forca": f, "Star": is_star})

                    avbs_principal, avbs_sec = [], []
                    for i in range(min(3, len(elegiveis))):
                        v = elegiveis.iloc[i]
                        for j in [i+2, i+3]:
                            if j < len(elegiveis):
                                d = elegiveis.iloc[j]
                                if d["Is_Target"]: continue
                                f = calc_forca(v, d)
                                if f >= 50.0: avbs_principal.append({"V": v, "D": d, "Forca": f})
                                elif f >= 40.0: avbs_sec.append({"V": v, "D": d, "Forca": f})

                    # --- EXIBIÇÃO ---
                    st.markdown(f"### 🏁 {class_hoje} · 480m")
                    
                    st.markdown("**Classificação Geral**")
                    medals = ["🥇", "🥈", "🥉", "4º", "5º", "6º"]
                    ranking = " > ".join([f"{medals[i]} [{row['Trap']}] {row['Galgo']}" for i, row in agg.iterrows()])
                    st.info(ranking)

                    st.markdown("### 📊 Planilha de Projeção")
                    # CORREÇÃO: Adicionado "Time" na lista de colunas
                    cols = ["Trap", "Galgo", "Overall", "Categoria", "Perfil", "Histórico", "Peso", "Dias", "Split", "Time", "Time Ajustado", "Media Time", "Recup. Média", "Confiança"]
                    st.dataframe(agg[cols].round(2), use_container_width=True, hide_index=True)

                    st.markdown("### 🎯 Planilha de AVB do Alvo")
                    if avbs_alvo:
                        for a in avbs_alvo:
                            star = "⭐ " if a["Star"] else ""
                            st.success(f"{star}**{a['V']['Trap']} {a['V']['Galgo']}** vence 🎯 **{a['D']['Trap']} {a['D']['Galgo']}** (Força: {a['Forca']:.2f})")
                    else: st.info("Nenhum AVB de Alvo.")

                    st.markdown("### 🎯 Planilha de AVB Principal")
                    if avbs_principal:
                        for a in avbs_principal:
                            st.success(f"**{a['V']['Trap']} {a['V']['Galgo']}** vence **{a['D']['Trap']} {a['D']['Galgo']}** (Força: {a['Forca']:.2f})")
                    else: st.info("Nenhum AVB Principal.")

                    st.markdown("### 🎯 Planilha de AVB Secundário")
                    if avbs_sec:
                        for a in avbs_sec:
                            st.warning(f"**{a['V']['Trap']} {a['V']['Galgo']}** vence **{a['D']['Trap']} {a['D']['Galgo']}** (Força: {a['Forca']:.2f})")
                    else: st.info("Nenhum AVB Secundário.")
                    
            except Exception as e:
                st.error(f"Erro no processamento dos cálculos: {e}")