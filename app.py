import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7 - Elite", layout="wide")
st.title("🐾 DIB 2.7 - Analisador de Elite")

# =========================================================
# EXTRAÇÃO DE DADOS
# =========================================================
def extrair_dados_racingpost(url):
    try:
        race_id_match = re.search(r"race_id=(\d+)", url)
        r_date_match = re.search(r"r_date=([\d-]+)", url)
        
        if not race_id_match or not r_date_match:
            return None, "Link inválido."
            
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
            return None, "O JSON não contém a chave 'dogs'."
            
        return {"dogs": dogs, "data_hoje": r_date_obj, "raw_json": data}, None
    except Exception as e:
        return None, f"Erro: {e}"

# =========================================================
# INTERFACE
# =========================================================
st.subheader("🔗 Link do Racing Post")
url_input = st.text_input("Cole o link da corrida:")

if st.button("Analisar", type="primary"):
    if url_input:
        with st.spinner("Buscando dados..."):
            resultado, erro = extrair_dados_racingpost(url_input)
            
            if erro:
                st.error(erro)
            else:
                dogs = resultado["dogs"]
                st.success(f"✅ Conectado! Encontrados {len(dogs)} galgos no card.")
                
                # --- MODO DIAGNÓSTICO ---
                st.warning("⚠️ Mostrando dados brutos para diagnóstico (apenas o 1º galgo):")
                
                # Pega o primeiro cão para ver a estrutura
                primeiro_cao = dogs[0]
                st.write("**Nome:**", primeiro_cao.get("dogName"))
                st.write("**Distância Hoje (Raiz):**", primeiro_cao.get("distance"))
                
                forms = primeiro_cao.get("forms", [])
                st.write(f"**Histórico:** {len(forms)} corridas encontradas")
                
                if forms:
                    st.write("**Estrutura da 1ª corrida do histórico:**")
                    st.json(forms[0])
                else:
                    st.error("O histórico deste galgo está vazio ([]) no JSON.")
                
                # Mostra o JSON inteiro caso ele queira copiar e enviar
                with st.expander("Ver JSON completo do 1º galgo"):
                    st.json(primeiro_cao)