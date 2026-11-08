import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7 - Elite", layout="wide")
st.title("🐾 DIB 2.7 - Analisador de Elite")

# =========================================================
# CONSTANTES E TRADUÇÕES
# =========================================================
TRAP_EMOJIS = {1: "🟥 1", 2: "🟦 2", 3: "⬜ 3", 4: "⬛ 4", 5: "🟧 5", 6: "🔳 6"}
CAT_BASE = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}

def parse_trap(trap_num):
    return TRAP_EMOJIS.get(int(trap_num), "vacant")

# =========================================================
# EXTRAÇÃO DE DADOS
# =========================================================
def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)

        if not race_id_match or not r_date_match:
            st.error("Link inválido.")
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
        
        response = requests.get(api_url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        dogs = data.get("form", {}).get("dogs", [])
        
        registros = []
        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = dog.get("trapNum", "0")
            peso_atual = float(dog.get("weight", 0))
            peso_atual_str = dog.get("weight", "0") # Ex: "29.4kg"
            
            # Identificar a distância da corrida de hoje
            forms = dog.get("forms", [])
            dist_hoje = forms[0].get("distance", "480m") if forms else "480m"

            for corrida in forms:
                dist_corrida = corrida.get("distance", "")
                # Filtro: Apenas a distância exata
                if dist_corrida != dist_hoje:
                    continue

                reg = {
                    "Galgo": nome,
                    "Trap_Num": int(trap),
                    "Trap": parse_trap(trap),
                    "Dist": dist_hoje,
                    "Split": float(corrida.get("sectionalTime", 0)),
                    "CalTm": float(corrida.get("calcRTimes", 0)),
                    "Going": corrida.get("goingType", "N"),
                    "Bends": corrida.get("bndPos", "4444"),
                    "Fin": str(corrida.get("outcomeDesc", "6")),
                    "Remarks": str(corrida.get("closeUpCmnt", "")),
                    "Grade": corrida.get("grade", "A5"),
                    "Peso": float(corrida.get("weight", peso_atual)), # Peso daquela corrida
                    "Data_Corrida": datetime.strptime(corrida.get("raceTime", r_date_str)[:10], "%Y-%m-%d")
                }
                registros.append(reg)
        
        return pd.DataFrame(registros), peso_atual_str, r_date_obj
    except Exception as e:
        st.error(f"Erro ao buscar dados: {e}")
        return None, None, None

# =========================================================
# ENGINE DE CÁLCULO DIB 2.7
# =========================================================
def calcular_dib(df, peso_atual_str, data_hoje):
    # 1. Filtrar Corridas Válidas (Ignorar T e HP para tempos)
    df['Valida_Tempo'] = df['Grade'].apply(lambda x: not (x.startswith('T') or x.startswith('HP')))

    resultados = []
    
    for galgo, group in df.groupby("Galgo"):
        group = group.sort_values("Data_Corrida", ascending=False)
        
        # Última corrida (para dias e peso)
        ultima = group.iloc[0]
        dias_sem_correr = (data_hoje - ultima['Data_Corrida']).days
        
        # Filtrar apenas as válidas para cálculos de tempo
        validas = group[group['Valida_Tempo']].copy()
        
        # Peso (Cálculo de variação)
        peso_atual_num = float(re.sub(r'[^\d.]', '', peso_atual_str)) if peso_atual_str else 0
        peso_ult_num = ultima['Peso']
        dif_peso = abs(peso_atual_num - peso_ult_num)
        
        # Categoria Base (última corrida válida)
        grade_ultima = validas.iloc[0]['Grade'] if not validas.empty else "A5"
        cat_base = CAT_BASE.get(grade_ultima[:2], 10)

        # Time Ajustado e Recuperação
        tempos_ajustados = []
        recuperacoes = []
        
        for _, row in validas.iterrows():
            t = row['CalTm']
            # Going
            going_val = str(row['Going']).replace('N', '0')
            if going_val.startswith('+'):
                t -= float(going_val.replace('+', '')) / 100
            elif going_val.startswith('-'):
                t += float(going_val.replace('-', '')) / 100
            
            # Tráfego Severo
            remarks = row['Remarks'].lower()
            if 'baulked' in remarks: t -= 0.20
            if any(x in remarks for x in ['crd', 'bmp', 'fcd']): t -= 0.10
            
            tempos_ajustados.append(t)
            
            # Recuperação Blindada
            if not any(x in remarks for x in ['crd', 'bmp', 'blk', 'baulked', 'fcd-ck', 'evch', 'mvdoff']):
                # Posições: 1º digito do Bends é a entrada, Fin é a saída
                p_inicio = int(row['Bends'][0]) if row['Bends'] and row['Bends'][0].isdigit() else 4
                p_fim = int(row['Fin']) if row['Fin'].isdigit() else 4
                # Recuperação = (Ganhou / Perdeu) - Ex: 5º para 2º = Ganhou 3
                recuperacoes.append(p_inicio - p_fim)

        if not tempos_ajustados:
            continue

        # Médias (Time Decay 5,4,3,2,1)
        pesos_decay = [5, 4, 3, 2, 1][:len(tempos_ajustados)]
        media_time = np.average(tempos_ajustados, weights=pesos_decay)
        
        pesos_split = pesos_decay[:len(validas)]
        media_split = np.average(validas['Split'].tolist(), weights=pesos_split) if len(validas) > 0 else 0
        
        # Ritmo final
        ritmo_final = media_time - media_split

        # Recuperação Média (formato XX.XX%)
        recup_media = (sum(recuperacoes) / len(recuperacoes) * 20) if recuperacoes else 0.0
        
        # Confiança
        confianca = min(len(validas) * 20, 100)
        
        # Trava de Confiança
        nome_exibicao = galgo
        if confianca < 60:
            nome_exibicao += " [BLOQUEADO]"

        resultados.append({
            "Galgo_Original": galgo,
            "Galgo": nome_exibicao,
            "Trap": ultima['Trap'],
            "Trap_Num": ultima['Trap_Num'],
            "Overall_Base": 0, # Calculado depois
            "Categoria": cat_base,
            "Fatores": "Velocidade", # Simulação
            "Perfil": "Frente" if int(ultima['Bends'][0]) <= 2 else "Atrás",
            "Histórico": f"{len(validas)}/{len(group)}",
            "Peso_Dif": dif_peso,
            "Dias": dias_sem_correr,
            "Split": validas.iloc[0]['Split'] if not validas.empty else 0,
            "Time": validas.iloc[0]['CalTm'] if not validas.empty else 0,
            "Time_Ajustado": np.mean(tempos_ajustados),
            "Media_Split": media_split,
            "Media_Time": media_time,
            "Ritmo_Final": ritmo_final,
            "Recup_Media": recup_media,
            "Confianca": confianca,
            "AVB1": 0, "AVB2": 0, "AVB3": 0
        })

    df_agg = pd.DataFrame(resultados)

    # Normalização para o Overall (Base 100 pts)
    def min_max(series, invert=False):
        if series.max() == series.min(): return pd.Series([50]*len(series), index=series.index)
        if invert: return ((series.max() - series) / (series.max() - series.min())) * 100
        return ((series - series.min()) / (series.max() - series.min())) * 100

    # Velocidade baseada em Tempos
    pts_time_aj = min_max(df_agg['Time_Ajustado'], invert=True) * 0.40
    pts_media_time = min_max(df_agg['Media_Time'], invert=True) * 0.30
    pts_media_split = min_max(df_agg['Media_Split'], invert=True) * 0.15
    pts_ritmo = min_max(df_agg['Ritmo_Final'], invert=True) * 0.15

    # Base Total
    df_agg['Overall_Base'] = pts_time_aj + pts_media_time + pts_media_split + pts_ritmo
    
    # Adicionando Categoria, Recuperação e Fatores
    df_agg['Overall'] = df_agg['Overall_Base'] + df_agg['Categoria'] + (df_agg['Recup_Media'] / 10)
    
    # Arredondando e Finalizando
    df_agg = df_agg.round(2)
    
    # Alvos (🎯)
    top3_split = df_agg['Media_Split'].nsmallest(3).values
    df_agg['Alvo'] = df_agg.apply(lambda r: "🎯" if (r['Media_Split'] not in top3_split and r['Recup_Media'] <= 0) else "", axis=1)
    df_agg['Galgo'] = df_agg['Alvo'] + " " + df_agg['Galgo']

    # Ordenar por Trap para a Projeção
    df_proj = df_agg.sort_values("Trap_Num").reset_index(drop=True)
    
    return df_proj

# =========================================================
# INTERFACE
# =========================================================
st.subheader("🔗 Link do Racing Post")
url_input = st.text_input("Cole o link da corrida:")

if st.button("Analisar", type="primary"):
    if url_input:
        df_raw, peso_str, data_hoje = extrair_dados_racingpost(url_input)
        
        if df_raw is not None and not df_raw.empty:
            df_proj = calcular_dib(df_raw, peso_str, data_hoje)
            
            # Exibição da Projeção
            st.subheader("📋 Planilha de Projeção (17 Colunas)")
            
            cols = ["Trap", "Galgo", "Overall", "Categoria", "Fatores", "Perfil", 
                    "Histórico", "Peso_Dif", "Dias", "Split", "Time", 
                    "Time_Ajustado", "Media_Split", "Media_Time", "Ritmo_Final", 
                    "Recup_Media", "Confianca"]
            
            st.dataframe(df_proj[cols], use_container_width=True, hide_index=True)

            # Classificação Geral (Medalhas)
            df_rank = df_proj.sort_values("Overall", ascending=False).head(3)
            podium = " > ".join([f"{med} {row['Trap']}" for med, (_, row) in zip(["🥇", "🥈", "🥉"], df_rank.iterrows())])
            st.markdown(f"**Classificação Geral:** {podium}")

            # AVBs (Simulação de Layout)
            st.subheader("⚔️ Tabelas de AVB")
            
            st.markdown("### 2ª Planilha: AVB Principal")
            st.info("Confrontos de Elite: Top 1 vs Top 3, Top 2 vs Top 4.")
            # Aqui o código monta as tabelas de Vencedor x Desafiante visualmente
            top_caes = df_rank.head(4).to_dict('records')
            if len(top_caes) >= 2:
                st.write(f"**Confronto 1:** {top_caes[0]['Trap']} {top_caes[0]['Galgo']} vs {top_caes[2]['Trap']} {top_caes[2]['Galgo']}")
                st.write(f"**Confronto 2:** {top_caes[1]['Trap']} {top_caes[1]['Galgo']} vs {top_caes[3]['Trap']} {top_caes[3]['Galgo']}")