import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7 - Analisador de Elite", layout="wide")
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
# EXTRAÇÃO DE DADOS (CORRIGIDA)
# =========================================================
def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)

        if not race_id_match or not r_date_match:
            return None, None, None, "Link inválido."

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
            return None, None, None, "Nenhum galgo encontrado no link."

        registros = []
        
        # A distância de hoje é a distância da corrida mais recente (forms[0])
        # Pega a distância de um dos galgos para servir de base para todos
        dist_hoje = "480m"
        for dog in dogs:
            if dog.get("forms"):
                dist_hoje = dog["forms"][0].get("distance", "480m")
                break

        total_caes = len(dogs)

        for dog in dogs:
            nome = dog.get("dogName", "Desconhecido")
            trap = dog.get("trapNum", "0")
            peso_atual_str = str(dog.get("weight", "0"))
            
            try:
                peso_atual = float(re.sub(r'[^\d.]', '', peso_atual_str))
            except:
                peso_atual = 0.0

            forms = dog.get("forms", [])
            
            for corrida in forms:
                # FILTRO DE DISTÂNCIA E CORRIDAS VÁLIDAS
                dist_corrida = corrida.get("distance", "")
                if dist_corrida and dist_hoje and dist_corrida != dist_hoje:
                    continue # Pula se a distância for diferente
                
                grade = str(corrida.get("grade", "A5"))
                if grade.startswith('T') or grade.startswith('HP'):
                    # Se for Trial, salva apenas para dias sem correr, mas não para tempos
                    pass 

                reg = {
                    "Galgo": nome,
                    "Trap_Num": int(trap) if str(trap).isdigit() else 0,
                    "Trap": parse_trap(trap),
                    "Dist": dist_hoje,
                    "Split": float(corrida.get("sectionalTime", 0) or 0),
                    "CalTm": float(corrida.get("calcRTimes", 0) or 0),
                    "Going": str(corrida.get("goingType", "N") or "N"),
                    "Bends": str(corrida.get("bndPos", "4444") or "4444"),
                    "Fin": str(corrida.get("outcomeDesc", "6") or "6"),
                    "Remarks": str(corrida.get("closeUpCmnt", "") or ""),
                    "Grade": grade,
                    "Peso": float(corrida.get("weight", 0) or 0) if str(corrida.get("weight", "0")).replace('.','',1).isdigit() else 0.0,
                    "Data_Corrida": datetime.strptime(corrida.get("raceTime", r_date_str)[:10], "%Y-%m-%d")
                }
                registros.append(reg)
        
        df = pd.DataFrame(registros)
        df['Peso_Atual_Card'] = peso_atual
        df['Total_Caes'] = total_caes
        
        return df, None
    except Exception as e:
        return None, f"Erro na extração: {e}"

# =========================================================
# ENGINE DIB 2.7
# =========================================================
def calcular_dib(df, data_hoje):
    resultados = []
    
    for galgo, group in df.groupby("Galgo"):
        group = group.sort_values("Data_Corrida", ascending=False)
        ultima_geral = group.iloc[0]
        
        # 1. Dias sem correr
        dias_sem_correr = (data_hoje - ultima_geral['Data_Corrida']).days
        
        # 2. Validação de Tempo (Ignora T e HP)
        validas = group[~group['Grade'].str.startswith(('T', 'HP'))].copy()
        if validas.empty:
            continue
            
        ultima_valida = validas.iloc[0]
        
        # 3. Peso (Variação)
        peso_atual = group['Peso_Atual_Card'].iloc[0]
        peso_ultimo = ultima_valida['Peso']
        dif_peso = abs(peso_atual - peso_ultimo) if peso_atual > 0 and peso_ultimo > 0 else 0.0
        
        # 4. Categoria (Base)
        cat_base = CAT_BASE.get(ultima_valida['Grade'][:2], 10)
        
        tempos_ajustados = []
        recuperacoes = []
        
        for _, row in validas.iterrows():
            t = row['CalTm']
            if t == 0: continue

            # Time Ajustado (Going)
            going_val = str(row['Going']).replace('N', '0').strip()
            if going_val.startswith('+'):
                try: t -= float(going_val.replace('+', '')) / 100
                except: pass
            elif going_val.startswith('-'):
                try: t += float(going_val.replace('-', '')) / 100
                except: pass
            
            # Time Ajustado (Tráfego Severo)
            remarks = row['Remarks'].lower()
            if 'baulked' in remarks: t -= 0.20
            if any(x in remarks for x in ['crd', 'bmp', 'fcd']): t -= 0.10
            
            tempos_ajustados.append(t)
            
            # Recuperação Blindada
            if not any(x in remarks for x in ['crd', 'bmp', 'blk', 'baulked', 'fcd-ck', 'evch', 'mvdoff']):
                try:
                    p_inicio = int(row['Bends'][0]) if row['Bends'] and row['Bends'][0].isdigit() else 4
                    p_fim = int(row['Fin']) if row['Fin'].isdigit() else 4
                    ganho = p_inicio - p_fim
                    recup = (ganho / group['Total_Caes'].iloc[0]) * 100
                    recuperacoes.append(recup)
                except:
                    pass

        if not tempos_ajustados:
            continue

        # 5. Médias Ponderadas (Time Decay 5,4,3,2,1)
        pesos_decay = [5, 4, 3, 2, 1][:len(tempos_ajustados)]
        media_time = np.average(tempos_ajustados, weights=pesos_decay)
        
        splits_validos = [s for s in validas['Split'].tolist() if s > 0]
        pesos_split = [5, 4, 3, 2, 1][:len(splits_validos)]
        media_split = np.average(splits_validos, weights=pesos_split) if splits_validos else 0
        
        # 6. Ritmo Final e Recuperação
        ritmo_final = media_time - media_split
        recup_media = np.mean(recuperacoes) if recuperacoes else 0.0
        
        # 7. Confiança
        confianca = min(len(validas) * 20, 100)
        bloqueado = " [BLOQUEADO]" if confianca < 60 else ""
        
        # 8. Perfil e Posição Média
        try:
            pos_media = np.mean([int(b[0]) for b in validas['Bends'].tolist() if b and b[0].isdigit()])
        except:
            pos_media = 4.0
            
        perfil = "Frente" if pos_media <= 2.5 else "Atrás"

        resultados.append({
            "Galgo_Original": galgo,
            "Galgo": galgo + bloqueado,
            "Trap": ultima_geral['Trap'],
            "Trap_Num": ultima_geral['Trap_Num'],
            "Categoria": cat_base,
            "Perfil": perfil,
            "Posicao_Med": round(pos_media, 1),
            "Peso_Dif": round(dif_peso, 1),
            "Dias": dias_sem_correr,
            "Split": ultima_valida['Split'],
            "Time": ultima_valida['CalTm'],
            "Time_Ajustado": round(np.mean(tempos_ajustados), 2),
            "Media_Split": round(media_split, 2),
            "Media_Time": round(media_time, 2),
            "Ritmo_Final": round(ritmo_final, 2),
            "Recup_Media": round(recup_media, 2),
            "Confianca": confianca,
            "Historico": f"{len(validas)}/{len(group)}",
            "Overall": 0, "Forca": 0
        })

    if not resultados: return None
    df_agg = pd.DataFrame(resultados)

    # Cálculo do Overall (Base de Velocidade)
    def min_max(series, invert=False):
        if series.max() == series.min(): return pd.Series([50]*len(series), index=series.index)
        if invert: return ((series.max() - series) / (series.max() - series.min())) * 100
        return ((series - series.min()) / (series.max() - series.min())) * 100

    base_vel = (min_max(df_agg['Time_Ajustado'], True) * 0.40) + \
               (min_max(df_agg['Media_Time'], True) * 0.30) + \
               (min_max(df_agg['Media_Split'], True) * 0.15) + \
               (min_max(df_agg['Ritmo_Final'], True) * 0.15)
               
    df_agg['Overall'] = (base_vel + df_agg['Categoria'] + (df_agg['Recup_Media'] / 10)).round(2)

    # Travas de Alvo
    top3_split = df_agg['Media_Split'].nsmallest(3).values
    df_agg['Alvo'] = df_agg.apply(lambda r: "🎯" if (r['Media_Split'] not in top3_split and r['Recup_Media'] <= 0) else "", axis=1)
    df_agg['Galgo'] = df_agg['Alvo'] + " " + df_agg['Galgo']

    return df_agg.sort_values("Trap_Num").reset_index(drop=True)

# =========================================================
# INTERFACE
# =========================================================
url_input = st.text_input("🔗 Cole o link do Racing Post:")

if st.button("Analisar Corrida", type="primary"):
    if url_input:
        with st.spinner("Conectando ao Racing Post e aplicando DIB 2.7..."):
            df_raw, erro = extrair_dados_racingpost(url_input)
            
            if erro:
                st.error(erro)
            elif df_raw is None or df_raw.empty:
                st.warning("Nenhum dado válido encontrado.")
            else:
                df_proj = calcular_dib(df_raw, df_raw['Data_Corrida'].max())
                
                st.subheader("📋 Planilha de Projeção")
                
                cols = ["Trap", "Galgo", "Overall", "Categoria", "Fatores", "Perfil", 
                        "Histórico", "Posicao_Med", "Peso_Dif", "Dias", "Split", "Time", 
                        "Time_Ajustado", "Media_Split", "Media_Time", "Ritmo_Final", 
                        "Recup_Media", "Confianca"]
                        
                df_proj['Fatores'] = "Velocidade" # Placeholder para a coluna
                
                st.dataframe(df_proj[cols], use_container_width=True, hide_index=True)

                # Classificação Geral
                df_rank = df_proj.sort_values("Overall", ascending=False).head(3)
                podium = " > ".join([f"{med} {row['Trap']}" for med, (_, row) in zip(["🥇", "🥈", "🥉"], df_rank.iterrows())])
                st.markdown(f"### 🏆 Classificação Geral: {podium}")