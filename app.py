import streamlit as st
import pandas as pd
import numpy as np
import re

st.set_page_config(page_title="DIB 2.7", layout="wide")
st.title("🐾 Análise DIB 2.7")

# =========================================================
# 🔧 AJUSTE AQUI — PESOS E TABELAS DO DIB 2.7
# =========================================================
PESO_AVB1 = 0.40   # velocidade (Split + CalTm)
PESO_AVB2 = 0.35   # posicionamento (Bends + Fin)
PESO_AVB3 = 0.25   # consistência (variação de tempos)

# Going: quanto a pista estava lenta (+10 = +0.10s no tempo)
GOING_TABLE = {
    "N": 0.0, "NORMAL": 0.0,
    "+05": 0.05, "-05": -0.05,
    "+10": 0.10, "-10": -0.10,
    "+20": 0.20, "-20": -0.20,
}

# Bônus/penalidade por Remark
REMARKS_TABLE = {
    "Q": 2.0, "QAW": 2.5, "AW": 1.0, "LD": 1.0, "CLR": 1.5, "FCD": 0.5,
    "BMP": -1.0, "CRD": -1.5, "ALD": -2.0, "STB": -0.5, "FCD2": 0.0,
}

# Bônus/penalidade por Trap (1 e 2 = raia interna, melhor)
TRAP_BONUS = {1: 2.0, 2: 1.0, 3: 0.0, 4: 0.0, 5: -1.0, 6: -2.0}

# Trava de peso: variação > ±0.5kg aplica ajuste
PESO_TRAVA_VALOR = 1.5

# =========================================================
# PARSERS
# =========================================================
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

def parse_fin(f):
    try: return int(float(f))
    except: return 6

def zscore_invert(s):
    """Menor é melhor → maior score. Retorna 0-100 aproximadamente."""
    s = pd.to_numeric(s, errors="coerce").fillna(s.mean())
    if s.std() == 0 or pd.isna(s.std()):
        return pd.Series([50.0] * len(s), index=s.index)
    z = (s - s.mean()) / s.std()
    return (-z) * 15 + 50

# =========================================================
# UPLOAD
# =========================================================
uploaded = st.file_uploader("Faça o upload do arquivo CSV", type="csv")

if uploaded is None:
    st.info("Aguardando o CSV. Use este modelo:")
    st.code(
        "Trap,Galgo,Distancia,Grade,Split,CalTm,Going,Bends,Fin,Remarks,Peso_Atual,Data_Corrida,Data_Hoje\n"
        "1,Galgo A,480,A4,4.5,29.1,N,1111,1,\"QAw,ALd\",32.1,2026-10-20,2026-11-07\n"
        "1,Galgo A,480,A5,4.6,29.5,+10,3322,3,Crd1,32.1,2026-10-10,2026-11-07"
    )
    st.stop()

df = pd.read_csv(uploaded)
st.success(f"✅ {len(df)} corridas • {df['Galgo'].nunique()} galgos")

# Sanitização
for c in ["Split", "CalTm", "Peso_Atual"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

df["Going_offset"] = df["Going"].apply(parse_going)
df["CalTm_adj"]    = df["CalTm"] - df["Going_offset"]
df["Remark_bonus"] = df["Remarks"].apply(parse_remarks)
df["Bends_list"]   = df["Bends"].apply(parse_bends)
df["Bends_avg"]    = df["Bends_list"].apply(np.mean)
df["Bends_early"]  = df["Bends_list"].apply(lambda x: x[0])
df["Fin"]          = df["Fin"].apply(parse_fin)

# =========================================================
# MÉDIAS POR GALGO
# =========================================================
agg = df.groupby("Galgo").agg(
    Corridas       = ("CalTm", "count"),
    Split_med      = ("Split", "mean"),
    CalTm_med      = ("CalTm_adj", "mean"),
    Bends_med      = ("Bends_avg", "mean"),
    Bends_early_med= ("Bends_early", "mean"),
    Fin_med        = ("Fin", "mean"),
    Remark_total   = ("Remark_bonus", "sum"),
    Peso_med       = ("Peso_Atual", "mean"),
    Peso_ult       = ("Peso_Atual", "last"),
    CalTm_std      = ("CalTm_adj", "std"),
).reset_index()

agg["CalTm_std"] = agg["CalTm_std"].fillna(0)
agg["Peso_var"]  = agg["Peso_ult"] - agg["Peso_med"]

# =========================================================
# 3 TABELAS AVB
# =========================================================
agg["AVB1"] = zscore_invert(agg["Split_med"]) * 0.4 + zscore_invert(agg["CalTm_med"]) * 0.6
agg["AVB2"] = (zscore_invert(agg["Bends_early_med"]) * 0.5
              + zscore_invert(agg["Bends_med"])       * 0.25
              + zscore_invert(agg["Fin_med"])         * 0.25)
agg["AVB3"] = zscore_invert(agg["CalTm_std"])

# =========================================================
# OVERALL
# =========================================================
agg["Overall_base"] = (agg["AVB1"] * PESO_AVB1
                      + agg["AVB2"] * PESO_AVB2
                      + agg["AVB3"] * PESO_AVB3)

# =========================================================
# TRAVAS
# =========================================================
# Trava 1: Split outlier na própria carreira (-2 por ocorrência)
df["Split_z"] = df.groupby("Galgo")["Split"].transform(
    lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0)
trava_split = (df.groupby("Galgo")["Split_z"]
                 .apply(lambda x: (x > 1.5).sum() * -2.0)
                 .reset_index())
trava_split.columns = ["Galgo", "Trava_Split"]

# Trava 2: Trap mais recente
trap_ult = (df.sort_values("Data_Corrida")
              .groupby("Galgo")["Trap"].last().reset_index())
trap_ult["Trava_Trap"] = trap_ult["Trap"].map(TRAP_BONUS).fillna(0)

# Trava 3: Variação de peso
agg["Trava_Peso"] = agg["Peso_var"].apply(
    lambda v: -PESO_TRAVA_VALOR if v < -0.5
    else (PESO_TRAVA_VALOR if v > 0.5 else 0.0))

agg = agg.merge(trava_split, on="Galgo", how="left") \
         .merge(trap_ult[["Galgo", "Trava_Trap"]], on="Galgo", how="left")

# =========================================================
# FORÇA FINAL (0-100)
# =========================================================
agg["Bonus_Remarks"] = agg["Remark_total"].clip(-5, 5)
agg["Forca_bruta"] = (agg["Overall_base"]
                     + agg["Trava_Split"].fillna(0)
                     + agg["Trava_Trap"].fillna(0)
                     + agg["Trava_Peso"].fillna(0)
                     + agg["Bonus_Remarks"])

fmin, fmax = agg["Forca_bruta"].min(), agg["Forca_bruta"].max()
agg["Forca"] = ((agg["Forca_bruta"] - fmin) / (fmax - fmin) * 100
                if fmax > fmin else 50.0)

agg = agg.sort_values("Forca", ascending=False).reset_index(drop=True)
agg["Ranking"] = agg.index + 1

# =========================================================
# EXIBIÇÃO
# =========================================================
t1, t2, t3, t4 = st.tabs(["🏆 Ranking / Força", "📊 AVB (3 tabelas)",
                          "⚔️ Matchmaking", "📄 Dados processados"])

with t1:
    st.subheader("Ranking por Força")
    st.dataframe(
        agg[["Ranking","Galgo","Forca","Overall_base","Corridas",
             "Split_med","CalTm_med","Fin_med"]].round(2),
        use_container_width=True)

with t2:
    st.subheader("AVB 1 — Velocidade")
    st.dataframe(agg[["Galgo","AVB1","Split_med","CalTm_med"]].round(2),
                 use_container_width=True)
    st.subheader("AVB 2 — Posicionamento")
    st.dataframe(agg[["Galgo","AVB2","Bends_early_med","Bends_med","Fin_med"]].round(2),
                 use_container_width=True)
    st.subheader("AVB 3 — Consistência")
    st.dataframe(agg[["Galgo","AVB3","CalTm_std"]].round(2),
                 use_container_width=True)

with t3:
    st.subheader("Confrontos sugeridos (1º vs 2º, 3º vs 4º, ...)")
    pares = []
    for i in range(0, len(agg) - 1, 2):
        a, b = agg.iloc[i], agg.iloc[i + 1]
        dif = a["Forca"] - b["Forca"]
        pares.append({
            "Confronto": f"{a['Galgo']} vs {b['Galgo']}",
            "Força A": round(a["Forca"], 1),
            "Força B": round(b["Forca"], 1),
            "Favorito": a["Galgo"] if dif >= 0 else b["Galgo"],
            "Margem": round(abs(dif), 1),
        })
    st.dataframe(pd.DataFrame(pares), use_container_width=True)

with t4:
    st.dataframe(df.drop(columns=["Bends_list"]), use_container_width=True)

st.download_button(
    "⬇️ Baixar resultados (CSV)",
    agg.to_csv(index=False).encode("utf-8"),
    file_name="dib27_resultado.csv",
    mime="text/csv",
)