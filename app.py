import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7", layout="wide")
st.title("🐾 Análise DIB 2.7")

# ... (funções parse_going, parse_traffic, is_traffic, get_bends, get_cat, calc_prop, get_emoji permanecem iguais) ...

def extrair(url):
    try:
        rid = re.search(r"race_id=(\d+)", url).group(1)
        dt = re.search(r"r_date=([\d-]+)", url).group(1)
        d_obj = datetime.strptime(dt, "%Y-%m-%d")
        
        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={rid}&r_date={dt}&blocks=card,form"
        
        # Lista de proxies para tentar em ordem
        proxies = [
            f"https://api.allorigins.win/raw?url={requests.utils.quote(api_url)}",
            f"https://corsproxy.io/?url={requests.utils.quote(api_url)}",
            f"https://api.cors.lol/?url={requests.utils.quote(api_url)}",
            f"https://api.codetabs.com/v1/proxy?quest={requests.utils.quote(api_url)}"
        ]
        
        data = None
        erro_final = "Todos os proxies falharam."
        
        for proxy_url in proxies:
            try:
                h = {"User-Agent": "Mozilla/5.0"}
                res = requests.get(proxy_url, headers=h, timeout=25)
                if res.status_code == 200:
                    data = res.json()
                    break
            except:
                continue
        
        if data is None:
            return None, None, erro_final
        
        # ... (restante da função extrair permanece igual: processamento do JSON, metadados, galgos) ...