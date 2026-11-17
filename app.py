# -*- coding: utf-8 -*-
"""
app.py - Lista de corridas / Resultados na barra lateral + analise e Form na pagina principal.
Usa o seu dib_core.py (calculo e tabelas) sem mudancas.
Novidades: replay da corrida e painel "Descobrir" para achar o endereco do resultado.
"""
import re
import time
import json
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="DIB GREYHOUND", layout="wide", initial_sidebar_state="auto")

# --- BLOCO PARA O GALGO CORRENDO NO STATUS DO STREAMLIT ---
st.markdown(
    """
    <style>
    /* 1. Força a esconder qualquer ícone de esporte original */
    [data-testid="stStatusWidget"] svg {
        display: none !important;
    }

    /* 2. Adiciona o Galgo no lugar */
    [data-testid="stStatusWidget"] > div::before {
        content: "";
        display: inline-block;
        width: 32px;
        height: 32px;
        /* Silhueta de Galgo em SVG na cor cinza escuro (#31333F) */
        background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 104 42"><g fill="%2331333F" stroke="%2331333F" stroke-linecap="round" stroke-linejoin="round"><path stroke-width="0.4" d="M24 13 C32 9.6 44 8.8 54 8.6 C62 8.4 68 7.2 74 6 C78 5 81 4.2 84 3.8 C87 3.4 89 4 91 5 L99 9 C100.4 9.8 100.4 11 99 11.6 L94 12.4 C91 12.6 89.4 11.4 87 11.2 C83 11.6 80 13 78.4 15.6 C77.4 19.2 75 22.6 70 22.6 C65 22.6 60 20 55 18.4 C50 16.8 44 15.8 38 16 C32 16 27 16.6 24 14.8 Z"/><path stroke-width="0.3" d="M85.4 3.8 L86.4 0.6 L88.8 3.4 Z"/><path fill="none" stroke-width="2.6" d="M77 15.4 L88 18"/><path fill="none" stroke-width="1.6" d="M88 18 L98 18.6"/><path fill="none" stroke-width="2.4" d="M76 17 L85 21.6"/><path fill="none" stroke-width="1.6" d="M85 21.6 L94 22.4"/><path fill="none" stroke-width="5" d="M29 13.6 L19 19.4"/><path fill="none" stroke-width="2.4" d="M19 19.4 L10 24.6"/><path fill="none" stroke-width="1.7" d="M10 24.6 L4 26.4"/><path fill="none" stroke-width="3.8" d="M30 15.6 L23 24"/><path fill="none" stroke-width="2.2" d="M23 24 L15 30.4"/><path fill="none" stroke-width="1.7" d="M15 30.4 L8.4 32.6"/><path fill="none" stroke-width="1.2" d="M24 12.6 C18 14.2 12 15 5 13.4"/></g></svg>');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        margin-right: 8px;
        vertical-align: middle;
        
        /* Animação do galgo correndo */
        animation: runDog 0.4s infinite alternate;
    }

    @keyframes runDog {
        from { transform: translateX(-3px); }
        to { transform: translateX(3px); }
    }
    </style>
    """,
    unsafe_allow_html=True
)
# --- FIM DO BLOCO DO GALGO ---

import dib_core as dib

BASE = "https://greyhoundbet.racingpost.com"
LISTA_CANDIDATOS = [
    BASE + "/meeting/blocks.sd?r_date={d}&blocks=header%2Clist",
    BASE + "/meeting/blocks.sd?r_date={d}&blocks=list",
    BASE + "/meeting-list/blocks.sd?r_date={d}&blocks=list",
    BASE + "/meeting/list.sd?r_date={d}",
]
RESULTADO_CANDIDATOS = (
    [BASE + "/results/blocks.sd?race_id={rid}&r_date={d}&blocks=" + b for b in ("result", "results", "header%2Cresult")]
    + [BASE + "/result/blocks.sd?race_id={rid}&r_date={d}&blocks=" + b for b in ("result", "results")]
    + [BASE + "/card/blocks.sd?race_id={rid}&r_date={d}&blocks=" + b for b in ("result", "results")]
    + [BASE + "/results/race.sd?race_id={rid}&r_date={d}"]
)
KEYS = {
    "id": ["raceId", "race_id", "rid"],
    "hora": ["raceDate", "offTime", "scheduledTime", "displayTime", "raceTime", "time", "startTime"],
    "pista": ["trackName", "track", "meetingName", "courseName", "venue"],
    "num": ["raceTitle", "raceNum", "raceNumber", "rNum", "number", "raceNo"],
    "grade": ["raceClass", "raceGrade", "grade", "class", "raceClassDesc"],
    "dist": ["distMetres", "distMeters", "distance", "dist", "raceDistance"],
    "clip": ["clipId", "clip_id", "videoId", "replayId"],
}
RES = {
    "nome": ["dogName", "dog_name", "name"],
    "pos": ["finishPos", "finPos", "outcomeDesc", "position", "pos", "fin", "outcome", "result"],
    "trap": ["trapNum", "trap", "dogTrap"],
    "sp": ["SP", "sp", "startingPrice", "price", "odds"],
    "tempo": ["calcRTimes", "calTm", "finishTime", "winTime", "time"],
    "margem": ["distBtn", "by", "beatenDistance"],
    "coment": ["closeUpCmnt", "comment", "cmnt", "commentary", "description"],
}
EXTRA = {"winsec": ["winnerOrSecond", "winSec", "wnSec", "winnerName", "secondName"],
         "sp": ["SP", "sp", "startingPrice", "price"],
         "trainer": ["trainerName", "trainer", "trainer_name"]}


# ---------------------------------------------------------------- conexao com o site
class _Http:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": dib.HEADERS.get("User-Agent", "Mozilla/5.0"),
            "Accept": "application/json, text/plain, */*", "Accept-Language": "en-GB,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest", "Referer": BASE + "/", "Origin": BASE})
        self.pronto = False

    def get(self, url, headers=None, timeout=15):
        if not self.pronto:
            try: self.s.get(BASE + "/", timeout=8)
            except Exception: pass
            self.pronto = True
        r = self.s.get(url, timeout=timeout)
        if r.status_code in (403, 429):
            time.sleep(1.5)
            r = self.s.get(url, timeout=timeout)
        return r


@st.cache_resource
def http():
    return _Http()


dib.requests = http()


# ---------------------------------------------------------------- numeros dos galgos
BADGE_STYLE = {
    1: "background:#d62828;color:#fff;",
    2: "background:#1d4ed8;color:#fff;",
    3: "background:#fff;color:#000;border:1px solid #000;",
    4: "background:#111;color:#fff;border:1px solid #444;",
    5: "background:#f97316;color:#fff;",
    6: "background:repeating-linear-gradient(90deg,#111 0 4px,#fff 4px 8px);color:#e11;"
       "text-shadow:0 0 2px #fff,0 0 2px #fff,0 0 2px #fff;",
}


def badge(t):
    try: t = int(t)
    except Exception: return ""
    return (f"<span style='display:inline-block;min-width:24px;height:24px;line-height:24px;text-align:center;"
            f"border-radius:4px;font-weight:700;font-size:14px;vertical-align:middle;{BADGE_STYLE.get(t, '')}'>{t}</span>")


class _St:
    def __getattr__(self, n): return getattr(st, n)
    def markdown(self, body, *a, **k):
        k.setdefault("unsafe_allow_html", True)
        return st.markdown(body, *a, **k)


dib.st = _St()
dib.TRAP_EMOJI = {t: badge(t) for t in range(1, 7)}
dib.trap_label = lambda d: badge(d["trap"])


# ---------------------------------------------------------------- botao copiar (JavaScript)
def botao_copiar(texto):
    """Cria um botão HTML nativo que copia o texto usando JavaScript."""
    texto_js = json.dumps(texto)

    html = f"""
    <html>
    <head>
    <style>
    .copy-btn {{
        background-color: #ff4b4b;
        color: white;
        border: none;
        padding: 12px 20px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 16px;
        font-weight: bold;
        width: 100%;
        transition: 0.2s;
    }}
    .copy-btn:active {{ background-color: #cc0000; }}
    </style>
    </head>
    <body>
    <button class="copy-btn" id="copyBtn">📋 Copiar Análise para o Chat</button>
    <script>
    const textToCopy = {texto_js};
    document.getElementById("copyBtn").addEventListener("click", async () => {{
        try {{
            await navigator.clipboard.writeText(textToCopy);
            document.getElementById("copyBtn").innerText = "✅ Texto Copiado! Cole no Chat.";
            document.getElementById("copyBtn").style.backgroundColor = "#28a745";
            setTimeout(() => {{
                document.getElementById("copyBtn").innerText = "📋 Copiar Análise para o Chat";
                document.getElementById("copyBtn").style.backgroundColor = "#ff4b4b";
            }}, 4000);
        }} catch (err) {{
            document.getElementById("copyBtn").innerText = "❌ Erro (Copie manualmente abaixo)";
            document.getElementById("copyBtn").style.backgroundColor = "#ff9800";
        }}
    }});
    </script>
    </body>
    </html>
    """
    components.html(html, height=65)


# ---------------------------------------------------------------- leitura de JSON
def _get(d, k, tabela=KEYS):
    for key in tabela[k]:
        if key in d and d[key] not in (None, "", {}, []):
            return d[key]
    return None


def _hhmm(v):
    m = re.search(r"(\d{1,2}):(\d{2})", str(v or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def achar_corridas(obj):
    achados = {}

    def walk(o, pista_ctx):
        if isinstance(o, dict):
            p = _get(o, "pista")
            if isinstance(p, str): pista_ctx = p
            rid = _get(o, "id")
            hora = _hhmm(_get(o, "hora"))
            if rid is not None and re.fullmatch(r"\d{5,9}", str(rid)) and hora:
                g, d = _get(o, "grade"), _get(o, "dist")
                achados[str(rid)] = {
                    "id": str(rid), "hora": hora, "pista": (pista_ctx or "?").title(),
                    "num": str(_get(o, "num") or "").replace("Race", "").strip(),
                    "grade": re.sub(r"[()\s]", "", str(g or "")).upper(),
                    "dist": int(re.sub(r"\D", "", str(d))) if d and re.search(r"\d", str(d)) else 0,
                    "clip": str(_get(o, "clip") or ""),
                }
            for v in o.values(): walk(v, pista_ctx)
        elif isinstance(o, list):
            for v in o: walk(v, pista_ctx)

    walk(obj, "")
    return sorted(achados.values(), key=lambda c: (c["hora"], c["pista"]))


def achar_resultados(obj):
    achados = {}

    def walk(o):
        if isinstance(o, dict):
            nome = _get(o, "nome", RES)
            m = re.search(r"\d+", str(_get(o, "pos", RES) or ""))
            if isinstance(nome, str) and m and 1 <= int(m.group()) <= 8:
                t = re.search(r"\d+", str(_get(o, "trap", RES) or ""))
                achados[nome] = {
                    "pos": int(m.group()), "trap": int(t.group()) if t else None, "nome": nome,
                    "sp": str(_get(o, "sp", RES) or ""), "tempo": str(_get(o, "tempo", RES) or ""),
                    "margem": str(_get(o, "margem", RES) or ""), "coment": str(_get(o, "coment", RES) or ""),
                }
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)

    walk(obj)
    return sorted(achados.values(), key=lambda x: x["pos"])


def _chaves(js):
    if not isinstance(js, dict): return f"({type(js).__name__} com {len(js) if hasattr(js, '__len__') else '?'} itens)"
    return ", ".join(f"{k}{'(erro)' if isinstance(v, dict) and 'errorCode' in v else ''}" for k, v in js.items())[:90]


def tentar(urls, parser):
    tentativas, achado, primeira = [], [], None
    for u in urls:
        curto = u.replace(BASE, "")
        time.sleep(0.3)
        try:
            r = http().get(u, timeout=8)
        except Exception as e:
            tentativas.append({"Status": f"erro: {str(e)[:40]}", "Achados": 0, "Chaves": "", "Resposta": "",
                               "Endereço": curto})
            continue
        js, resposta = None, ""
        if r.status_code == 200:
            try:
                js = r.json()
            except Exception:   # resposta que nao e JSON: mostra o comeco para entender
                resposta = r.text[:90].replace("\n", " ")
        res = parser(js) if js is not None else []
        tentativas.append({"Status": r.status_code, "Achados": len(res),
                           "Chaves": _chaves(js) if js is not None else "", "Resposta": resposta,
                           "Endereço": curto})
        if primeira is None and js is not None and not res: primeira = js
        if res:
            achado = res
            break
    return achado, tentativas, primeira


@st.cache_data(ttl=120, show_spinner=False)
def buscar_lista(data_str, url_custom):
    urls = ([url_custom.replace("{data}", data_str)] if url_custom.strip() else []) \
        + [u.format(d=data_str) for u in LISTA_CANDIDATOS]
    return tentar(urls, achar_corridas)


@st.cache_data(ttl=60, show_spinner=False)
def buscar_resultado(race_id, data_str):
    return tentar([u.format(rid=race_id, d=data_str) for u in RESULTADO_CANDIDATOS], achar_resultados)


@st.cache_data(ttl=300, show_spinner=False)
def buscar_form_raw(race_id, data_str):
    try:
        r = http().get(f"{BASE}/card/blocks.sd?race_id={race_id}&r_date={data_str}&blocks=form", timeout=15)
        r.raise_for_status()
        return r.json().get("form", {}).get("dogs", [])
    except Exception:
        return []


# ---------------------------------------------------------------- utilidades
def hora_br(hhmm, h24=False):
    h, m = [int(x) for x in hhmm.split(":")]
    t = datetime(2000, 1, 1, h, m) - timedelta(hours=3)
    if h24:
        return f"{t.hour:02d}:{t.minute:02d}"
    return f"{t.hour % 12 or 12}:{t.minute:02d}"


def agora_uk():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/London"))
    except Exception:
        return datetime.utcnow()


def escolher(c, data_str, modo):
    st.session_state["sel"] = dict(c, data=data_str, modo=modo)
    st.session_state["fechar"] = True


def fechar_sidebar():
    components.html(
        """<script>
        try {
          const d = window.parent.document;
          if (window.parent.innerWidth < 900) {
            const b = d.querySelector('[data-testid="stSidebarCollapseButton"] button')
                   || d.querySelector('[data-testid="stSidebarCollapseButton"]')
                   || d.querySelector('button[kind="header"]');
            if (b) b.click();
          }
        } catch (e) {}
        </script>""", height=0)


def tabela_html(headers, rows):
    st.markdown(dib.tbl(headers, rows), unsafe_allow_html=True)


def _link(url, rotulo):
    try:
        st.link_button(rotulo, url)
    except Exception:
        st.markdown(f"[{rotulo}]({url})")


# ---------------------------------------------------------------- replay
def mostrar_replay(c):
    clip = str(c.get("clip") or "").strip()
    if clip:
        url = f"https://www.youtube.com/watch?v={clip}"
        with st.expander("▶ Replay da corrida (tentativa)", expanded=False):
            try:
                st.video(url)
            except Exception:
                st.write("Não consegui incorporar o vídeo aqui.")
            _link(url, "Abrir o vídeo em outra aba")
            st.caption(f"Código do replay recebido da lista: {clip}")
    else:
        st.caption("▶ Replay: esta corrida ainda não trouxe o código do vídeo (clipId vazio na lista). "
                   "Ele costuma aparecer depois que a corrida termina; toque em 🔄 para recarregar a lista.")
    _link(f"{BASE}/#card/race_id={c['id']}&r_date={c['data']}", "Abrir esta corrida no site")


# ---------------------------------------------------------------- descobrir enderecos (lendo o JavaScript do site)
_RE_SD = re.compile(r"""["']((?:/?[\w\-]+/)*[\w\-]*\.sd)(?:\?[^"']*)?["']""")
_RE_BLOCKS = re.compile(r"""blocks\s*[:=]\s*["']([\w,%\-]+)["']""")


def _baixar(url, tam=3_000_000):
    try:
        r = http().get(url, timeout=15)
        if r.status_code == 200:
            return r.text[:tam]
    except Exception:
        pass
    return ""


def _contextos(texto, padrao, n=70, limite=20):
    vistos, res = set(), []
    for m in re.finditer(padrao, texto, flags=re.I):
        ini, fim = max(0, m.start() - n), min(len(texto), m.end() + n)
        trecho = texto[ini:fim].replace("\n", " ")
        chave = trecho[n - 10:n + 20]
        if chave not in vistos:
            vistos.add(chave)
            res.append(trecho)
        if len(res) >= limite:
            break
    return res


def _galgos_com_posicao(js):
    n = 0

    def walk(o):
        nonlocal n
        if isinstance(o, dict):
            nome = o.get("dogName")
            pos = re.search(r"\d+", str(o.get("outcomeDesc") or o.get("finishPos") or o.get("position") or ""))
            if isinstance(nome, str) and pos:
                n += 1
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)

    walk(js)
    return n


@st.cache_data(ttl=3600, show_spinner=False)
def varrer_site():
    """Le a pagina inicial e os arquivos JavaScript do site (so na primeira vez)."""
    html = _baixar(BASE + "/")
    scripts = []
    for u in re.findall(r"""<script[^>]+src=["']([^"']+)["']""", html):
        u = "https:" + u if u.startswith("//") else (BASE + u if u.startswith("/") else
                                                      (u if u.startswith("http") else BASE + "/" + u))
        if "racingpost" in u and u not in scripts:
            scripts.append(u)
    scripts = scripts[:8]
    tudo = "\n".join(_baixar(u) for u in scripts)
    return {
        "html": len(html), "scripts": [u.replace(BASE, "") for u in scripts], "chars": len(tudo),
        "caminhos": sorted({m.group(1) for m in _RE_SD.finditer(tudo)})[:120],
        "blocos": sorted({m.group(1) for m in _RE_BLOCKS.finditer(tudo)})[:120],
        "rotas": _contextos(tudo, r"(results?|meeting|card)[-_](list|details?|meeting)|#result", 80, 25),
        "result": _contextos(tudo, r"result", 70, 25),
        "replay": _contextos(tudo, r"replay|clipId|youtube|\.mp4|m3u8|video", 80, 25),
    }


@st.cache_data(ttl=600, show_spinner=False)
def testar_enderecos(race_id, data_str, bases, nomes):
    testes, achado = [], None
    for p in bases:
        for b in nomes:
            u = f"{BASE}{p}?race_id={race_id}&r_date={data_str}&blocks={b}"
            time.sleep(0.25)
            try:
                r = http().get(u, timeout=8)
                js = r.json() if r.status_code == 200 else None
            except Exception:
                testes.append({"Status": "não é JSON", "Galgos": 0, "Chaves": "", "Endereço": u.replace(BASE, "")})
                continue
            n = _galgos_com_posicao(js) if js is not None else 0
            testes.append({"Status": r.status_code, "Galgos": n, "Chaves": _chaves(js) if js is not None else "",
                           "Endereço": u.replace(BASE, "")})
            if n >= 2 and not achado:
                achado = u
    return testes, achado


def painel_descobrir(race_id, data_str):
    st.markdown("---")
    st.markdown("#### 🧪 Procurando o endereço do resultado e do replay")
    with st.spinner("Lendo o código do site (só na primeira vez, leva alguns segundos)..."):
        v = varrer_site()
    caminhos_res = [p for p in v["caminhos"] if "result" in p.lower()]
    bases = tuple(dict.fromkeys([(p if p.startswith("/") else "/" + p) for p in caminhos_res[:5]]
                                + ["/results/blocks.sd", "/card/blocks.sd"]))
    nomes = tuple(dict.fromkeys([b for b in v["blocos"] if "result" in b.lower()][:6]
                                + ["result", "results", "resultDetails", "card%2Cresult"]))[:8]
    with st.spinner("Testando endereços..."):
        testes, achado = testar_enderecos(race_id, data_str, bases, nomes)
    if achado:
        st.success("Achei um endereço com resultado! Copie o relatório abaixo e cole no chat.")
        st.code(achado)
    else:
        st.warning("Ainda não achei o endereço. Toque em copiar e cole o relatório no chat que eu ajusto.")
    linhas = [f"Pagina inicial: {v['html']} caracteres | JavaScript: {len(v['scripts'])} arquivos, {v['chars']} caracteres",
              "ARQUIVOS: " + ", ".join(v["scripts"]),
              "ENDERECOS .sd: " + ", ".join(v["caminhos"]),
              "BLOCKS: " + ", ".join(v["blocos"]),
              "ROTAS:", *v["rotas"], "RESULT:", *v["result"], "REPLAY/VIDEO:", *v["replay"],
              "TESTES:", *[f"{t['Status']} | galgos={t['Galgos']} | {t['Chaves']} | {t['Endereço']}" for t in testes]]
    relatorio = "\n".join(linhas)
    botao_copiar(relatorio)
    st.text_area("Relatório (se o botão não copiar, selecione e copie daqui):", relatorio, height=220)
    st.dataframe(pd.DataFrame(testes), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------- grafico estilo "Predictor" (barras pelo Overall)
BAR_STYLE = {
    1: ("background:#c62828;", "invert"),
    2: ("background:#1d4ed8;", "invert"),
    3: ("background:#eeeeee;", "dark"),
    4: ("background:#151515;", "invert"),
    5: ("background:#f26b21;", "invert"),
    6: ("background:repeating-linear-gradient(180deg,#111 0 3px,#fff 3px 6px);", "stripe"),
}


def greyhound_svg(trap):
    """Silhueta de greyhound em galope estendido (de lado, olhando p/ a direita).
    Branca; preta na barra 3 (fundo claro); com contorno escuro na barra 6 (listrada)."""
    cor = "#111" if trap == 3 else "#fff"
    if trap == 6:
        sh = "filter:drop-shadow(0 0 .6px #000) drop-shadow(0 0 .6px #000) drop-shadow(0 0 .6px #000);"
    elif trap == 3:
        sh = ""
    else:
        sh = "filter:drop-shadow(0 0 .7px rgba(0,0,0,.8));"
    return (
        f"<svg viewBox='0 0 104 42' width='28' height='11' xmlns='http://www.w3.org/2000/svg' "
        f"style='display:block;{sh}'>"
        f"<g fill='{cor}' stroke='{cor}' stroke-linecap='round' stroke-linejoin='round'>"
        # tronco, pescoço fino e cabeça comprida
        "<path stroke-width='0.4' d='M24 13 C32 9.6 44 8.8 54 8.6 C62 8.4 68 7.2 74 6 C78 5 81 4.2 84 3.8 "
        "C87 3.4 89 4 91 5 L99 9 C100.4 9.8 100.4 11 99 11.6 L94 12.4 C91 12.6 89.4 11.4 87 11.2 "
        "C83 11.6 80 13 78.4 15.6 C77.4 19.2 75 22.6 70 22.6 C65 22.6 60 20 55 18.4 C50 16.8 44 15.8 38 16 "
        "C32 16 27 16.6 24 14.8 Z'/>"
        # orelha
        "<path stroke-width='0.3' d='M85.4 3.8 L86.4 0.6 L88.8 3.4 Z'/>"
        # patas dianteiras esticadas para a frente
        "<path fill='none' stroke-width='2.6' d='M77 15.4 L88 18'/>"
        "<path fill='none' stroke-width='1.6' d='M88 18 L98 18.6'/>"
        "<path fill='none' stroke-width='2.4' d='M76 17 L85 21.6'/>"
        "<path fill='none' stroke-width='1.6' d='M85 21.6 L94 22.4'/>"
        # patas traseiras esticadas para trás
        "<path fill='none' stroke-width='5' d='M29 13.6 L19 19.4'/>"
        "<path fill='none' stroke-width='2.4' d='M19 19.4 L10 24.6'/>"
        "<path fill='none' stroke-width='1.7' d='M10 24.6 L4 26.4'/>"
        "<path fill='none' stroke-width='3.8' d='M30 15.6 L23 24'/>"
        "<path fill='none' stroke-width='2.2' d='M23 24 L15 30.4'/>"
        "<path fill='none' stroke-width='1.7' d='M15 30.4 L8.4 32.6'/>"
        # rabo fino
        "<path fill='none' stroke-width='1.2' d='M24 12.6 C18 14.2 12 15 5 13.4'/>"
        "</g></svg>"
    )


def badge_p(t):
    """Número da trap em tamanho reduzido (só para o gráfico)."""
    return (badge(t).replace("min-width:24px;height:24px;line-height:24px", "min-width:16px;height:16px;line-height:16px")
            .replace("font-size:14px", "font-size:11px"))


def grafico_predictor(ds):
    """Uma barra por galgo (na ordem das traps). Tamanho = Overall / maior Overall; o maior Overall enche a barra.
    No fim de cada barra vai o galgo correndo, com a casaca da respectiva trap."""
    com = [d for d in ds if not d.get("nd") and d.get("overall") is not None]
    if not com:
        return ""
    mx = max(d["overall"] for d in com)
    linhas = []
    for d in sorted(ds, key=lambda x: x["trap"]):
        t = d["trap"]
        estilo, _ = BAR_STYLE.get(t, ("background:#888;", "invert"))
        if d.get("nd") or d.get("overall") is None:
            fill = ""
        else:
            w = 100.0 if mx <= 0 else max(11.0, min(100.0, d["overall"] / mx * 100.0))
            tip = f"{d['name']} · Overall {d['overall']:.1f}"
            fill = (f"<div title=\"{tip}\" style='position:relative;width:{w:.1f}%;height:100%;"
                    f"border-radius:8px;{estilo}'>"
                    f"<span style='position:absolute;right:4px;top:50%;transform:translateY(-50%);"
                    f"line-height:0;'>{greyhound_svg(t)}</span></div>")
        linhas.append(f"<div style='display:flex;align-items:center;gap:6px;margin:4px 0'>{badge_p(t)}"
                      f"<div style='flex:1;height:15px;background:#0a2a52;border-radius:8px;overflow:hidden'>"
                      f"{fill}</div></div>")
    return ("<div style='background:#143f6f;border-radius:16px;padding:12px 10px 5px;max-width:640px;margin:6px 0;"
            "position:relative'>"
            "<div style='position:absolute;top:-1px;left:10px;background:#d32f2f;color:#fff;font-weight:700;"
            "font-size:11px;padding:2px 12px;border-radius:0 0 10px 10px'>Predictor</div>"
            "<div style='height:6px'></div>" + "".join(linhas) + "</div>")


# ---------------------------------------------------------------- post pick (galgos indicados pelo Racing Post)
_RE_PP_TXT = re.compile(r"post\s*pick\s*[:\-]?\s*((?:[1-6]\s*[-,/]\s*)*[1-6])(?!\d)", re.I)
_RE_SEQ = re.compile(r"[1-6](?:\s*[-,/]\s*[1-6]){1,5}")
_TRAP_KEYS = ("trapNum", "trap", "dogTrap")


def _nums_pp(v):
    """Extrai numeros de trap (1-6) de um valor: '1-2-5', [1,2,5], [{'trapNum': 1}, ...]."""
    if isinstance(v, bool):
        return []
    if isinstance(v, int):
        return [v] if 1 <= v <= 6 else []
    if isinstance(v, str):
        if re.fullmatch(r"[\s1-6,\-/]+", v):
            return [int(x) for x in re.findall(r"[1-6]", v)]
        m = _RE_PP_TXT.search(v)
        return [int(x) for x in re.findall(r"[1-6]", m.group(1))] if m else []
    if isinstance(v, dict):
        for k in _TRAP_KEYS:
            if k in v:
                return _nums_pp(v[k])
        return [n for x in v.values() for n in _nums_pp(x)]
    if isinstance(v, list):
        return [n for x in v for n in _nums_pp(x)]
    return []


def extrair_post_pick(obj):
    """Procura o Post Pick em qualquer lugar do JSON, em ordem de confianca:
    1) chave 'postPick'/'post_pick'; 2) texto 'POST PICK: 1-2-5'; 3) chave com 'pick';
    4) chave com 'tip' cujo valor e uma sequencia de traps (ex.: '1-2-5')."""
    n1, n2, n3, n4 = [], [], [], []

    def walk(o, caminho):
        if isinstance(o, dict):
            for k, v in o.items():
                nk = re.sub(r"[^a-z]", "", str(k).lower())
                if "postpick" in nk:
                    n = _nums_pp(v)
                    if n: n1.append((n, f"{caminho}/{k}"))
                elif "pick" in nk:
                    n = _nums_pp(v)
                    if n: n3.append((n, f"{caminho}/{k}"))
                elif "tip" in nk and isinstance(v, (str, list)):
                    if isinstance(v, str) and _RE_SEQ.fullmatch(v.strip()):
                        n4.append((_nums_pp(v), f"{caminho}/{k}"))
                walk(v, f"{caminho}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{caminho}[{i}]")
        elif isinstance(o, str):
            m = _RE_PP_TXT.search(o)
            if m:
                n2.append(([int(x) for x in re.findall(r"[1-6]", m.group(1))], caminho + " (texto)"))

    walk(obj, "")
    for grupo in (n1, n2, n3, n4):
        for n, onde in grupo:
            n = list(dict.fromkeys(n))[:6]
            if n:
                return n, onde
    return [], ""


def pistas_post_pick(obj, limite=15):
    """Lista (caminho = valor) das chaves/textos que parecem ligados a post pick/tips, para diagnostico."""
    res = []

    def walk(o, caminho):
        if len(res) >= limite:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                nk = re.sub(r"[^a-z]", "", str(k).lower())
                if any(x in nk for x in ("pick", "tip", "verdict", "forecast")) and not isinstance(v, (dict, list)):
                    res.append(f"{caminho}/{k} = {str(v)[:60]}")
                elif "pick" in nk:
                    res.append(f"{caminho}/{k} = {str(v)[:60]}")
                walk(v, f"{caminho}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o[:12]):
                walk(v, f"{caminho}[{i}]")
        elif isinstance(o, str) and re.search(r"post\s*pick", o, re.I):
            res.append(f"{caminho} = {o[:60]}")

    walk(obj, "")
    return res[:limite]


def _corrida_no_json(obj, race_id):
    """Dentro do JSON da lista de corridas, devolve o trecho (dict) da corrida pedida."""
    achado = []

    def walk(o):
        if achado:
            return
        if isinstance(o, dict):
            if str(o.get("raceId", o.get("race_id", ""))) == str(race_id):
                achado.append(o)
                return
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)

    walk(obj)
    return achado[0] if achado else None


@st.cache_data(ttl=300, show_spinner=False)
def buscar_post_pick(race_id, data_str):
    """Tenta varias respostas do site ate achar o Post Pick. Devolve ('1-2-5', diagnostico)."""
    diag = []
    urls = [f"{BASE}/card/blocks.sd?race_id={race_id}&r_date={data_str}&blocks={b}"
            for b in ("card", "header%2Ccard", "card-header", "card-title",
                      "card-pager%2Ccard-header%2Ccard-tabs%2Ccard-title%2Ccard", "form")]
    urls.append(f"{BASE}/meeting/blocks.sd?r_date={data_str}&blocks=header%2Clist")
    urls.append(f"{BASE}/meeting/blocks.sd?r_date={data_str}&blocks=list")
    for u in urls:
        curto = u.replace(BASE, "")
        time.sleep(0.2)
        try:
            r = http().get(u, timeout=8)
            js = r.json() if r.status_code == 200 else None
        except Exception as e:
            diag.append({"Status": f"erro: {str(e)[:30]}", "Achado": "", "Chaves": "", "Pistas": [],
                         "Endereço": curto})
            continue
        alvo = js
        if js is not None and "/meeting/" in u:      # lista do dia: olhar so a corrida pedida
            alvo = _corrida_no_json(js, race_id)
        nums, onde = extrair_post_pick(alvo) if alvo is not None else ([], "")
        diag.append({"Status": r.status_code,
                     "Achado": f"{'-'.join(map(str, nums))} em {onde}" if nums else "",
                     "Chaves": _chaves(js) if js is not None else "",
                     "Pistas": pistas_post_pick(alvo) if alvo is not None else [],
                     "Endereço": curto})
        if nums:
            return "-".join(map(str, nums)), diag
    return "", diag


def _fmt_pp(pp):
    """Padroniza para '1-2-5' (aceita '1,2,5', '1 2 5', '125'...)."""
    n = re.findall(r"[1-6]", str(pp or ""))
    return "-".join(dict.fromkeys(n)) if n else ""


# ---------------------------------------------------------------- analise
def preparar(race_id, r_date, c, classe_in, dist_in, pp_in, so_antes=False):
    cache = st.session_state.setdefault("cache_corridas", {})
    chave = f"{race_id}|{r_date}"
    if chave not in cache:
        res = dib.extrair_dados_racingpost(f"{BASE}/#card/race_id={race_id}&r_date={r_date}")
        if not res or not res[0]:
            return None
        cache[chave] = res
    dogs, meta, meta_info = cache[chave]
    if so_antes:
        dogs = [dict(d, runs=[r for r in d["runs"] if (r.get("date_str") or "") < r_date]) for d in dogs]
    classe = (classe_in or c.get("grade") or (meta_info or {}).get("classe") or "").strip().upper()
    dist = float(dist_in or c.get("dist") or 0)
    if not dist:
        ds_all = [r["dist"] for d in dogs for r in d["runs"] if r["dist"]]
        dist = float(pd.Series(ds_all).mode().iloc[0]) if ds_all else 480.0
    pp = _fmt_pp(pp_in) or _fmt_pp((meta_info or {}).get("post_pick", ""))
    if not pp:
        pp = _fmt_pp(buscar_post_pick(race_id, r_date)[0])
    ctx = {"dist": dist, "today": dib.parse_date(meta["r_date"]), "classe_n": dib.grade_num(classe),
           "post_pick": [int(x) for x in re.findall(r"\d", pp)],
           "vazias": [t for t in range(1, 7) if t not in {d["trap"] for d in dogs if d["name"] != "vacant"}]}
    ds = [dib.analisar_galgo(d, ctx) for d in dogs]
    rank, _ = dib.finalizar(ds, ctx)
    ds.sort(key=lambda d: d["trap"])
    res = dib.montar_avbs(rank, ctx)
    s1 = res[0] if isinstance(res, tuple) else res
    return {"ds": ds, "rank": rank, "ctx": ctx, "s1": s1, "classe": classe, "dist": dist, "pp": pp}


def titulo_corrida(c, p=None, prefixo=""):
    t = f"{c['pista']} {c['hora']} (BR {hora_br(c['hora'], True)})" if c.get("hora") else ""
    extra = f" · {p['classe']} · {int(p['dist'])}m · Post Pick: {p['pp'] or '-'}" if p else \
        f" · {c.get('grade', '')} · {c.get('dist', '')}m"
    return f"### {prefixo}{t} · Race {c.get('num', '')}{extra}"


# ---------------------------------------------------------------- exportar texto
def gerar_texto_analise(c, p):
    txt = []
    txt.append(titulo_corrida(c, p).replace("### ", ""))
    txt.append("")

    txt.append("**Planilha de Projeção**")
    txt.append("| Trp | Galgo | Overall | Cat | Fatores | Perfil | Grades | Peso | Dias | Split | Time | Méd. Split | Méd. Time | Time Ajust. | Ritmo | Recup. Média | Conf. |")
    txt.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    for d in p["ds"]:
        if d["nd"]:
            txt.append(f"| {d['trap']} | {d['name']} | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |")
            continue

        nome = f"{d['name']} {'🚫' if d.get('bloqueado') else ''} {'🎯' if d.get('alvo') else ''}".strip()
        fat = "<br>".join(f"{k} ({v:+.1f})" for k, v in d["fatores"]) or "-"
        grades = "-".join((r["grade"] or "?") for r in d["runs"])

        f_split = f"{d['split']:.2f}" if d.get("split") else "-"
        f_time = f"{d['time']:.2f}" if d.get("time") else "-"
        f_msplit = f"{d['msplit']:.2f}" if d.get("msplit") else (f"Pos:{d['msplit_pos']:.1f}" if d.get("msplit_pos") else "-")
        f_mtime = f"{d['mtime']:.2f}" if d.get("mtime") else "-"
        f_tadj = f"{d['tadj']:.2f}" if d.get("tadj") else "-"
        f_ritmo = f"{d['ritmo']:.2f}" if d.get("ritmo") else "-"
        f_rec = f"{d['rec']:+.2f}%" if d.get("rec") is not None else "-"
        f_peso = f"{d['peso']:.1f}" if d.get("peso") else "-"

        txt.append(f"| {d['trap']} | {nome} | {d['overall']:.1f} | {d['cat']:.1f} | {fat} | {d['perfil']} | {grades} | {f_peso} | {d['dias']} | {f_split} | {f_time} | {f_msplit} | {f_mtime} | {f_tadj} | {f_ritmo} | {f_rec} | {d['conf']:.0f}% |")

    txt.append("")

    classif = " > ".join(f"{d['pos']}º [T{d['trap']}]" for d in p["rank"])
    txt.append(f"**Classificação:** {classif}")
    txt.append("")

    txt.append("**AVBs Principais (≥ 60%)**")
    if not p["s1"]:
        txt.append("Nenhum confronto atingiu 60%.")
    else:
        txt.append("| Vencedor (Trap/Nome) | Perdedor (Trap/Nome) | Probabilidade |")
        txt.append("|---|---|---|")
        for (V, D, prob, star) in p["s1"]:
            txt.append(f"| {V['trap']} - {V['name']} | {D['trap']} - {D['name']} | {prob:.1f}% |")

    txt.append("")

    txt.append("**🏁 O Cenário da Corrida:**")

    elegiveis = [d for d in p["rank"] if not d.get("bloqueado")]
    bloqueados = [d for d in p["rank"] if d.get("bloqueado")]
    alvos = [d for d in p["rank"] if d.get("alvo")]
    top_ritmo = min([d for d in p["rank"] if d.get("ritmo") is not None], key=lambda x: x["ritmo"], default=None)
    top_split = min([d for d in p["rank"] if d.get("msplit") is not None], key=lambda x: x["msplit"], default=None) if any(d.get("msplit") for d in p["rank"]) else None

    if elegiveis:
        fav = elegiveis[0]
        bloc_acima = [d for d in bloqueados if d["pos"] < fav["pos"]]
        if bloc_acima:
            b_name = bloc_acima[0]['name']
            f_name = fav['name']
            txt.append(f"- 🏆 Melhor Elegível: O favorito absoluto ({b_name}) está bloqueado 🚫. O cão mais seguro é o {f_name} (Posição {fav['pos']} | Recup: {fav['rec']:+.1f}%).")
        else:
            f_name = fav['name']
            txt_rec = f" Ele tem recuperação excelente ({fav['rec']:+.1f}%)." if fav['rec'] > 10 else ""
            txt.append(f"- 🏆 Favorito Claro: O {f_name} domina o Overall ({fav['overall']:.1f}).{txt_rec}")

    if bloqueados:
        b = bloqueados[0]
        b_name = b['name']
        avb_info = ""
        if elegiveis:
            for V, D, prob, star in p["s1"]:
                if (V["trap"] == elegiveis[0]["trap"] and D["trap"] == b["trap"]) or (D["trap"] == elegiveis[0]["trap"] and V["trap"] == b["trap"]):
                    avb_info = f" AVB apertado contra o elegível ({prob:.1f}%)."
                    break
        txt.append(f"- 🚫 Falso Favorito Bloqueado: O {b_name} tem Overall alto ({b['overall']:.1f}), mas foi pego pela Trava (Conf. {b['conf']:.0f}%).{avb_info}")

    if alvos:
        nomes_alvo = ", ".join([d['name'] for d in alvos])
        txt.append(f"- 🎯 Alvo(s): {nomes_alvo} (fora do Top 3 largada e recuperação ≤ 0%).")

    # DIB 3.5: Alerta de pista irlandesa e Alerta de Zebra
    all_splits = [d["msplit"] for d in p["rank"] if d.get("msplit") is not None]
    is_irish_metric = all(s < 2.0 for s in all_splits) if all_splits else False

    if top_split and top_split["msplit"] < 5.0 and not is_irish_metric:
        s_name = top_split['name']
        txt.append(f"- ⚠️ Alerta de Dados: O {s_name} tem Split muito rápido ({top_split['msplit']:.2f}). Pode ser erro na base (considerado 'Melhor Pace').")
    elif top_ritmo and top_split and top_ritmo["trap"] != top_split["trap"]:
        s_name = top_split['name']
        r_name = top_ritmo['name']
        txt.append(f"- 💡 Análise de Pace: O {s_name} tem a melhor largada, mas o {r_name} tem o melhor ritmo final.")
        if top_split["pos"] > 3:
            txt.append(f"- 🦓 Alerta de Zebra: O {s_name} (Posição {top_split['pos']}) tem o melhor Early Pace. Pode surpreender.")
    elif not top_split and top_ritmo:
        top_split_pos = min([d for d in p["rank"] if d.get("msplit_pos") is not None], key=lambda x: x["msplit_pos"], default=None)
        if top_split_pos and top_ritmo["trap"] != top_split_pos["trap"]:
             s_name = top_split_pos['name']
             r_name = top_ritmo['name']
             txt.append(f"- 💡 Análise de Pace: O {s_name} assume a liderança na 1ª curva, mas o {r_name} tem o melhor ritmo de prova final.")

    pior_rec = min([d for d in p["rank"] if d.get("rec") is not None], key=lambda x: x["rec"], default=None)
    if pior_rec and pior_rec["rec"] < -10.0:
        rec_name = pior_rec['name']
        txt.append(f"- ⚠️ Tráfego: O {rec_name} tem recuperação ruim ({pior_rec['rec']:+.1f}%).")

    dropping = [d for d in p["rank"] if d.get("cat_mod", 0) > 0]
    if dropping:
        nomes = ", ".join([d['name'] for d in dropping])
        txt.append(f"- 📉 Queda de Classe: {nomes} desceu(ram) de categoria hoje.")

    top3_ms = p["ctx"].get("top3_ms", set())
    if len(top3_ms) >= 3:
        txt.append("- ⚠️ Conflito de Pace: Múltiplos cães com largada rápida (Top 3 Split). Risco de trombada na 1ª curva.")

    return "\n".join(txt)


def badge_g(t):
    """Número da trap em tamanho maior (cabeçalho da corrida)."""
    return (badge(t).replace("min-width:24px;height:24px;line-height:24px", "min-width:30px;height:30px;line-height:30px")
            .replace("font-size:14px", "font-size:17px"))


def cabecalho_corrida(c, p):
    """Cabeçalho: pista/hora, chips (Race, classe, distância), Classificação geral e Post Pick do site."""
    borda = "border:1px solid rgba(128,128,128,.35);"
    titulo = ""
    if c.get("hora"):
        titulo = (f"<div style='font-size:1.7rem;font-weight:700;line-height:1.25;margin:4px 0 12px'>"
                  f"{c['pista']} {c['hora']} (BR {hora_br(c['hora'], True)})</div>")
    num = str(c.get("num") or "").strip()
    chips = [f"Race {num}" if num else "", p["classe"], f"{int(p['dist'])}m"]
    chips_html = "".join(
        f"<span style='display:inline-block;{borda}background:rgba(128,128,128,.12);border-radius:999px;"
        f"padding:5px 14px;margin:0 8px 8px 0;font-size:1rem'>{x}</span>" for x in chips if x)
    sep = "<span style='opacity:.6'>–</span>"
    ordem = sep.join(badge_g(d["trap"]) for d in p["rank"])
    pp_nums = re.findall(r"[1-6]", p["pp"] or "")
    pp_html = ("<span style='opacity:.6'>-</span>" if not pp_nums
               else "<span style='opacity:.6;margin:0 3px'>-</span>".join(badge_g(n) for n in pp_nums))
    return (titulo + f"<div>{chips_html}</div>"
            "<div style='font-size:1.3rem;font-weight:700;margin:10px 0 8px'>Classificação geral</div>"
            f"<div style='{borda}background:rgba(128,128,128,.08);border-radius:10px;padding:12px 14px'>"
            f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:8px'>{ordem}</div>"
            f"<div style='margin:10px 0 0 10px;font-size:1rem'><span style='opacity:.8'>Post Pick do site:</span> {pp_html}</div>"
            "</div>")


# ---------------------------------------------------------------- colunas travadas ao rolar para o lado
_JS_TRAVAR = """<script>
(function () {
  var win, doc;
  try { win = window.parent; doc = win.document; } catch (e) { return; }

  // Cores das colunas travadas = cores reais do tema atual (claro/escuro), atualizadas ao trocar o tema
  var styleId = 'dib-sticky-style';
  var estilo = doc.getElementById(styleId);
  if (!estilo) {
    estilo = doc.createElement('style');
    estilo.id = styleId;
    doc.head.appendChild(estilo);
  }
  estilo.innerHTML =
    '.dib-table.sticky-1 td:nth-child(1):not(.sep):not(.sep-avb),' +
    '.dib-table.sticky-2 td:nth-child(1):not(.sep):not(.sep-avb),' +
    '.dib-table.sticky-2 td:nth-child(2):not(.sep):not(.sep-avb)' +
    '{ background-color: var(--dib-bg, #fff) !important; }' +
    '.dib-table.sticky-1 th:nth-child(1),' +
    '.dib-table.sticky-2 th:nth-child(1),' +
    '.dib-table.sticky-2 th:nth-child(2)' +
    '{ background-color: var(--dib-bg-head, #f0f2f6) !important; }';
  function cores() {
    var app = doc.querySelector('.stApp') || doc.body;
    var m = win.getComputedStyle(app).backgroundColor.match(/[\\d.]+/g);
    if (!m || m.length < 3 || (m.length > 3 && parseFloat(m[3]) === 0)) return;
    var r = +m[0], g = +m[1], b = +m[2];
    function mix(c) { return Math.round(c * 0.9 + 128 * 0.1); }
    var raiz = doc.documentElement;
    raiz.style.setProperty('--dib-bg', 'rgb(' + r + ',' + g + ',' + b + ')');
    raiz.style.setProperty('--dib-bg-head', 'rgb(' + mix(r) + ',' + mix(g) + ',' + mix(b) + ')');
  }
  cores();
  setInterval(cores, 400);

  function travar(tabela, n) {
    var linhas = tabela.querySelectorAll('tr');
    if (!linhas.length) return false;
    var cab = linhas[0].children, lefts = [], i;
    if (!cab[0] || cab[0].getBoundingClientRect().width === 0) return false;   // tabela escondida
    for (i = 0; i < n; i++) {
      if (!cab[i]) return false;
      lefts.push(i === 0 ? 0 : Math.floor(cab[i].offsetLeft) - 1);
    }
    
    tabela.classList.add('sticky-' + n);

    Array.prototype.forEach.call(linhas, function (tr) {
      var c0 = tr.children[0];
      if (!c0 || (c0.colSpan && c0.colSpan > 1)) return;
      for (var j = 0; j < n && j < tr.children.length; j++) {
        var c = tr.children[j];
        c.style.position = 'sticky';
        c.style.left = lefts[j] + 'px';
        c.style.zIndex = (c.tagName === 'TH') ? '3' : '2';
        
        var sombra = 'inset 0 -1px 0 rgba(128,128,128,.35), inset -1px 0 0 rgba(128,128,128,.45)';
        if (j === n - 1) sombra += ', 3px 0 4px -2px rgba(0,0,0,.35)';
        c.style.boxShadow = sombra;
      }
    });
    return true;
  }
  function aplicar() {
    Array.prototype.forEach.call(doc.querySelectorAll('table.dib-table'), function (t) {
      if (t.getAttribute('data-dibfix') === '1') return;
      var tr0 = t.querySelector('tr');
      if (!tr0) return;
      var cab = Array.prototype.map.call(tr0.children, function (c) {
        return (c.innerText || '').trim().toLowerCase();
      });
      var n = 0;
      if (cab[0] === 'trap' && cab[1] === 'galgo') n = 2;      // Planilha de Projecao
      else if (cab[0] === 'avb') n = 1;                         // Planilha de AVB
      if (n && travar(t, n)) t.setAttribute('data-dibfix', '1');
    });
  }
  [0, 250, 700, 1500, 3000].forEach(function (ms) { setTimeout(aplicar, ms); });
  try {
    var obs = new win.MutationObserver(function () { aplicar(); });
    obs.observe(doc.body, {childList: true, subtree: true});
    setTimeout(function () { obs.disconnect(); }, 20000);
  } catch (e) {}
})();
</script>"""


def fixar_colunas():
    """Trava (sticky) Trap+Galgo na Planilha de Projeção e AvB na Planilha de AVB ao rolar para o lado."""
    components.html(_JS_TRAVAR + f"<!-- {time.time()} -->", height=0)


def analisar(c, classe_in, dist_in, pp_in):
    p = preparar(c["id"], c["data"], c, classe_in, dist_in, pp_in)
    if not p:
        return
    st.markdown(cabecalho_corrida(c, p), unsafe_allow_html=True)
    st.markdown("#### Planilha de Projeção")
    st.markdown(dib.tabela_projecao(p["ds"]), unsafe_allow_html=True)
    st.markdown(grafico_predictor(p["ds"]), unsafe_allow_html=True)
    st.markdown(titulo_corrida(c, p))
    if not p["pp"]:
        st.caption("Post Pick não encontrado automaticamente. Você pode digitar em ⚙️ Ajustes (ex: 1-2-5).")
        with st.expander("🔎 Diagnóstico do Post Pick (copie e cole no chat)", expanded=True):
            diag = buscar_post_pick(c["id"], c["data"])[1]
            linhas = [f"corrida {c['id']} {c['data']}"]
            for d_ in diag:
                linhas.append(f"{d_['Status']} | {d_['Endereço']} | chaves: {d_['Chaves']}")
                linhas += [f"    {x}" for x in d_["Pistas"]]
            relatorio = "\n".join(linhas)
            botao_copiar(relatorio)
            st.text_area("Relatório:", relatorio, height=200)
            st.dataframe(pd.DataFrame([{k: v for k, v in d_.items() if k != "Pistas"} for d_ in diag]),
                         use_container_width=True, hide_index=True)
    dib.tabela_avb(p["s1"], "1ª Planilha — AVB Principal (Prob ≥ 60%)")
    if hasattr(dib, "gerar_observacoes"):
        dib.gerar_observacoes(p["rank"], p["s1"], p["ctx"])

    # BOTÃO DE EXPORTAR COM CÓPIA AUTOMÁTICA
    st.markdown("---")
    with st.expander("📋 Exportar Análise (Copiar e Colar para o Chat)"):
        texto_gerado = gerar_texto_analise(c, p)
        botao_copiar(texto_gerado)  # Chama o botão JS
        st.text_area("Se o botão acima não funcionar, copie o texto aqui:", texto_gerado, height=200)
    fixar_colunas()


# ---------------------------------------------------------------- aba Form
def mostrar_form(c):
    raw = buscar_form_raw(c["id"], c["data"])
    st.markdown(titulo_corrida(c, None, "📄 Form · "))
    if not raw:
        st.warning("Não consegui carregar o Form desta corrida.")
        return
    dib.descobrir_chaves(raw)
    heads = ["Data", "Pista", "Dis", "Trp", "Split", "Bends", "Fin", "By", "Win/Sec", "Remarks",
             "WnTm", "Gng", "Wght", "SP", "Grade", "CalTm"]
    for dog in sorted(raw, key=lambda x: int(re.search(r"\d+", str(x.get("trapNum", 9))).group())
                      if re.search(r"\d+", str(x.get("trapNum", ""))) else 9):
        trap = re.search(r"\d+", str(dog.get("trapNum", "")))
        trainer = _get(dog, "trainer", EXTRA) or ""
        peso = dog.get("weight") or ""
        st.markdown(f"{badge(trap.group()) if trap else ''} **{dog.get('dogName', '?')}**"
                    f"{' · Tnr: ' + str(trainer) if trainer else ''}{' · ' + str(peso) + ' kg' if peso else ''}",
                    unsafe_allow_html=True)
        rows = []
        for f in dog.get("forms", []):
            n = dib.norm_run(f)
            g = lambda k: dib.pick_fb(f, k)
            data = n["date"].strftime("%d%b%y") if n["date"] else n["date_str"]
            rows.append([data, n["track"], f"{int(n['dist'])}m" if n["dist"] else "", n["trap"] or "",
                         g("split") or "", n["bends"], g("fin") or "", g("by") or "",
                         _get(f, "winsec", EXTRA) or "", g("remarks") or "", g("wntm") or "",
                         g("gng") or "", g("weight") or "", _get(f, "sp", EXTRA) or "",
                         n["grade"], g("caltm") or ""])
        if rows:
            tabela_html(heads, rows)
        else:
            st.caption("Sem corridas anteriores (galgo vacant ou sem histórico).")


# ---------------------------------------------------------------- resultados
def mostrar_resultado(c, classe_in, dist_in, pp_in):
    linhas, tent, primeira = buscar_resultado(c["id"], c["data"])
    st.markdown(titulo_corrida(c, None, "📊 Resultado · "))
    mostrar_replay(c)
    if not linhas:
        st.warning("Não consegui ler o resultado desta corrida (ela pode ainda não ter sido disputada). "
                   "Veja o diagnóstico abaixo.")
        st.dataframe(pd.DataFrame(tent), use_container_width=True, hide_index=True)
        if primeira is not None:
            st.caption("Primeira resposta recebida:")
            st.json(primeira if len(str(primeira)) < 6000 else {"(cortado)": str(primeira)[:6000]})
        painel_descobrir(c["id"], c["data"])
        return
    tabela_html(["Pos", "Trap", "Galgo", "SP", "Tempo", "Margem", "Comentário"],
                [[f"{l['pos']}º", badge(l["trap"]), l["nome"], l["sp"], l["tempo"], l["margem"], l["coment"]]
                 for l in linhas])
    try:
        p = preparar(c["id"], c["data"], c, classe_in, dist_in, pp_in, so_antes=True)
        if not p or not p["rank"]:
            return
        prev = {d["trap"]: d["pos"] for d in p["rank"]}
        real = {l["trap"]: l["pos"] for l in linhas if l["trap"]}
        st.markdown("#### 🔍 Previsto × Real (projeção só com corridas anteriores)")
        tabela_html(["Real", "Galgo", "Previsto"],
                    [[f"{l['pos']}º", f"{badge(l['trap'])} {l['nome']}", f"{prev.get(l['trap'], '-')}º"]
                     for l in linhas])
        fav, venc = p["rank"][0], linhas[0]
        top3_prev = {d["trap"] for d in p["rank"][:3]}
        top3_real = {l["trap"] for l in linhas[:3] if l["trap"]}
        st.markdown(f"- **Vencedor:** previsto {badge(fav['trap'])} {fav['name']} → "
                    f"{'✅ acertou' if fav['trap'] == venc['trap'] else '❌ venceu ' + venc['nome']}",
                    unsafe_allow_html=True)
        st.markdown(f"- **Top 3:** {len(top3_prev & top3_real)} de 3 galgos previstos entre os 3 primeiros.")
        if p["s1"]:
            st.markdown("**AVBs (≥ 60%):**")
            for (V, D, prob, star) in p["s1"]:
                pv, pd_ = real.get(V["trap"]), real.get(D["trap"])
                ok = ("✅" if pv < pd_ else "❌") if (pv and pd_) else ("✅" if pv else ("❌" if pd_ else "—"))
                st.markdown(f"- {ok} {badge(V['trap'])} {V['name']} ({pv or '-'}º) vence "
                            f"{badge(D['trap'])} {D['name']} ({pd_ or '-'}º) · {prob:.1f}%", unsafe_allow_html=True)
        else:
            st.markdown("- Nenhum AVB ≥ 60% nesta corrida.")
    except Exception as e:
        st.caption(f"Não foi possível comparar com a projeção: {e}")


# ---------------------------------------------------------------- tela
# Trava a largura da barra lateral no padrao (21rem) e usa letra menor nos botoes das corridas,
# para o texto com o horario do Brasil caber sem alargar a barra.
_CSS_SIDEBAR = """<style>
section[data-testid="stSidebar"]{width:21rem !important;min-width:21rem !important;max-width:21rem !important;}
section[data-testid="stSidebar"] .stButton > button{padding:.35rem .4rem;min-height:0;}
section[data-testid="stSidebar"] .stButton > button p{font-size:.85rem;line-height:1.25;}
</style>"""


def main():
    st.title("🐾 DIB GREYHOUND")

    st.markdown(_CSS_SIDEBAR, unsafe_allow_html=True)
    with st.sidebar:
        modo_txt = st.radio("Ver", ["🏁 Corridas", "📊 Resultados"], horizontal=True, label_visibility="collapsed")
        modo = "res" if "Resultados" in modo_txt else "ana"
        data = st.date_input("Data", value=agora_uk().date())
        data_str = data.strftime("%Y-%m-%d")
        ocultar = st.checkbox("Ocultar corridas já realizadas", value=True) if modo == "ana" else False
        with st.expander("⚙️ Ajustes (opcional)"):
            classe_in = st.text_input("Classe (vazio = da lista)", value="")
            dist_in = st.number_input("Distância (m) - 0 = da lista", value=0, step=10)
            pp_in = st.text_input("Post Pick (ex: 1-2-3)", value="")
            url_custom = st.text_input("Endereço da lista (use {data})", value="")
        corridas, tentativas, primeira = buscar_lista(data_str, url_custom)
        memoria = st.session_state.setdefault("lista_ok", {})
        if corridas:
            memoria[data_str] = corridas
        elif data_str in memoria:
            corridas = memoria[data_str]
            st.caption("⚠️ Usando a última lista carregada (o site não respondeu agora).")
        if not corridas and any(t.get("Status") == 403 for t in tentativas):
            st.error("O site recusou o acesso (403). Costuma ser bloqueio temporário por muitas consultas "
                     "ou data ainda indisponível. Espere alguns minutos, escolha o dia anterior ou toque em Tentar de novo.")
        if st.button("🔄 Recarregar lista"):
            buscar_lista.clear()
            st.rerun()

        sel = st.session_state.get("sel")
        if corridas:
            pistas = sorted({c["pista"] for c in corridas})
            filtro = st.multiselect("Pistas (vazio = todas)", pistas)
            lista = [c for c in corridas if not filtro or c["pista"] in filtro]
            hoje = data == agora_uk().date()
            limite = agora_uk().strftime("%H:%M")
            if modo == "ana" and ocultar and hoje:
                lista = [c for c in lista if c["hora"] >= limite]
            if modo == "res":
                if hoje: lista = [c for c in lista if c["hora"] < limite]
                lista = sorted(lista, key=lambda c: (c["hora"], c["pista"]), reverse=True)
            st.caption(f"{len(lista)} corridas · horário da pista (Brasil = −3h)")
            for c in lista:
                ativo = sel and sel.get("id") == c["id"] and sel.get("modo") == modo
                rotulo = f"{'▶ ' if ativo else ''}{c['hora']} (BR {hora_br(c['hora'], True)}) · {c['pista']} R{c['num'] or '?'} · " \
                         f"{c['grade'] or '?'} · {c['dist'] or '?'}m"
                st.button(rotulo, key=f"{modo}_{c['id']}", use_container_width=True,
                          on_click=escolher, args=(c, data_str, modo))
        else:
            st.warning("Não consegui carregar a lista. Veja o diagnóstico abaixo.")

        with st.expander("🔎 Diagnóstico da lista"):
            st.dataframe(pd.DataFrame(tentativas), use_container_width=True, hide_index=True)
            if not corridas and primeira is not None:
                st.caption("Resposta recebida:")
                st.json(primeira if len(str(primeira)) < 6000 else {"(cortado)": str(primeira)[:6000]})
        with st.expander("🔗 Usar link manual"):
            link = st.text_input("Link da corrida", placeholder="Cole o link aqui...")
            if st.button("Analisar link") and link:
                rid = re.search(r"race_id=(\d+)", link)
                rd = re.search(r"r_date=([\d-]+)", link)
                if rid and rd:
                    escolher({"id": rid.group(1), "hora": "", "pista": "", "num": "", "grade": "", "dist": 0},
                             rd.group(1), "ana")
                    st.rerun()
                else:
                    st.error("Link inválido: precisa ter race_id e r_date.")

    sel = st.session_state.get("sel")
    if sel:
        if sel.get("modo") == "res":
            aba1, aba2 = st.tabs(["📊 Resultado", "📄 Form"])
            with aba1: mostrar_resultado(sel, classe_in, dist_in, pp_in)
        else:
            aba1, aba2 = st.tabs(["📋 Análise", "📄 Form"])
            with aba1: analisar(sel, classe_in, dist_in, pp_in)
        with aba2:
            mostrar_form(sel)
        if st.session_state.pop("fechar", False):
            fechar_sidebar()


main()
