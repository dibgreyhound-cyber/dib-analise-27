# -*- coding: utf-8 -*-
"""
app.py (novo) - Lista de corridas na barra lateral + analise na pagina principal.
Usa o seu codigo atual, que deve estar salvo no GitHub como dib_core.py (o antigo app.py renomeado).
"""
import re
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="DIB GREYHOUND 3.3", layout="wide", initial_sidebar_state="auto")
import dib_core as dib   # seu codigo de calculo e tabelas (sem mudancas)

BASE = "https://greyhoundbet.racingpost.com"
# Enderecos tentados (em ordem) para obter a lista de corridas do dia.
CANDIDATOS = [
    BASE + "/meeting/blocks.sd?r_date={d}&blocks=header%2Clist",
    BASE + "/meeting/blocks.sd?r_date={d}&blocks=list",
    BASE + "/meeting-list/blocks.sd?r_date={d}&blocks=list",
    BASE + "/meeting_list/blocks.sd?r_date={d}&blocks=list",
    BASE + "/meeting/list.sd?r_date={d}",
    BASE + "/card/blocks.sd?r_date={d}&blocks=list",
    BASE + "/next/blocks.sd?r_date={d}",
]
KEYS = {
    "id": ["raceId", "race_id", "rid"],
    "hora": ["raceDate", "offTime", "scheduledTime", "displayTime", "raceTime", "time", "startTime"],
    "pista": ["trackName", "track", "meetingName", "courseName", "venue"],
    "num": ["raceTitle", "raceNum", "raceNumber", "rNum", "number", "raceNo"],
    "grade": ["raceClass", "raceGrade", "grade", "class", "raceClassDesc"],
    "dist": ["distMetres", "distMeters", "distance", "dist", "raceDistance"],
}


def _get(d, k):
    for key in KEYS[k]:
        if key in d and d[key] not in (None, "", {}, []):
            return d[key]
    return None


def _hhmm(v):
    m = re.search(r"(\d{1,2}):(\d{2})", str(v or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def achar_corridas(obj):
    """Percorre qualquer JSON e devolve as corridas encontradas (precisa de raceId + horario)."""
    achados = {}

    def walk(o, pista_ctx):
        if isinstance(o, dict):
            p = _get(o, "pista")
            if isinstance(p, str):
                pista_ctx = p
            rid = _get(o, "id")
            hora = _hhmm(_get(o, "hora"))
            if rid is not None and re.fullmatch(r"\d{5,9}", str(rid)) and hora:
                g, d = _get(o, "grade"), _get(o, "dist")
                achados[str(rid)] = {
                    "id": str(rid), "hora": hora, "pista": (pista_ctx or "?").title(),
                    "num": str(_get(o, "num") or "").replace("Race", "").strip(),
                    "grade": re.sub(r"[()\s]", "", str(g or "")).upper(),
                    "dist": int(re.sub(r"\D", "", str(d))) if d and re.search(r"\d", str(d)) else 0,
                }
            for v in o.values():
                walk(v, pista_ctx)
        elif isinstance(o, list):
            for v in o:
                walk(v, pista_ctx)

    walk(obj, "")
    return sorted(achados.values(), key=lambda c: (c["hora"], c["pista"]))


@st.cache_data(ttl=120, show_spinner=False)
def buscar_lista(data_str, url_custom=""):
    urls = ([url_custom.replace("{data}", data_str)] if url_custom.strip() else []) \
        + [u.format(d=data_str) for u in CANDIDATOS]
    tentativas, corridas, primeira = [], [], None
    for u in urls:
        try:
            r = requests.get(u, headers=dib.HEADERS, timeout=12)
            js = r.json() if r.status_code == 200 else None
        except Exception as e:
            tentativas.append({"URL": u, "Status": f"erro: {str(e)[:50]}", "Corridas": 0})
            continue
        achados = achar_corridas(js) if js is not None else []
        tentativas.append({"URL": u, "Status": r.status_code, "Corridas": len(achados)})
        if primeira is None and js is not None:
            primeira = js
        if achados:
            corridas = achados
            break
    return corridas, tentativas, primeira


def hora_br(hhmm):
    h, m = [int(x) for x in hhmm.split(":")]
    t = datetime(2000, 1, 1, h, m) - timedelta(hours=3)
    return f"{t.hour % 12 or 12}:{t.minute:02d}"


def agora_uk():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/London"))
    except Exception:
        return datetime.utcnow()


def escolher(c, data_str):
    st.session_state["sel"] = dict(c, data=data_str)
    st.session_state["fechar"] = True


def fechar_sidebar():
    """No celular, recolhe a barra lateral depois de escolher a corrida."""
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


def analisar(race_id, r_date, c, classe_in, dist_in, pp_in):
    cache = st.session_state.setdefault("cache_corridas", {})
    chave = f"{race_id}|{r_date}"
    if chave not in cache:
        url = f"{BASE}/#card/race_id={race_id}&r_date={r_date}"
        res = dib.extrair_dados_racingpost(url)
        if not res or not res[0]:
            return
        cache[chave] = res
    dogs, meta, meta_info = cache[chave]
    classe = (classe_in or c.get("grade") or (meta_info or {}).get("classe") or "").strip().upper()
    dist = float(dist_in or c.get("dist") or 0)
    if not dist:
        ds_all = [r["dist"] for d in dogs for r in d["runs"] if r["dist"]]
        dist = float(pd.Series(ds_all).mode().iloc[0]) if ds_all else 480.0
    pp = pp_in or (meta_info or {}).get("post_pick", "")
    ctx = {"dist": dist, "today": dib.parse_date(meta["r_date"]), "classe_n": dib.grade_num(classe),
           "post_pick": [int(x) for x in re.findall(r"\d", pp)],
           "vazias": [t for t in range(1, 7) if t not in {d["trap"] for d in dogs if d["name"] != "vacant"}]}
    ds = [dib.analisar_galgo(d, ctx) for d in dogs]
    rank, top3_ms = dib.finalizar(ds, ctx)
    ds.sort(key=lambda d: d["trap"])

    titulo = f"{c['pista']} {c['hora']} (BR {hora_br(c['hora'])})" if c.get("hora") else ""
    st.markdown(f"### {titulo} · Race {c.get('num', '')} · {classe} · {int(dist)}m · POST PICK: {pp or '-'}")
    st.markdown("#### Planilha de Projeção")
    st.markdown(dib.tabela_projecao(ds), unsafe_allow_html=True)
    st.markdown("**Classificação:** " + " > ".join(
        f"{dib.MEDALS.get(d['pos'], str(d['pos']) + 'º')} {dib.TRAP_EMOJI[d['trap']]} {d['trap']}" for d in rank))
    s1, s2, s3 = dib.montar_avbs(rank, ctx)
    dib.tabela_avb(s1, "1ª Planilha — AVB Principal (Prob ≥ 60%)")
    dib.tabela_avb(s2, "2ª Planilha — AVB Secundário (Prob < 60%)")


def main():
    st.title("🐾 DIB GREYHOUND 3.3")
    sel = st.session_state.get("sel")

    with st.sidebar:
        st.header("🏁 Corridas")
        data = st.date_input("Data", value=agora_uk().date())
        data_str = data.strftime("%Y-%m-%d")
        ocultar = st.checkbox("Ocultar corridas já realizadas", value=False)
        with st.expander("⚙️ Ajustes (opcional)"):
            classe_in = st.text_input("Classe (vazio = da lista)", value="")
            dist_in = st.number_input("Distância (m) - 0 = da lista", value=0, step=10)
            pp_in = st.text_input("Post Pick (ex: 1-2-3)", value="")
            url_custom = st.text_input("Endereço da lista (use {data})", value="")
        corridas, tentativas, primeira = buscar_lista(data_str, url_custom)

        if corridas:
            pistas = sorted({c["pista"] for c in corridas})
            filtro = st.multiselect("Pistas (vazio = todas)", pistas)
            lista = [c for c in corridas if not filtro or c["pista"] in filtro]
            if ocultar and data == agora_uk().date():
                limite = agora_uk().strftime("%H:%M")
                lista = [c for c in lista if c["hora"] >= limite]
            st.caption(f"{len(lista)} corridas · horário da pista (Brasil = −3h)")
            for c in lista:
                ativo = sel and sel.get("id") == c["id"]
                rotulo = f"{'▶ ' if ativo else ''}{c['hora']} · {c['pista']} R{c['num'] or '?'} · " \
                         f"{c['grade'] or '?'} · {c['dist'] or '?'}m"
                st.button(rotulo, key=f"r_{c['id']}", use_container_width=True,
                          on_click=escolher, args=(c, data_str))
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
                             rd.group(1))
                    st.rerun()
                else:
                    st.error("Link inválido: precisa ter race_id e r_date.")

    sel = st.session_state.get("sel")
    if sel:
        analisar(sel["id"], sel["data"], sel, classe_in, dist_in, pp_in)
        if st.session_state.pop("fechar", False):
            fechar_sidebar()
    else:
        st.info("👈 Abra a lista de corridas pela seta no canto superior esquerdo e escolha uma corrida.")


main()
