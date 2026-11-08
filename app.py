import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7 - Elite", layout="wide")
st.title("🐾 DIB 2.7 - Analisador de Elite")

# =========================================================
# CONSTANTES
# =========================================================
TRAP_EMOJIS = {1: "🟥 1", 2: "🟦 2", 3: "⬜ 3", 4: "⬛ 4", 5: "🟧 5", 6: "🔳 6"}
CAT_BASE = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}

def parse_trap(trap_num):
    try:
        return TRAP_EMOJIS.get(int(trap_num), "vacant")
    except:
        return "vacant"

# =========================================================
# EXTRAÇÃO DE DADOS (COM TRATAMENTO DE ERRO)
# =========================================================
def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)

        if not race_id_match or not r_date_match:
            return None, None, None, "Link inválido. Certifique-se de que o link tem 'race_id' e 'r_date'."

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
        
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()

        dogs = data.get("form", {}).get("dogs", [])
        if not dogs:
            return None, None, None, "O Racing Post retornou o card, mas sem dados de galgos."

        registros = []
        peso_atual_geral = "0"
        
        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = dog.get("trapNum", "0")
            peso_atual_geral = str(dog.get("weight", "0"))
            
            forms = dog.get("forms", [])
            if not forms: continue
            
            dist_hoje = forms[0].get("distance", "480m")

            for corrida in forms:
                if corrida.get("distance", "") != dist_hoje:
                    continue

                # Proteção contra valores nulos
                split_val = corrida.get("sectionalTime")
                caltm_val = corrida.get("calcRTimes")
                
                reg = {
                    "Galgo": nome,
                    "Trap_Num": int(trap) if str(trap).isdigit() else 0,
                    "Trap": parse_trap(trap),
                    "Dist": dist_hoje,
                    "Split": float(split_val) if split_val and str(split_val).replace('.','',1).isdigit() else 0.0,
                    "CalTm": float(caltm_val) if caltm_val and str(caltm_val).replace('.','',1).isdigit() else 0.0,
                    "Going": str(corrida.get("goingType", "N")),
                    "Bends": str(corrida.get("bndPos", "4444")),
                    "Fin": str(corrida.get("outcomeDesc", "6")),
                    "Remarks": str(corrida.get("closeUpCmnt", "")),
                    "Grade": str(corrida.get("grade", "A5")),
                    "Peso": float(corrida.get("weight", 0)) if str(corrida.get("weight", "0")).replace('.','',1).isdigit() else 0.0,
                    "Data_Corrida": datetime.strptime(corrida.get("raceTime", r_date_str)[:10], "%Y-%m-%d")
                }
                registros.append(reg)
        
        return pd.DataFrame(registros), peso_atual_geral, r_date_obj, None

    except Exception as e:
        return None, None, None, f"Erro de conexão com o Racing Post: {e}"

# =========================================================
# ENGINE DIB 2.7
# =========================================================
def calcular_dib(df, peso_atual_str, data_hoje):
    df['Valida_Tempo'] = df['Grade'].apply(lambda x: not (x.startswith('T') or x.startswith('HP')))

    resultados = []
    
    for galgo, group in df.groupby("Galgo"):
        group = group.sort_values("Data_Corrida", ascending=False)
        ultima = group.iloc[0]
        
        dias_sem_correr = (data_hoje - ultima['Data_Corrida']).days
        
        validas = group[group['Valida_Tempo']].copy()
        
        # Peso
        try:
            peso_atual_num = float(re.sub(r'[^\d.]', '', peso_atual_str))
        except:
            peso_atual_num = 0.0
        peso_ult_num = ultima['Peso']
        dif_peso = abs(peso_atual_num - peso_ult_num) if peso_atual_num > 0 else 0.0

        grade_ultima = validas.iloc[0]['Grade'] if not validas.empty else "A5"
        cat_base = CAT_BASE.get(grade_ultima[:2], 10)

        tempos_ajustados = []
        recuperacoes = []
        
        for _, row in validas.iterrows():
            t = row['CalTm']
            if t == 0: continue

            # Going
            going_val = str(row['Going']).replace('N', '0').strip()
            if going_val.startswith('+'):
                try: t -= float(going_val.replace('+', '')) / 100
                except: pass
            elif going_val.startswith('-'):
                try: t += float(going_val.replace('-', '')) / 100
                except: pass
            
            remarks = row['Remarks'].lower()
            if 'baulked' in remarks: t -= 0.20
            if any(x in remarks for x in ['crd', 'bmp', 'fcd']): t -= 0.10
            
            tempos_ajustados.append(t)
            
            # Recuperação
            if not any(x in remarks for x in ['crd', 'bmp', 'blk', 'baulked', 'fcd-ck', 'evch', 'mvdoff']):
                try:
                    p_inicio = int(row['Bends'][0]) if row['Bends'] and row['Bends'][0].isdigit() else 4
                    p_fim = int(row['Fin']) if row['Fin'].isdigit() else 4
                    recuperacoes.append(p_inicio - p_fim)
                except:
                    pass

        if not tempos_ajustados:
            continue

        pesos_decay = [5, 4, 3, 2, 1][:len(tempos_ajustados)]
        media_time = np.average(tempos_ajustados, weights=pesos_decay)
        
        splits_validos = [s for s in validas['Split'].tolist() if s > 0]
        pesos_split = [5, 4, 3, 2, 1][:len(splits_validos)]
        media_split = np.average(splits_validos, weights=pesos_split) if splits_validos else 0
        
        ritmo_final = media_time - media_split
        recup_media = (sum(recuperacoes) / len(recuperacoes) * 20) if recuperacoes else 0.0
        confianca = min(len(validas) * 20, 100)
        
        nome_exibicao = galgo + (" [BLOQUEADO]" if confianca < 60 else "")

        # Trap inicial para perfil
        try:
            trap_init = int(ultima['Bends'][0])
        except:
            trap_init = 4

        resultados.append({
            "Galgo_Original": galgo,
            "Galgo": nome_exibicao,
            "Trap": ultima['Trap'],
            "Trap_Num": ultima['Trap_Num'],
            "Overall_Base": 0,
            "Categoria": cat_base,
            "Fatores": "Velocidade",
            "Perfil": "Frente" if trap_init <= 2 else "Atrás",
            "Histórico": f"{len(validas)}/{len(group)}",
            "Peso_Dif": round(dif_peso, 1),
            "Dias": dias_sem_correr,
            "Split": validas.iloc[0]['Split'] if not validas.empty else 0,
            "Time": validas.iloc[0]['CalTm'] if not validas.empty else 0,
            "Time_Ajustado": round(np.mean(tempos_ajustados), 2),
            "Media_Split": round(media_split, 2),
            "Media_Time": round(media_time, 2),
            "Ritmo_Final": round(ritmo_final, 2),
            "Recup_Media": round(recup_media, 2),
            "Confianca": confianca,
        })

    if not resultados:
        return None

    df_agg = pd.DataFrame(resultados)

    def min_max(series, invert=False):
        if series.max() == series.min(): return pd.Series([50]*len(series), index=series.index)
        if invert: return ((series.max() - series) / (series.max() - series.min())) * 100
        return ((series - series.min()) / (series.max() - series.min())) * 100

    df_agg['Overall_Base'] = (min_max(df_agg['Time_Ajustado'], True) * 0.40) + \
                             (min_max(df_agg['Media_Time'], True) * 0.30) + \
                             (min_max(df_agg['Media_Split'], True) * 0.15) + \
                             (min_max(df_agg['Ritmo_Final'], True) * 0.15)
    
    df_agg['Overall'] = (df_agg['Overall_Base'] + df_agg['Categoria'] + (df_agg['Recup_Media'] / 10)).round(2)
    
    top3_split = df_agg['Media_Split'].nsmallest(3).values
    df_agg['Alvo'] = df_agg.apply(lambda r: "🎯" if (r['Media_Split'] not in top3_split and r['Recup_Media'] <= 0) else "", axis=1)
    df_agg['Galgo'] = df_agg['Alvo'] + " " + df_agg['Galgo']

    return df_agg.sort_values("Trap_Num").reset_index(drop=True)

# =========================================================
# INTERFACE
# =========================================================
st.subheader("🔗 Link do Racing Post")
url_input = st.text_input("Cole o link da corrida:")

if st.button("Analisar", type="primary"):
    if url_input:
        with st.spinner("Buscando e processando dados... Aguarde."):
            df_raw, peso_str, data_hoje, erro = extrair_dados_racingpost(url_input)
            
            if erro:
                st.error(erro)
            elif df_raw is None or df_raw.empty:
                st.warning("Nenhum dado válido encontrado. Verifique se a corrida já tem histórico.")
            else:
                df_proj = calcular_dib(df_raw, peso_str, data_hoje)
                
                if df_proj is None or df_proj.empty:
                    st.warning("Não foi possível calcular as médias (faltam dados de tempo).")
                else:
                    st.subheader("📋 Planilha de Projeção")
                    
                    cols = ["Trap", "Galgo", "Overall", "Categoria", "Fatores", "Perfil", 
                            "Histórico", "Peso_Dif", "Dias", "Split", "Time", 
                            "Time_Ajustado", "Media_Split", "Media_Time", "Ritmo_Final", 
                            "Recup_Media", "Confianca"]
                    
                    st.dataframe(df_proj[cols], use_container_width=True, hide_index=True)

                    df_rank = df_proj.sort_values("Overall", ascending=False).head(3)
                    podium = " > ".join([f"{med} {row['Trap']}" for med, (_, row) in zip(["🥇", "🥈", "🥉"], df_rank.iterrows())])
                    st.markdown(f"### 🏆 Classificação Geral: {podium}")