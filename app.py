import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7 - Projeção", layout="wide")
st.title("🐾 Análise DIB 2.7")

# =========================================================
# 🔧 FUNÇÕES AUXILIARES (DIB 2.7)
# =========================================================
def parse_going(g):
    if pd.isna(g): return 0.0
    g = str(g).strip().upper().replace(" ", "")
    if g == "N" or g == "NORMAL": return 0.0
    m = re.match(r"([+-]?)(\d+)", g)
    if not m: return 0.0
    val = int(m.group(2)) / 100.0
    return -val if m.group(1) == "-" else val

def parse_traffic(remarks):
    r = str(remarks).upper()
    if "BAULKED" in r or "BLK" in r: return 0.20
    if "CRD" in r or "BMP" in r or "FCD" in r: return 0.10
    return 0.0

def is_traffic(remarks):
    r = str(remarks).upper()
    return any(x in r for x in ["CRD", "BMP", "BLK", "BAULKED", "FCD", "MVDOFF", "EVCH"])

def get_bends(b_str):
    digits = [int(c) for c in str(b_str) if c.isdigit()]
    if len(digits) >= 4: return digits[0], digits[-1]
    return 4, 4

def calc_prop_points(series, is_reverse=False):
    s = pd.to_numeric(series, errors="coerce").fillna(series.max() if not is_reverse else series.min())
    if s.max() == s.min(): return pd.Series([40] * len(s), index=s.index)
    
    min_val, max_val = s.min(), s.max()
    # Se for tempo/split, menor é melhor. Se for ritmo/recup, maior é melhor.
    if not is_reverse: # Menor é melhor
        return 40 - ((s - min_val) / (max_val - min_val) * 35)
    else: # Maior é melhor
        return 5 + ((s - min_val) / (max_val - min_val) * 35)

def get_cat_base(grade):
    mapping = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}
    g = str(grade).strip().upper()
    return mapping.get(g, 10)

def check_alvo(split_med, top3_splits, recup_med):
    if pd.isna(split_med): return False
    is_split_bad = split_med > top3_splits[-1] if len(top3_splits) == 3 else False
    is_recup_bad = recup_med <= 0
    return is_split_bad and is_recup_bad

# =========================================================
# EXTRAIR DADOS DO RACING POST (Mantido o seu código)
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

        # Tenta pegar a distância da corrida, se não conseguir, assume a da primeira corrida
        dist_corrida = data.get("race", {}).get("dist", 480) 
        
        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            st.warning("Nenhum dado encontrado.")
            return None

        registros = []
        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = dog.get("trapNum", "0")
            peso = float(dog.get("weight", 0))
            
            forms = dog.get("forms", [])
            if not forms: continue

            data_ultima = datetime.strptime(forms[0].get("raceTime", r_date_str)[:10], "%Y-%m-%d")
            dias_sem_correr = (r_date_obj - data_ultima).days
            
            # Pega a classe de hoje (assumindo que a primeira corrida é a de hoje ou baseada no URL)
            class_hoje = forms[0].get("grade", "A6")

            for corrida in forms:
                reg = {
                    "Galgo": nome, "Trap_Num": int(trap) if str(trap).isdigit() else 0,
                    "Split": float(corrida.get("sectionalTime", 0) or 0), 
                    "CalTm": float(corrida.get("calcRTimes", 0) or 0),
                    "Going": corrida.get("goingType", "N"),
                    "Bends": corrida.get("bndPos", "4444"),
                    "Fin": str(corrida.get("outcomeDesc", "6")),
                    "Remarks": corrida.get("closeUpCmnt", ""),
                    "Peso_Atual": peso, "Dias_Sem_Correr": dias_sem_correr,
                    "Grade": corrida.get("grade", "A6"),
                    "Dist": corrida.get("dist", 480),
                    "Data_Corrida": corrida.get("raceTime", "")[:10]
                }
                registros.append(reg)
        return pd.DataFrame(registros), dist_corrida, class_hoje
    except Exception as e:
        st.error(f"Erro: {e}")
        return None, None, None

# =========================================================
# INTERFACE E LÓGICA DIB 2.7
# =========================================================
url_input = st.text_input("Link da corrida", placeholder="https://greyhoundbet.racingpost.com/#card/race_id=...&r_date=...")

if st.button("Analisar Corrida", type="primary") and url_input:
    df, dist_hoje, class_hoje = extrair_dados_racingpost(url_input)
    
    if df is not None and not df.empty:
        # 1. Filtrar apenas a distância correta e classes oficiais
        df = df[(df["Dist"] == dist_hoje) & (~df["Grade"].str.contains("T|HP", na=False))]
        df = df[df["CalTm"] > 0] # Ignorar tempos zerados

        # 2. Cálculos Base
        df["Going_adj"] = df["Going"].apply(parse_going)
        df["Traffic_adj"] = df["Remarks"].apply(parse_traffic)
        df["CalTm_Ajust"] = df["CalTm"] - df["Going_adj"] - df["Traffic_adj"]
        df["Has_Traffic"] = df["Remarks"].apply(is_traffic)
        
        # Bends e Fin
        df[["Bend_1", "Bend_Fin"]] = df.apply(lambda x: pd.Series(get_bends(x["Bends"])), axis=1)
        df["Fin_num"] = pd.to_numeric(df["Fin"].str.extract(r'(\d+)')[0], errors="coerce").fillna(6)

        # Agrupamento por Galgo (Médias Ponderadas - Time Decay)
        def weighted_avg(group, col):
            weights = [5, 4, 3, 2, 1][:len(group)]
            return np.average(group[col], weights=weights)

        res = []
        for nome, group in df.groupby("Galgo"):
            group = group.sort_values("Data_Corrida", ascending=False)
            
            # Time Decay
            m_time = weighted_avg(group, "CalTm")
            m_split = weighted_avg(group, "Split")
            m_ajust = group["CalTm_Ajust"].mean()
            ritmo = m_time - m_split
            
            # Recuperação Blindada
            clean_runs = group[~group["Has_Traffic"]]
            if not clean_runs.empty:
                recup_vals = ((clean_runs["Bend_1"] - clean_runs["Fin_num"]) / 6) * 100
                recup_med = recup_vals.mean()
            else:
                recup_med = 0.0
            
            # Categoria
            cat_base = get_cat_base(class_hoje)
            cat_ult = group.iloc[0]["Grade"]
            # Lógica simplificada de subida/descida baseada na primeira letra (A)
            nivel_hoje = int(re.search(r'\d+', class_hoje).group()) if re.search(r'\d+', class_hoje) else 6
            nivel_ult = int(re.search(r'\d+', cat_ult).group()) if re.search(r'\d+', cat_ult) else 6
            cat_final = cat_base + (2 if nivel_ult < nivel_hoje else (-2 if nivel_ult > nivel_hoje else 0))

            # Confiança
            confianca = len(group) * 20

            # Travas e Alvos
            is_trial = str(group.iloc[0]["Grade"]).startswith("T")
            block_winner = is_trial or confianca < 60
            
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
                "Block_Winner": block_winner,
                "Perfil": "⚠️ Irregular" if group["Has_Traffic"].sum() > 1 else "✅ Limpo",
                "Histórico": "·".join(group["Grade"].head(5)),
                "Peso": group.iloc[0]["Peso_Atual"],
                "Dias": group.iloc[0]["Dias_Sem_Correr"],
                "Split": group.iloc[0]["Split"],
                "Time": group.iloc[0]["CalTm"]
            })

        agg = pd.DataFrame(res)
        
        # 3. Definir Top 3 Splits para a Trava de Alvo
        top3_splits = agg["Media Split"].nsmallest(3).tolist()
        agg["Is_Target"] = agg.apply(lambda x: check_alvo(x["Media Split"], top3_splits, x["Recup. Média"]), axis=1)

        # 4. Calcular Base de Velocidade (Pontos Proporcionais)
        pts_ajust = calc_prop_points(agg["Time Ajustado"])
        pts_mtime = calc_prop_points(agg["Media Time"])
        pts_msplit = calc_prop_points(agg["Media Split"])
        pts_ritmo = calc_prop_points(agg["Ritmo final"], is_reverse=True) # menor ritmo é melhor
        
        agg["Base_Velocidade"] = pts_ajust + pts_mtime + pts_msplit + pts_ritmo
        
        # 5. Overall Final
        perfil_pts = agg["Perfil"].apply(lambda x: 10 if "Limpo" in x else 5)
        recup_pts = (5 + (agg["Recup. Média"] / 10)).clip(0, 10)
        
        agg["Overall"] = agg["Base_Velocidade"] + agg["Categoria"] + perfil_pts + recup_pts

        # Ordenar pelo Overall
        agg = agg.sort_values("Overall", ascending=False).reset_index(drop=True)
        
        # =========================================================
        # MATCHMAKING E AVBs
        # =========================================================
        elegiveis = agg[~agg["Block_Winner"]].copy()
        elegiveis = elegiveis.reset_index(drop=True)

        # Função para calcular Força
        def calc_forca(row_v, row_d):
            diff_over = row_v["Overall"] - row_d["Overall"]
            diff_tempo = 100 * (row_d["Media Time"] - row_v["Media Time"])
            diff_recup = (row_v["Recup. Média"] - row_d["Recup. Média"]) / 2
            diff_cat = (row_v["Categoria"] - row_d["Categoria"]) * 2
            return diff_over + diff_tempo + diff_recup + diff_cat

        # --- GERAR AVB DO ALVO ---
        avbs_alvo = []
        targets = agg[agg["Is_Target"]].sort_values("Overall")
        for _, target in targets.iterrows():
            # Quem ataca o alvo? Todos elegíveis com Overall maior
            attackers = elegiveis[elegiveis["Overall"] > target["Overall"]]
            for _, atk in attackers.iterrows():
                forca = calc_forca(atk, target)
                if forca >= 50.0:
                    # É um Alvo e também Principal? (Star)
                    is_star = atk["Galgo"] in elegiveis["Galgo"].head(4).values # Simplificação Top 4
                    avbs_alvo.append({"V": atk, "D": target, "Forca": forca, "Star": is_star, "Tipo": "Alvo"})

        # --- GERAR AVB PRINCIPAL (MATCHMAKING DE ELITE) ---
        avbs_principal = []
        for i in range(3): # Top 1, 2, 3
            if i >= len(elegiveis): break
            v = elegiveis.iloc[i]
            # Pula uma posição: testa contra 3 e 4 (índices i+2 e i+3)
            for j in [i+2, i+3]:
                if j < len(elegiveis):
                    d = elegiveis.iloc[j]
                    if d["Is_Target"]: continue # Se já é alvo, não entra aqui
                    
                    forca = calc_forca(v, d)
                    if forca >= 40.0:
                        tipo = "Principal" if forca >= 50.0 else "Secundário"
                        avbs_principal.append({"V": v, "D": d, "Forca": forca, "Star": False, "Tipo": tipo})

        # =========================================================
        # EXIBIÇÃO (STREAMLIT)
        # =========================================================
        st.subheader(f"Race {class_hoje} · {dist_hoje}m")
        
        # Planilha de Projeção
        st.markdown("### 📊 Planilha de Projeção (Overall)")
        proj_cols = ["Trap", "Galgo", "Overall", "Categoria", "Perfil", "Histórico", "Peso", "Dias", "Split", "Time", "Time Ajustado", "Média Split", "Media Time", "Ritmo final", "Recup. Média", "Confiança"]
        st.dataframe(agg[proj_cols].round(2), use_container_width=True, hide_index=True)

        # Tabela de Alvos
        st.markdown("### 🎯 Planilha de AVB do Alvo")
        if avbs_alvo:
            for avb in avbs_alvo:
                v, d, f = avb["V"], avb["D"], avb["Forca"]
                star = "⭐ " if avb["Star"] else ""
                st.success(f"**{star}🟥 {v['Trap']} {v['Galgo']} vence 🎯 {d['Trap']} {d['Galgo']} (Força: {f:.2f})**")
        else:
            st.info("Nenhum AVB de Alvo.")

        # Tabela Principal
        st.markdown("### 🎯 Planilha de AVB Principal (Elite)")
        if any(a["Tipo"] == "Principal" for a in avbs_principal):
            for avb in [a for a in avbs_principal if a["Tipo"] == "Principal"]:
                v, d, f = avb["V"], avb["D"], avb["Forca"]
                st.success(f"**🟥 {v['Trap']} {v['Galgo']} vence 🟥 {d['Trap']} {d['Galgo']} (Força: {f:.2f})**")
        else:
            st.info("Nenhum AVB Principal.")

        # Tabela Secundária
        st.markdown("### 🎯 Planilha de AVB Secundário")
        if any(a["Tipo"] == "Secundário" for a in avbs_principal):
            for avb in [a for a in avbs_principal if a["Tipo"] == "Secundário"]:
                v, d, f = avb["V"], avb["D"], avb["Forca"]
                st.warning(f"**🟥 {v['Trap']} {v['Galgo']} vence 🟥 {d['Trap']} {d['Galgo']} (Força: {f:.2f})**")
        else:
            st.info("Nenhum AVB Secundário.")