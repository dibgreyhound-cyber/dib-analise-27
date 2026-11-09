import streamlit as st
import pandas as pd
import numpy as np
import re
import requests
from datetime import datetime

st.set_page_config(page_title="DIB 2.7", layout="wide")

# =========================================================
# FUNÇÕES AUXILIARES E REGEX
# =========================================================
def get_dist_val(val):
    if not val: return ""
    match = re.search(r'(\d+)', str(val))
    return match.group(1) if match else ""

def parse_going(g):
    if pd.isna(g) or not g: return 0.0
    g = str(g).strip().upper().replace(" ", "")
    m = re.match(r"([+-]?)(\d+)", g)
    if not m: return 0.0
    val = int(m.group(2)) / 100.0
    return -val if m.group(1) == "-" else val

def parse_traffic(r):
    if pd.isna(r): return 0.0
    r = str(r).upper()
    if "BAULKED" in r or "BLK" in r: return 0.20
    if "CRD" in r or "BMP" in r or "FCD" in r: return 0.10
    return 0.0

def is_traffic(r):
    if pd.isna(r): return False
    r = str(r).upper()
    forbidden = ["CRD", "BMP", "BLK", "BAULKED", "FCD-CK", "EVCH", "MVDOFF"]
    return any(x in r for x in forbidden)

def get_bends(b):
    if pd.isna(b): return 4, 4
    d = [int(c) for c in str(b) if c.isdigit()]
    return (d[0], d[-1]) if len(d) >= 4 else (4, 4)

def get_cat_base(g):
    m = {"A1": 15, "A2": 14, "A3": 13, "A4": 12, "A5": 11, "A6": 10, "A7": 9, "A8": 8, "A9": 7, "A10": 6, "A11": 5}
    match = re.search(r'A(\d+)', str(g).upper())
    return m.get(f"A{match.group(1)}", 10) if match else 10

def calc_prop(s, max_p, min_p):
    s = pd.to_numeric(s, errors="coerce").fillna(s.median())
    if s.max() == s.min(): return pd.Series([(max_p+min_p)/2] * len(s), index=s.index)
    return max_p - ((s - s.min()) / (s.max() - s.min()) * (max_p - min_p))

def get_emoji(t):
    return {1: "🟥 1", 2: "🟦 2", 3: "⬜ 3", 4: "⬛ 4", 5: "🟧 5", 6: "🔳 6"}.get(int(t), str(t))

# =========================================================
# EXTRAÇÃO DE DADOS (RACING POST API & PROXY)
# =========================================================
def extrair(url):
    try:
        rid = re.search(r"race_id=(\d+)", url).group(1)
        dt = re.search(r"r_date=([\d-]+)", url).group(1)
        d_obj = datetime.strptime(dt, "%Y-%m-%d")
        
        api_url = f"https://greyhoundbet.racingpost.com/card/blocks.sd?race_id={rid}&r_date={dt}&blocks=card,form"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36", "Accept": "application/json"}
        
        data = None
        try:
            res = requests.get(api_url, headers=headers, timeout=15)
            if res.status_code == 200: data = res.json()
        except: pass
        
        if data is None:
            proxy_url = f"https://api.allorigins.win/raw?url={requests.utils.quote(api_url)}"
            try:
                res = requests.get(proxy_url, timeout=20)
                if res.status_code == 200: data = res.json()
            except: pass
                
        if data is None: return None, None, "Racing Post bloqueou a conexão. Tente novamente."
            
        meta = {"pista": "Desconhecida", "hora": "00:00", "br": "00:00", "num": "X", "cat": "A5", "dist": "480"}
        race_info = {}
        try:
            for r in data.get('card', {}).get('races', []):
                if str(r.get('raceId')) == str(rid): race_info = r; break
        except: pass
            
        if race_info:
            meta["pista"] = str(race_info.get("course", meta["pista"])).upper()
            meta["num"] = str(race_info.get("raceNo", meta["num"]))
            tm = str(race_info.get("time", ""))
            if tm:
                match = re.search(r'(\d{2}:\d{2})', tm)
                if match:
                    meta["hora"] = match.group(1)
                    meta["br"] = f"{(int(meta['hora'][:2])-3)%24:02d}:{meta['hora'][3:]}"
            
            title = str(race_info.get("raceTitle", ""))
            m_dist = re.search(r'(\d{3,4})\s*m', title)
            if m_dist: meta["dist"] = m_dist.group(1)
            else:
                d_raw = race_info.get("distance") or race_info.get("dist") or ""
                if d_raw: meta["dist"] = get_dist_val(d_raw)
            
            
