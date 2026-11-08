import streamlit as st
import pandas as pd
import numpy as np
import re
import requests

st.set_page_config(page_title="DIB 2.7 - Projeção", layout="wide")
st.title("🐾 Análise DIB 2.7")

# =========================================================
# 🔧 PESOS E TABELAS DO DIB 2.7
# =========================================================
PESO_AVB1 = 0.40
PESO_AVB2 = 0.35
PESO_AVB3 = 0.25
GOING_TABLE = {"N": 0.0, "NORMAL": 0.0, "+05": 0.05, "-05": -0.05,
               "+10": 0.10, "-10": -0.10, "+20": 0.20, "-20": -0.20}
REMARKS_TABLE = {"Q": 2.0, "QAW": 2.5, "AW": 1.0, "LD": 1.0, "CLR": 1.5,
                 "FCD": 0.5, "BMP": -1.0, "CRD": -1.5, "ALD": -2.0,
                 "STB": -0.5, "FCD2": 0.0}
TRAP_BONUS = {1: 2.0, 2: 1.0, 3: 0.0, 4: 0.0, 5: -1.0, 6: -2.0}
PESO_TRAVA_VALOR = 1.5

def parse_going(g):
    if pd.isna(g): return 0.0
    g = str(g).strip().upper().replace(" ", "")
    if g in GOING_TABLE: return GOING_TABLE[g]
    m = re.match(r"([+-]?)(\d+)", g)
    if not m: return 0.0
    return (-1 if m.group(1) == "-" else 1) * int(m.group(2)) / 100.0

def parse_remarks(r):
    if pd.isna(r): return 0.0
    total = 0.0
    for p in re.split(r"[,/\s]+", str(r).upper()):
        if p in REMARKS_TABLE: total += REMARKS_TABLE[p]
    return total

def parse_bends(b):
    if pd.isna(b): return [4, 4, 4, 4]
    return [int(c) for c in str(b) if c.isdigit()] or [4, 4, 4, 4]

def zscore_invert(s):
    s = pd.to_numeric(s, errors="coerce").fillna(s.mean())
    if s.std() == 0 or pd.isna(s.std()):
        return pd.Series([50.0] * len(s), index=s.index)
    z = (s - s.mean()) / s.std()
    return (-z) * 15 + 50

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
        r_date = r_date_match.group(1)

        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={race_id}&r_date={r_date}&blocks=form"
        headers = {"User-Agent": "Mozilla/5.0"}
        
        with st.spinner("Buscando dados no Racing Post..."):
            response = requests.get(api_url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()

        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado encontrado.")
            return None

        registros = []
        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = dog.get("trapNum", "0")
            peso = dog.get("weight", "0")
            for corrida in dog.get("forms", []):
                # Extraindo pista e data igual ao site
                track = corrida.get("trackName", "N/A")
                data_corrida = corrida.get("raceTime", "N/A")[:10]
                
                reg = {
                    "Galgo": nome,
                    "Trap_Num": int(trap) if str(trap).isdigit() else 0,
                    "Trap": f"[{trap}]", # Formatado igual ao site
                    "Track": track,
                    "Data": data_corrida,
                    "Dist": corrida.get("distance", "480m"),
                    "Split": corrida.get("sectionalTime"),
                    "CalTm": corrida.get("calcRTimes"),
                    "Going": corrida.get("goingType"),
                    "Bends": corrida.get("bndPos"),
                    "Fin": corrida.get("outcomeDesc"),
                    "Remarks": corrida.get("closeUpCmnt", ""),
                    "Peso_Atual": peso,
                }
                registros.append(reg)
        return pd.DataFrame(registros)
    except Exception as e:
        st.error(f"Erro: {e}")
        return None

# =========================================================
# INTERFACE
# =========================================================
st.subheader("🔗 Cole o link da corrida do Racing Post")
url_input = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/race_id=...")

if st.button("Analisar Corrida", type="primary"):
    if url_input:
        df = extrair_dados_racingpost(url_input)
        if df is not None and not df.empty:
            
            for c in ["Split", "CalTm", "Peso_Atual"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["Going_offset"] = df["Going"].apply(parse_going)
            df["CalTm_adj"] = df["CalTm"] - df["Going_offset"]
            df["Remark_bonus"] = df["Remarks"].apply(parse_remarks)
            df["Bends_list"] = df["Bends"].apply(parse_bends)
            df["Bends_avg"] = df["Bends_list"].apply(np.mean)
            df["Bends_early"] = df["Bends_list"].apply(lambda x: x[0])
            df["Fin_num"] = pd.to_numeric(df["Fin"].astype(str).str.extract(r'(\d+)')[0], errors="coerce").fillna(6)

            # Agregação
            agg = df.groupby("Galgo").agg(
                Trap=("Trap", "last"),
                Track=("Track", "last"),
                Data=("Data", "last"),
                Dist=("Dist", "last"),
                Split_med=("Split", "mean"),
                CalTm_med=("CalTm_adj", "mean"),
                Going_med=("Going_offset", "mean"),
                Bends_med=("Bends_avg", "mean"),
                Bends_early_med=("Bends_early", "mean"),
                Fin_med=("Fin_num", "mean"),
                Remark_total=("Remark_bonus", "sum"),
                Peso_med=("Peso_Atual", "mean"),
                Peso_ult=("Peso_Atual", "last"),
                CalTm_std=("CalTm_adj", "std"),
            ).reset_index()
            
            agg["CalTm_std"] = agg["CalTm_std"].fillna(0)
            agg["Peso_var"] = agg["Peso_ult"] - agg["Peso_med"]

            # AVBs e Overall
            agg["AVB1"] = zscore_invert(agg["Split_med"]) * 0.4 + zscore_invert(agg["CalTm_med"]) * 0.6
            agg["AVB2"] = (zscore_invert(agg["Bends_early_med"]) * 0.5 + zscore_invert(agg["Bends_med"]) * 0.25 + zscore_invert(agg["Fin_med"]) * 0.25)
            agg["AVB3"] = zscore_invert(agg["CalTm_std"])
            agg["Overall_base"] = (agg["AVB1"] * PESO_AVB1 + agg["AVB2"] * PESO_AVB2 + agg["AVB3"] * PESO_AVB3)

            # Travas
            df["Split_z"] = df.groupby("Galgo")["Split"].transform(lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0)
            trava_split = df.groupby("Galgo")["Split_z"].apply(lambda x: (x > 1.5).sum() * -2.0).reset_index()
            trava_split.columns = ["Galgo", "Trava_Split"]
            
            # Trap para trava (precisamos do número puro)
            trap_ult = df.sort_values("Data").groupby("Galgo")["Trap_Num"].last().reset_index()
            trap_ult["Trava_Trap"] = trap_ult["Trap_Num"].map(TRAP_BONUS).fillna(0)
            
            agg["Trava_Peso"] = agg["Peso_var"].apply(lambda v: -PESO_TRAVA_VALOR if v < -0.5 else (PESO_TRAVA_VALOR if v > 0.5 else 0.0))
            
            agg = agg.merge(trava_split, on="Galgo", how="left").merge(trap_ult[["Galgo", "Trava_Trap"]], on="Galgo", how="left")
            
            agg["Bonus_Remarks"] = agg["Remark_total"].clip(-5, 5)
            agg["Forca_bruta"] = (agg["Overall_base"] + agg["Trava_Split"].fillna(0) + agg["Trava_Trap"].fillna(0) + agg["Trava_Peso"].fillna(0) + agg["Bonus_Remarks"])
            
            fmin, fmax = agg["Forca_bruta"].min(), agg["Forca_bruta"].max()
            agg["Força"] = ((agg["Forca_bruta"] - fmin) / (fmax - fmin) * 100 if fmax > fmin else 50.0)
            
            agg = agg.sort_values("Força", ascending=False).reset_index(drop=True)
            agg.insert(0, "Rank", agg.index + 1)

            # Exibição
            tab_proj, tab_avb, tab_match, tab_dados = st.tabs([
                "📋 Planilha de Projeção", "📊 Tabelas AVB", "⚔️ Matchmaking", "📄 Dados Brutos"
            ])

            with tab_proj:
                st.subheader("Planilha de Projeção")
                # Construindo a tabela com os nomes e a formatação do site
                proj = pd.DataFrame({
                    "Rank": agg["Rank"],
                    "Trp": agg["Trap"], # Agora com colchetes [1]
                    "Galgo": agg["Galgo"],
                    "Data": agg["Data"],
                    "Track": agg["Track"],
                    "Dist.": agg["Dist"],
                    "Split": agg["Split_med"].round(2),
                    "CalTm": agg["CalTm_med"].round(2),
                    "Bends": agg["Bends_med"].round(1),
                    "Fin": agg["Fin_med"].round(1),
                    "AVB1": agg["AVB1"].round(1),
                    "AVB2": agg["AVB2"].round(1),
                    "Força": agg["Força"].round(1)
                })
                st.dataframe(proj, use_container_width=True, hide_index=True)

            with tab_avb:
                st.subheader("Comparativo AVB 1 (Velocidade)")
                st.dataframe(agg[["Galgo", "AVB1", "Split_med", "CalTm_med"]].sort_values("AVB1", ascending=False).round(2), use_container_width=True, hide_index=True)
                
                st.subheader("Comparativo AVB 2 (Posicionamento)")
                st.dataframe(agg[["Galgo", "AVB2", "Bends_early_med", "Fin_med"]].sort_values("AVB2", ascending=False).round(2), use_container_width=True, hide_index=True)
                
                st.subheader("Comparativo AVB 3 (Consistência)")
                st.dataframe(agg[["Galgo", "AVB3", "CalTm_std"]].sort_values("AVB3", ascending=False).round(2), use_container_width=True, hide_index=True)

            with tab_match:
                st.subheader("Confrontos Sugeridos")
                pares = []
                for i in range(0, len(agg) - 1, 2):
                    a, b = agg.iloc[i], agg.iloc[i + 1]
                    dif = a["Força"] - b["Força"]
                    pares.append({
                        "Confronto": f"{a['Trap']} {a['Galgo']} vs {b['Trap']} {b['Galgo']}",
                        "Força A": round(a["Força"], 1),
                        "Força B": round(b["Força"], 1),
                        "Favorito": a["Galgo"] if dif >= 0 else b["Galgo"],
                        "Margem": round(abs(dif), 1),
                    })
                st.dataframe(pd.DataFrame(pares), use_container_width=True, hide_index=True)

            with tab_dados:
                st.dataframe(df.drop(columns=["Bends_list", "Trap_Num"]), use_container_width=True)