import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime

st.set_page_config(page_title="DIB 2.7 - Analisador", layout="wide")
st.title("🐾 DIB 2.7 - Analisador de Elite")

# =========================================================
# CONSTANTES E TRADUÇÕES
# =========================================================
TRAP_EMOJIS = {1: "🟥 1", 2: "🟦 2", 3: "⬜ 3", 4: "⬛ 4", 5: "🟧 5", 6: "🔳 6"}
CAT_BASE = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}

def parse_trap(trap_num):
    return TRAP_EMOJIS.get(int(trap_num), "vacant")

# =========================================================
# FUNÇÕES DE CÁLCULO DIB 2.7
# =========================================================
def calcular_engine_dib(df):
    # 1. Filtros Iniciais
    df['Trap'] = df['Trap_Num'].apply(parse_trap)
    df['Categoria_Base'] = df['Grade'].str.extract(r'([A-Z]\d+)')[0].map(CAT_BASE).fillna(5)
    
    # 2. Categoria (Modificador) e Peso
    # (Simulação simplificada para o código base, requerendo dados de classe anterior)
    df['Categoria'] = df['Categoria_Base'] # + modificadores se houver
    
    # 3. Dias sem correr (simulado com base na data de hoje)
    # df['Dias'] = (hoje - df['Data_Ultima']).days
    
    # 4. Médias Ponderadas (Time Decay 5,4,3,2,1)
    def calcular_media_ponderada(tempos):
        pesos = [5, 4, 3, 2, 1][:len(tempos)]
        return np.average(tempos, weights=pesos) if tempos else 0
    
    # 5. Time Ajustado
    def calc_time_ajustado(row):
        t = row['CalTm']
        going = row['Going']
        remarks = str(row['Remarks']).lower()
        
        ajuste = 0
        if going in ['+10', '+20']: ajuste -= float(going.replace('+', ''))/100
        if going in ['-10', '-20']: ajuste += float(going.replace('-', ''))/100
        if 'baulked' in remarks: ajuste -= 0.20
        if any(x in remarks for x in ['crd', 'bmp', 'fcd']): ajuste -= 0.10
        
        return t + ajuste

    df['Time_Ajustado'] = df.apply(calc_time_ajustado, axis=1)

    # 6. Recuperação Blindada
    def calc_recuperacao(row):
        remarks = str(row['Remarks']).lower()
        if any(x in remarks for x in ['crd', 'bmp', 'blk', 'baulked', 'fcd-ck', 'evch', 'mvdoff']):
            return None # Corrida excluída
        # Lógica de posições (ex: começou em 4, terminou em 2 = +2 posições ganhas)
        return 0 # Placeholder para lógica exata de posição

    # 7. Confiança
    # df['Confianca'] = (count_validas / 5) * 20

    # 8. Cálculo do Overall
    def normalize(series, is_inverse=False):
        if series.max() == series.min(): return 50
        if is_inverse:
            return ((series.max() - series) / (series.max() - series.min())) * 100
        return ((series - series.min()) / (series.max() - series.min())) * 100

    # Base Velocidade (100 pontos normalizados)
    # df['Base_Vel'] = (normalize(df['Time_Ajustado'], True) * 0.40) + ...
    
    return df

# =========================================================
# INTERFACE (Simulação de entrada de dados via CSV)
# =========================================================
st.info("Para testar a matemática, insira as colunas necessárias no CSV (Trap, Galgo, Overall, Categoria, etc).")

uploaded_file = st.file_uploader("Upload do CSV base", type="csv")

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    
    if st.button("Processar DIB 2.7", type="primary"):
        with st.spinner("Aplicando as travas e calculando o Overall..."):
            try:
                # Processa a engine
                df_result = calcular_engine_dib(df.copy())
                
                # ---------------------------------------------------------
                # EXIBIÇÃO: PROJEÇÃO
                # ---------------------------------------------------------
                st.subheader("📋 Planilha de Projeção")
                
                # Colunas solicitadas na Projeção
                cols_proj = [
                    "Trap", "Galgo", "Overall", "Categoria", "Fatores", "Perfil", 
                    "Histórico", "Posição Med.", "Peso", "Dias", "Split", "Time", 
                    "Time Ajustado", "Média Split", "Média Time", "Ritmo final", 
                    "Recup. Média", "Confiança"
                ]
                
                # Garantindo que as colunas existam para não dar erro
                for c in cols_proj:
                    if c not in df_result.columns: df_result[c] = "-"
                    
                st.dataframe(df_result[cols_proj], use_container_width=True, hide_index=True)
                
                # Classificação Geral (Medalhas)
                df_sorted = df_result.sort_values("Overall", ascending=False)
                top3 = df_sorted.head(3)
                podium = " > ".join([f"{medal} {trap}" for medal, trap in zip(["🥇", "🥈", "🥉"], top3["Trap"])])
                st.markdown(f"**Classificação Geral:** {podium}")

                # ---------------------------------------------------------
                # EXIBIÇÃO: AVB (Simulação de Matchmaking)
                # ---------------------------------------------------------
                st.subheader("⚔️ Tabelas de AVB e Matchmaking")
                
                st.markdown("### 1ª Planilha: AVB do Alvo (🎯)")
                st.info("Confrontos gerados contra os galgos marcados com 🎯 (Alvos).")
                # Aqui entraria a lógica de renderização lado a lado Vencedor vs Desafiante

                st.markdown("### 2ª Planilha: AVB Principal (Elite)")
                st.info("Confrontos de Elite (Força ≥ 50.0).")
                # Aqui entraria a renderização

                st.markdown("### 3ª Planilha: AVB Secundário")
                st.info("Confrontos de Elite com Força entre 40.0 e 49.9.")

                # ---------------------------------------------------------
                # OBSERVAÇÕES
                # ---------------------------------------------------------
                st.subheader("📝 Observações Táticas")
                for index, row in df_sorted.iterrows():
                    st.markdown(f"**{row['Trap']} {row['Galgo']}:** Overall {row['Overall']}. Perfil {row['Perfil']}.")
                    
            except Exception as e:
                st.error(f"Erro ao processar: {e}")