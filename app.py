# -*- coding: utf-8 -*-
"""
DIB 2.7 - Analise de corridas de galgos (Streamlit)
- Extracao: mesmo fluxo do app anterior (link do Racing Post -> blocks.sd?blocks=form)
- Calculo: regras do DIB 2.7 (projecao + 3 planilhas de AVB)
- Exibicao: tabelas no estilo do artefato (emojis de posicao, stacked V/D, medalhas)
"""
import re
import html
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st

# =====================================================================
# CONFIGURACAO (ajuste aqui sem mexer no resto do codigo)
# =====================================================================
CFG = {
    "N_RUNS": 5,                       # ultimas corridas lidas por galgo
    "WEIGHTS": [5, 4, 3, 2, 1],        # Time Decay
    "POND_MODE": "validas",            # "validas": 5,4,3.. so entre corridas validas | "posicao": peso pela posicao entre as 5
    "CAT_BASE_MODE": "media",          # "media" das classes validas | "ultima" corrida valida
    "CAT_BONUS": 2.0,                  # desceu de classe +2 / subiu -2
    "N_CORREDORES": 6,                 # total de corredores para a % de Recup
    "TRAFFIC_ADJ": {"baulk": 0.20, "crd": 0.10, "bmp": 0.10, "fcd": 0.10},  # Blk nao esta no manual
    "VEL_PTS": {"adj": 40, "mtime": 30, "msplit": 15, "ritmo": 15},        # Base de Velocidade (100)
    "VEL_MIN": 0.0,                    # pontos do pior em cada item
    "PERFIL_PTS": {"Limpo": 10.0, "Irregular": 5.0, "Trombador": 2.5},
    "RECUP_PTS": lambda rec: float(np.clip(5 + (rec or 0) / 10.0, 0, 10)),  # 0 a 10 pts
    "REMARKS_PTS": {"early": 1.5, "clear": 5.0, "slowaway": -10.0, "firstbend": -7.0},
    "TRAP_VAZIA": 1.5, "ESMAGAMENTO": -1.5, "TRAFEGO_SEVERO": -2.0, "WIDE": -1.0,
    "H2H": 1.0, "H2H_MARGEM_GRANDE": 3.0, "H2H_GRANDE": 2.0,
    "MOMENTUM_VITORIA": 3.0, "MOMENTUM_DERROTA": -2.0, "DERROTA_POS_MIN": 5,
    "PESO_DIAS_NO_OVERALL": True,      # soma os pontos de Peso e Dias no Overall
    "FORCA_PRINCIPAL": 50.0, "FORCA_SECUNDARIO": 40.0,
    "CONF_MIN_VENCEDOR": 60.0,
}
