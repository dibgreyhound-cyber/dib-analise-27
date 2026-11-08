import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

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
        r_date_str = r_date_match.group(1)
        r_date_obj = datetime.strptime(r_date_str, "%Y-%m-%d")

        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={race_id}&r_date={r_date_str}&blocks=form"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://greyhoundbet.racingpost.com/"
        }
        
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
            
            forms = dog.get("forms", [])
            if not forms:
                continue

            # Pega a corrida mais recente para as colunas "atuais"
            ultima_corrida = forms[0]
            
            # Calcula dias sem correr
            data_ultima = datetime.strptime(ultima_corrida.get("raceTime", r_date_str)[:10], "%Y-%m-%d")
            dias_sem_correr = (r_date_obj - data_ultima).days

            # Histórico (Vitórias / Corridas)
            vitorias = sum(1 for c in forms if str(c.get("outcomeDesc", "")).strip() == "1")
            historico = f"{vitorias}/{len(forms)}"

            for corrida in forms:
                reg = {
                    "Galgo": nome,
                    "Trap_Num": int(trap) if str(trap).isdigit() else 0,
                    "Trap": f"[{trap}]",
                    "Split": corrida.get("sectionalTime"),
                    "CalTm": corrida.get("calcRTimes"),
                    "Going": corrida.get("goingType"),
                    "Bends": corrida.get("bndPos"),
                    "Fin": corrida.get("outcomeDesc"),
                    "Remarks": corrida.get("closeUpCmnt", ""),
                    "Peso_Atual": peso,
                    "Dias_Sem_Correr": dias_sem_correr,
                    "Historico": historico,
                    "Data_Corrida": corrida.get("raceTime", "")[:10],
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
url_input = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/...")

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

            # Agregação (Médias por Galgo)
            agg = df.groupby("Galgo").agg(
                Trap_Num=("Trap_Num", "last"),
                Trap=("Trap", "last"),
                Split_med=("Split", "mean"),
                CalTm_med=("CalTm_adj", "mean"),
                Bends_med=("Bends_avg", "mean"),
                Bends_early_med=("Bends_early", "mean"),
                Fin_med=("Fin_num", "mean"),
                Remark_total=("Remark_bonus", "sum"),
                Peso_ult=("Peso_Atual", "last"),
                CalTm_std=("CalTm_adj", "std"),
                Dias_Sem_Correr=("Dias_Sem_Correr", "last"),
                Historico=("Historico", "last"),
                Split_ult=("Split", "last"),
                CalTm_ult=("CalTm_adj", "last")
            ).reset_index()
            
            agg["CalTm_std"] = agg["CalTm_std"].fillna(0)

            # AVBs
            agg["AVB1"] = zscore_invert(agg["Split_med"]) * 0.4 + zscore_invert(agg["CalTm_med"]) * 0.6
            agg["AVB2"] = (zscore_invert(agg["Bends_early_med"]) * 0.5 + zscore_invert(agg["Bends_med"]) * 0.25 + zscore_invert(agg["Fin_med"]) * 0.25)
            agg["AVB3"] = zscore_invert(agg["CalTm_std"])
            agg["Overall_base"] = (agg["AVB1"] * PESO_AVB1 + agg["AVB2"] * PESO_AVB2 + agg["AVB3"] * PESO_AVB3)

            # Travas
            df["Split_z"] = df.groupby("Galgo")["Split"].transform(lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0)
            trava_split = df.groupby("Galgo")["Split_z"].apply(lambda x: (x > 1.5).sum() * -2.0).reset_index()
            trava_split.columns = ["Galgo", "Trava_Split"]
            
            trap_ult = df.sort_values("Data_Corrida").groupby("Galgo")["Trap_Num"].last().reset_index()
            trap_ult["Trava_Trap"] = trap_ult["Trap_Num"].map(TRAP_BONUS).fillna(0)
            
            agg = agg.merge(trava_split, on="Galgo", how="left").merge(trap_ult[["Galgo", "Trava_Trap"]], on="Galgo", how="left")
            
            agg["Bonus_Remarks"] = agg["Remark_total"].clip(-5, 5)
            agg["Forca_bruta"] = (agg["Overall_base"] + agg["Trava_Split"].fillna(0) + agg["Trava_Trap"].fillna(0) + agg["Bonus_Remarks"])
            
            fmin, fmax = agg["Forca_bruta"].min(), agg["Forca_bruta"].max()
            agg["Força"] = ((agg["Forca_bruta"] - fmin) / (fmax - fmin) * 100 if fmax > fmin else 50.0)

            # Criando as colunas solicitadas para a Planilha de Projeção (17 colunas)
            # 1. Trap, 2. Galgo, 3. Overall, 4. Categoria, 5. Fatores, 6. Perfil, 7. Histórico, 8. Peso, 
            # 9. Dias sem correr, 10. Split, 11. Time, 12. Time ajustado, 13. Média Split, 14. Média Time, 
            # 15. Ritmo final, 16. Recuperação média, 17. Confiança
            
            def get_categoria(overall):
                if overall > 65: return "A1"
                elif overall > 55: return "A2"
                elif overall > 45: return "A3"
                else: return "A4"

            def get_fatores(row):
                max_avb = max(row["AVB1"], row["AVB2"], row["AVB3"])
                if max_avb == row["AVB1"]: return "Velocidade"
                elif max_avb == row["AVB2"]: return "Posição"
                else: return "Consistência"

            def get_perfil(bends):
                if bends <= 2.0: return "Frente"
                elif bends <= 4.0: return "Meio"
                else: return "Atrás"

            proj = pd.DataFrame({
                "Trap": agg["Trap"],
                "Galgo": agg["Galgo"],
                "Overall": agg["Overall_base"].round(1),
                "Categoria": agg["Overall_base"].apply(get_categoria),
                "Fatores": agg.apply(get_fatores, axis=1),
                "Perfil": agg["Bends_early_med"].apply(get_perfil),
                "Histórico": agg["Historico"],
                "Peso": agg["Peso_ult"],
                "Dias s/ Correr": agg["Dias_Sem_Correr"],
                "Split": agg["Split_ult"].round(2),
                "Time": agg["CalTm_ult"].round(2),
                "Time Ajust.": agg["CalTm_med"].round(2),
                "Média Split": agg["Split_med"].round(2),
                "Média Time": agg["CalTm_med"].round(2),
                "Ritmo Final": agg["Fin_med"].round(1),
                "Recuperação": (agg["Bends_med"] - agg["Fin_med"]).round(1),
                "Confiança": (100 - (agg["CalTm_std"] * 100).clip(0, 100)).round(1)
            })

            # Ordenar a Projeção pelo Trap (Ordem Numérica, como você pediu)
            proj = proj.sort_values("Trap", key=lambda x: x.str.extract(r'(\d+)')[0].astype(int))

            # Exibição
            tab_proj, tab_avb, tab_match, tab_dados = st.tabs([
                "📋 Projeção (17 Colunas)", "📊 Tabelas AVB", "⚔️ Matchmaking", "📄 Dados Brutos"
            ])

            with tab_proj:
                st.subheader("Planilha de Projeção")
                st.dataframe(proj, use_container_width=True, hide_index=True)

            with tab_avb:
                st.subheader("AVB 1 — Velocidade")
                avb1_df = agg[["Galgo", "AVB1", "Split_med", "CalTm_med"]].sort_values("AVB1", ascending=False).rename(columns={"Split_med": "Split Médio", "CalTm_med": "Time Médio"})
                st.dataframe(avb1_df.round(2), use_container_width=True, hide_index=True)
                
                st.subheader("AVB 2 — Posicionamento")
                avb2_df = agg[["Galgo", "AVB2", "Bends_early_med", "Fin_med"]].sort_values("AVB2", ascending=False).rename(columns={"Bends_early_med": "Bends Início", "Fin_med": "Final Médio"})
                st.dataframe(avb2_df.round(2), use_container_width=True, hide_index=True)
                
                st.subheader("AVB 3 — Consistência")
                avb3_df = agg[["Galgo", "AVB3", "CalTm_std"]].sort_values("AVB3", ascending=False).rename(columns={"CalTm_std": "Variação de Tempo"})
                st.dataframe(avb3_df.round(2), use_container_width=True, hide_index=True)

            with tab_match:
                st.subheader("Confrontos Sugeridos")
                # Ordenar por força para o matchmaking fazer sentido
                agg_forca = agg.sort_values("Força", ascending=False).reset_index(drop=True)
                pares = []
                for i in range(0, len(agg_forca) - 1, 2):
                    a, b = agg_forca.iloc[i], agg_forca.iloc[i + 1]
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