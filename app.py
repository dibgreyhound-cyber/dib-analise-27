# -*- coding: utf-8 -*-
"""
app.py - Lista de corridas / Resultados na barra lateral + analise na pagina principal.
Usa o seu dib_core.py (calculo e tabelas) sem mudancas.
"""
import re
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="DIB GREYHOUND", layout="wide", initial_sidebar_state="auto")
import dib_core as dib

BASE = "https://greyhoundbet.racingpost.com"
LISTA_CANDIDATOS = [
    BASE + "/meeting/blocks.sd?r_date={d}&blocks=header%2Clist",
    BASE + "/meeting/blocks.sd?r_date={d}&blocks=list",
    BASE + "/meeting-list/blocks.sd?r_date={d}&blocks=list",
    BASE + "/meeting/list.sd?r_date={d}",
]
LISTA_RES_CANDIDATOS = [
    BASE + "/results/blocks.sd?r_date={d}&blocks=list",
    BASE + "/results/blocks.sd?r_date={d}&blocks=header%2Clist",
    BASE + "/results-list/blocks.sd?r_date={d}&blocks=list",
    BASE + "/results/list.sd?r_date={d}",
    BASE + "/results/results.sd?r_date={d}",
]
RESULTADO_CANDIDATOS = [
    BASE + "/results/blocks.sd?race_id={rid}&r_date={d}&blocks=result",
    BASE + "/result/blocks.sd?race_id={rid}&r_date={d}&blocks=result",
    BASE + "/results/blocks.sd?race_id={rid}&r_date={d}&blocks=header%2Cresult",
    BASE + "/card/blocks.sd?race_id={rid}&r_date={d}&blocks=result",
    BASE + "/card/blocks.sd?race_id={rid}&r_date={d}&blocks=card%2Cresult",
    BASE + "/results/race.sd?race_id={rid}&r_date={d}",
    BASE + "/card/race.sd?race_id={rid}&r_date={d}",
]
KEYS = {
    "id": ["raceId", "race_id", "rid"],
    "hora": ["raceDate", "offTime", "scheduledTime", "displayTime", "raceTime", "time", "startTime"],
    "pista": ["trackName", "track", "meetingName", "courseName", "venue"],
    "num": ["raceTitle", "raceNum", "raceNumber", "rNum", "number", "raceNo"],
    "grade": ["raceClass", "raceGrade", "grade", "class", "raceClassDesc"],
    "dist": ["distMetres", "distMeters", "distance", "dist", "raceDistance"],
}
# campos de um galgo no resultado (primeiro que existir)
RES = {
    "nome": ["dogName", "dog_name", "name"],
    "pos": ["finishPos", "finPos", "outcomeDesc", "position", "pos", "fin", "outcome", "result"],
    "trap": ["trapNum", "trap", "dogTrap"],
    "sp": ["SP", "sp", "startingPrice", "price", "odds"],
    "tempo": ["calcRTimes", "calTm", "finishTime", "winTime", "time"],
    "margem": ["distBtn", "by", "beatenDistance"],
    "coment": ["closeUpCmnt", "comment", "cmnt", "commentary", "description"],
}


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
    """Qualquer JSON -> corridas (precisa de raceId + horario)."""
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


def achar_resultados(obj):
    """Qualquer JSON -> linhas de resultado (galgo com posicao final)."""
    achados = {}

    def walk(o):
        if isinstance(o, dict):
            nome = _get(o, "nome", RES)
            pos_raw = _get(o, "pos", RES)
            m = re.search(r"\d+", str(pos_raw or ""))
            if isinstance(nome, str) and m and 1 <= int(m.group()) <= 8:
                t = re.search(r"\d+", str(_get(o, "trap", RES) or ""))
                achados[nome] = {
                    "pos": int(m.group()), "trap": int(t.group()) if t else None, "nome": nome,
                    "sp": str(_get(o, "sp", RES) or ""), "tempo": str(_get(o, "tempo", RES) or ""),
                    "margem": str(_get(o, "margem", RES) or ""), "coment": str(_get(o, "coment", RES) or ""),
                }
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return sorted(achados.values(), key=lambda x: x["pos"])


def tentar(urls, parser):
    tentativas, achado, primeira = [], [], None
    for u in urls:
        try:
            r = requests.get(u, headers=dib.HEADERS, timeout=12)
            js = r.json() if r.status_code == 200 else None
        except Exception as e:
            tentativas.append({"URL": u, "Status": f"erro: {str(e)[:50]}", "Achados": 0})
            continue
        res = parser(js) if js is not None else []
        tentativas.append({"URL": u, "Status": r.status_code, "Achados": len(res)})
        if primeira is None and js is not None:
            primeira = js
        if res:
            achado = res
            break
    return achado, tentativas, primeira


@st.cache_data(ttl=120, show_spinner=False)
def buscar_lista(data_str, url_custom, modo):
    base = LISTA_RES_CANDIDATOS if modo == "res" else LISTA_CANDIDATOS
    urls = ([url_custom.replace("{data}", data_str)] if url_custom.strip() else []) \
        + [u.format(d=data_str) for u in base]
    return tentar(urls, achar_corridas)


@st.cache_data(ttl=60, show_spinner=False)
def buscar_resultado(race_id, data_str):
    urls = [u.format(rid=race_id, d=data_str) for u in RESULTADO_CANDIDATOS]
    return tentar(urls, achar_resultados)


# ---------------------------------------------------------------- utilidades
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


def escolher(c, data_str, modo):
    st.session_state["sel"] = dict(c, data=data_str, modo=modo)
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
    if so_antes:   # para comparar com o resultado, usa so corridas ANTERIORES a esta data
        dogs = [dict(d, runs=[r for r in d["runs"] if (r.get("date_str") or "") < r_date]) for d in dogs]
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
    rank, _ = dib.finalizar(ds, ctx)
    ds.sort(key=lambda d: d["trap"])
    res = dib.montar_avbs(rank, ctx)
    s1 = res[0] if isinstance(res, tuple) else res
    return {"ds": ds, "rank": rank, "ctx": ctx, "s1": s1, "classe": classe, "dist": dist, "pp": pp}


def titulo_corrida(c, p, prefixo=""):
    t = f"{c['pista']} {c['hora']} (BR {hora_br(c['hora'])})" if c.get("hora") else ""
    return f"### {prefixo}{t} · Race {c.get('num', '')} · {p['classe']} · {int(p['dist'])}m · POST PICK: {p['pp'] or '-'}"


def analisar(c, classe_in, dist_in, pp_in):
    p = preparar(c["id"], c["data"], c, classe_in, dist_in, pp_in)
    if not p:
        return
    st.markdown(titulo_corrida(c, p))
    st.markdown("#### Planilha de Projeção")
    st.markdown(dib.tabela_projecao(p["ds"]), unsafe_allow_html=True)
    st.markdown("**Classificação:** " + " > ".join(
        f"{dib.MEDALS.get(d['pos'], str(d['pos']) + 'º')} {dib.TRAP_EMOJI[d['trap']]} {d['trap']}" for d in p["rank"]))
    dib.tabela_avb(p["s1"], "1ª Planilha — AVB Principal (Prob ≥ 60%)")
    if hasattr(dib, "gerar_observacoes"):
        dib.gerar_observacoes(p["rank"], p["s1"], p["ctx"])


# ---------------------------------------------------------------- resultados
def mostrar_resultado(c, classe_in, dist_in, pp_in):
    linhas, tent, primeira = buscar_resultado(c["id"], c["data"])
    cab = f"{c.get('pista', '')} {c.get('hora', '')} · Race {c.get('num', '')} · {c.get('grade', '')} · {c.get('dist', '')}m"
    st.markdown(f"### 📊 Resultado · {cab}")
    if not linhas:
        st.warning("Não consegui ler o resultado desta corrida (ela pode ainda não ter sido disputada).")
        with st.expander("🔎 Diagnóstico do resultado"):
            st.dataframe(pd.DataFrame(tent), use_container_width=True, hide_index=True)
            if primeira is not None:
                st.json(primeira if len(str(primeira)) < 6000 else {"(cortado)": str(primeira)[:6000]})
        return
    tab = pd.DataFrame([{
        "Pos": f"{l['pos']}º", "Trap": f"{dib.TRAP_EMOJI.get(l['trap'], '')} {l['trap'] or ''}",
        "Galgo": l["nome"], "SP": l["sp"], "Tempo": l["tempo"], "Margem": l["margem"],
        "Comentário": l["coment"]} for l in linhas])
    st.dataframe(tab, use_container_width=True, hide_index=True)

    try:   # comparacao: previsto x real
        p = preparar(c["id"], c["data"], c, classe_in, dist_in, pp_in, so_antes=True)
        if not p or not p["rank"]:
            return
        prev = {d["trap"]: d["pos"] for d in p["rank"]}
        real = {l["trap"]: l["pos"] for l in linhas if l["trap"]}
        st.markdown("#### 🔍 Previsto × Real (projeção só com corridas anteriores)")
        comp = pd.DataFrame([{"Real": f"{l['pos']}º", "Galgo": f"{dib.TRAP_EMOJI.get(l['trap'], '')} {l['nome']}",
                              "Previsto": f"{prev.get(l['trap'], '-')}º"} for l in linhas])
        st.dataframe(comp, use_container_width=True, hide_index=True)
        fav = p["rank"][0]
        venc = linhas[0]
        top3_prev = {d["trap"] for d in p["rank"][:3]}
        top3_real = {l["trap"] for l in linhas[:3] if l["trap"]}
        st.markdown(f"- **Vencedor:** previsto {dib.TRAP_EMOJI[fav['trap']]} {fav['name']} → "
                    f"{'✅ acertou' if fav['trap'] == venc['trap'] else '❌ venceu ' + venc['nome']}")
        st.markdown(f"- **Top 3:** {len(top3_prev & top3_real)} de 3 galgos previstos entre os 3 primeiros.")
        if p["s1"]:
            st.markdown("**AVBs (≥ 60%):**")
            for (V, D, prob, star) in p["s1"]:
                pv, pd_ = real.get(V["trap"]), real.get(D["trap"])
                if pv and pd_:
                    ok = "✅" if pv < pd_ else "❌"
                elif pv:
                    ok = "✅"
                elif pd_:
                    ok = "❌"
                else:
                    ok = "—"
                st.markdown(f"- {ok} {dib.TRAP_EMOJI[V['trap']]} {V['name']} ({pv or '-'}º) vence "
                            f"{dib.TRAP_EMOJI[D['trap']]} {D['name']} ({pd_ or '-'}º) · {prob:.1f}%")
        else:
            st.markdown("- Nenhum AVB ≥ 60% nesta corrida.")
    except Exception as e:
        st.caption(f"Não foi possível comparar com a projeção: {e}")


# ---------------------------------------------------------------- tela
def main():
    st.title("🐾 DIB GREYHOUND")

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
        corridas, tentativas, primeira = buscar_lista(data_str, url_custom, modo)

        sel = st.session_state.get("sel")
        if corridas:
            pistas = sorted({c["pista"] for c in corridas})
            filtro = st.multiselect("Pistas (vazio = todas)", pistas)
            lista = [c for c in corridas if not filtro or c["pista"] in filtro]
            if ocultar and data == agora_uk().date():
                limite = agora_uk().strftime("%H:%M")
                lista = [c for c in lista if c["hora"] >= limite]
            st.caption(f"{len(lista)} corridas · horário da pista (Brasil = −3h)")
            for c in lista:
                ativo = sel and sel.get("id") == c["id"] and sel.get("modo") == modo
                rotulo = f"{'▶ ' if ativo else ''}{c['hora']} · {c['pista']} R{c['num'] or '?'} · " \
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
            mostrar_resultado(sel, classe_in, dist_in, pp_in)
        else:
            analisar(sel, classe_in, dist_in, pp_in)
        if st.session_state.pop("fechar", False):
            fechar_sidebar()


main()
