# -*- coding: utf-8 -*-
"""DIB GREYHOUND - app completo com resultados, Replay e Predictor."""
import re, time, json, html
from datetime import datetime, timedelta
from urllib.parse import urlencode
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="DIB GREYHOUND", layout="wide", initial_sidebar_state="auto")
import dib_core as dib

BASE = "https://greyhoundbet.racingpost.com"
LISTA_CANDIDATOS = [
 BASE+"/meeting/blocks.sd?r_date={d}&blocks=header%2Clist",
 BASE+"/meeting/blocks.sd?r_date={d}&blocks=list",
 BASE+"/meeting-list/blocks.sd?r_date={d}&blocks=list",
 BASE+"/meeting/list.sd?r_date={d}",]
KEYS={"id":["raceId","race_id","rid"],"hora":["raceDate","offTime","scheduledTime","displayTime","raceTime","time","startTime"],
"pista":["trackName","track","meetingName","courseName","venue"],"num":["raceTitle","raceNum","raceNumber","rNum","number","raceNo"],
"grade":["raceClass","raceGrade","grade","class","raceClassDesc"],"dist":["distMetres","distMeters","distance","dist","raceDistance"],
"track_id":["trackId","track_id","courseId"],"r_time":["raceTime","r_time","offTime","scheduledTime"]}
RES={"nome":["dogName","dog_name","name","runnerName","greyhoundName"],"pos":["finishPos","finPos","outcomeDesc","position","pos","fin","outcome","result","place"],
"trap":["trapNum","trap","dogTrap","trap_number"],"sp":["SP","sp","startingPrice","price","odds","oddsDesc"],
"tempo":["calcRTimes","calTm","finishTime","winTime","winnersTime","time"],"margem":["distBtn","by","beatenDistance","rpDistDesc","distancesResults"],
"coment":["closeUpCmnt","comment","cmnt","commentary","description"]}
EXTRA={"winsec":["winnerOrSecond","winSec","wnSec","winnerName","secondName"],"sp":["SP","sp","startingPrice","price"],"trainer":["trainerName","trainer","trainer_name"]}
RESULT_CANDIDATES=(
 [BASE+"/results/blocks.sd?race_id={rid}&r_date={d}&blocks="+b for b in ("result","results","header%2Cresult")]
 +[BASE+"/result/blocks.sd?race_id={rid}&r_date={d}&blocks="+b for b in ("result","results")]
 +[BASE+"/card/blocks.sd?race_id={rid}&r_date={d}&blocks="+b for b in ("result","results")]
 +[BASE+"/results/race.sd?race_id={rid}&r_date={d}"])

class _Http:
 def __init__(self):
  self.s=requests.Session(); self.s.headers.update({"User-Agent":dib.HEADERS.get("User-Agent","Mozilla/5.0"),"Accept":"application/json, text/plain, */*","Accept-Language":"en-GB,en;q=0.9","X-Requested-With":"XMLHttpRequest","Referer":BASE+"/","Origin":BASE}); self.pronto=False
 def get(self,url,headers=None,timeout=15):
  if not self.pronto:
   try:self.s.get(BASE+"/",timeout=8)
   except Exception:pass
   self.pronto=True
  r=self.s.get(url,headers=headers,timeout=timeout)
  if r.status_code in (403,429):time.sleep(1.5);r=self.s.get(url,headers=headers,timeout=timeout)
  return r
@st.cache_resource
def http():return _Http()
dib.requests=http()
BADGE_STYLE={1:"background:#d62828;color:#fff;",2:"background:#1d4ed8;color:#fff;",3:"background:#fff;color:#000;border:1px solid #000;",4:"background:#111;color:#fff;border:1px solid #444;",5:"background:#f97316;color:#fff;",6:"background:repeating-linear-gradient(90deg,#111 0 4px,#fff 4px 8px);color:#e11;text-shadow:0 0 2px #fff;"}
def badge(t):
 try:t=int(t)
 except Exception:return ""
 return f"<span style='display:inline-block;min-width:24px;height:24px;line-height:24px;text-align:center;border-radius:4px;font-weight:700;font-size:14px;vertical-align:middle;{BADGE_STYLE.get(t,'')}'>{t}</span>"
class _St:
 def __getattr__(self,n):return getattr(st,n)
 def markdown(self,body,*a,**k):k.setdefault("unsafe_allow_html",True);return st.markdown(body,*a,**k)
dib.st=_St();dib.TRAP_EMOJI={t:badge(t) for t in range(1,7)};dib.trap_label=lambda d:badge(d["trap"])

def botao_copiar(texto):
 texto_js=json.dumps(texto)
 components.html(f"""<html><body><button id="copyBtn" style="background:#ff4b4b;color:white;border:0;padding:12px;border-radius:8px;width:100%;font-weight:bold">📋 Copiar Análise para o Chat</button><script>const textToCopy={texto_js};document.getElementById("copyBtn").onclick=async()=>{{try{{await navigator.clipboard.writeText(textToCopy);document.getElementById("copyBtn").innerText="✅ Texto Copiado! Cole no Chat."}}catch(e){{document.getElementById("copyBtn").innerText="Erro: copie manualmente"}}}};</script></body></html>""",height=65)
def _get(d,k,tabela=KEYS):
 if not isinstance(d,dict):return None
 for key in tabela[k]:
  if key in d and d[key] not in (None,"",{},[]):return d[key]
 return None
def _hhmm(v):
 m=re.search(r"(\d{1,2}):(\d{2})",str(v or ""));return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None
def achar_corridas(obj):
 achados={}
 def walk(o,pista_ctx):
  if isinstance(o,dict):
   p=_get(o,"pista")
   if isinstance(p,str):pista_ctx=p
   rid=_get(o,"id");hora=_hhmm(_get(o,"hora"))
   if rid is not None and re.fullmatch(r"\d{5,9}",str(rid)) and hora:
    g,d=_get(o,"grade"),_get(o,"dist")
    achados[str(rid)]={"id":str(rid),"hora":hora,"pista":(pista_ctx or "?").title(),"num":str(_get(o,"num") or "").replace("Race","").strip(),"grade":re.sub(r"[()\s]","",str(g or "")).upper(),"dist":int(re.sub(r"\D","",str(d))) if d and re.search(r"\d",str(d)) else 0,"track_id":str(_get(o,"track_id") or ""),"r_time":str(_get(o,"r_time") or hora or "")}
   for v in o.values():walk(v,pista_ctx)
  elif isinstance(o,list):
   for v in o:walk(v,pista_ctx)
 walk(obj,"");return sorted(achados.values(),key=lambda c:(c["hora"],c["pista"]))

# Parser robusto: encontra corredores em qualquer nível do JSON
RKEYS={"nome":("dogName","dog_name","name","runnerName","greyhoundName"),"pos":("position","finishPos","finPos","outcomeDesc","pos","fin","place","result"),"trap":("trapNum","trap","dogTrap","trap_number"),"sp":("SP","sp","startingPrice","price","odds","oddsDesc"),"tempo":("winnersTimeS","winTime","finishTime","time","calcRTimes","calTm"),"margem":("rpDistDesc","distBtn","distancesResults","by","beatenDistance","fract"),"coment":("comment","closeUpCmnt","cmnt","commentary","description"),"trainer":("trainer","trainerName","trainer_name"),"split":("splitTime","sectionalTime","split")}
def _first_value(obj,keys):
 if not isinstance(obj,dict):return None
 for k in keys:
  v=obj.get(k)
  if v not in (None,"",[],{}):return v
 return None
def _walk_result_objects(obj):
 if isinstance(obj,dict):
  nome=_first_value(obj,RKEYS["nome"]);pos=_first_value(obj,RKEYS["pos"]);trap=_first_value(obj,RKEYS["trap"])
  if nome is not None and (pos is not None or trap is not None):yield obj
  for v in obj.values():yield from _walk_result_objects(v)
 elif isinstance(obj,list):
  for v in obj:yield from _walk_result_objects(v)
def _parse_position(v):
 if v is None:return None
 s=str(v).strip().upper()
 if s in {"N","NR","RES","VOID","DQ","DNF","PU","F"}:return None
 m=re.search(r"\d+",s);return int(m.group()) if m else None
def achar_resultados(obj):
 achados=[];vistos=set()
 for row in _walk_result_objects(obj):
  nome=str(_first_value(row,RKEYS["nome"]) or "").strip();pos=_parse_position(_first_value(row,RKEYS["pos"]));tr=_first_value(row,RKEYS["trap"]);mt=re.search(r"\d+",str(tr or ""));trap=int(mt.group()) if mt else None
  if not nome or (pos is None and trap is None):continue
  chave=(nome.lower(),trap,pos)
  if chave in vistos:continue
  vistos.add(chave);achados.append({"pos":pos if pos is not None else 99,"trap":trap,"nome":nome,"sp":str(_first_value(row,RKEYS["sp"]) or ""),"tempo":str(_first_value(row,RKEYS["tempo"]) or ""),"margem":str(_first_value(row,RKEYS["margem"]) or ""),"coment":str(_first_value(row,RKEYS["coment"]) or ""),"trainer":str(_first_value(row,RKEYS["trainer"]) or ""),"split":str(_first_value(row,RKEYS["split"]) or "")})
 return sorted(achados,key=lambda x:(x["pos"],x["trap"] or 99))
def _chaves(js):
 if not isinstance(js,dict):return type(js).__name__
 return ", ".join(f"{k}{'(erro)' if isinstance(v,dict) and 'errorCode' in v else ''}" for k,v in js.items())[:120]
def tentar(urls,parser):
 tentativas=[];achado=[];primeira=None
 for u in urls:
  time.sleep(.25)
  try:r=http().get(u,timeout=10);js=r.json() if r.status_code==200 else None
  except Exception as e:tentativas.append({"URL":u.replace(BASE,""),"Status":f"erro: {str(e)[:60]}","Achados":0,"Chaves":""});continue
  res=parser(js) if js is not None else [];tentativas.append({"URL":u.replace(BASE,""),"Status":r.status_code,"Achados":len(res),"Chaves":_chaves(js) if js is not None else ""})
  if primeira is None and js is not None:primeira=js
  if res:achado=res;break
 return achado,tentativas,primeira
@st.cache_data(ttl=120,show_spinner=False)
def buscar_lista(data_str,url_custom):
 urls=([url_custom.replace("{data}",data_str)] if url_custom.strip() else [])+[u.format(d=data_str) for u in LISTA_CANDIDATOS];return tentar(urls,achar_corridas)
def _resultado_urls(race_id,data_str,track_id=None,race_time=None):
 params={"race_id":race_id,"r_date":data_str}
 if track_id:params["track_id"]=track_id
 if race_time:params["r_time"]=race_time
 q=urlencode(params)
 return [f"{BASE}/results/blocks.sd?{q}&blocks=result",f"{BASE}/results/blocks.sd?{q}&blocks=results",f"{BASE}/results/blocks.sd?{q}&blocks=header%2Cresult",f"{BASE}/result/blocks.sd?{q}&blocks=result",f"{BASE}/result/blocks.sd?{q}&blocks=results",f"{BASE}/card/blocks.sd?{q}&blocks=result",f"{BASE}/card/blocks.sd?{q}&blocks=results",f"{BASE}/results/race.sd?{q}"]
@st.cache_data(ttl=45,show_spinner=False)
def buscar_resultado(race_id,data_str,track_id=None,race_time=None):
 tent=[];primeira=None;achados=[]
 for url in _resultado_urls(race_id,data_str,track_id,race_time):
  try:
   r=http().get(url,timeout=12);ct=r.headers.get("Content-Type","")
   try:js=r.json() if r.status_code==200 else None
   except Exception:js=None
   if primeira is None and (js is not None or r.text):primeira=js if js is not None else r.text[:5000]
   encontrados=achar_resultados(js) if js is not None else []
   tent.append({"URL":url.replace(BASE,""),"Status":r.status_code,"Content-Type":ct,"Bytes":len(r.content),"Achados":len(encontrados),"Chaves":_chaves(js) if isinstance(js,dict) else type(js).__name__})
   if encontrados:achados=encontrados;break
  except Exception as e:tent.append({"URL":url.replace(BASE,""),"Status":f"erro: {e}","Achados":0})
 return achados,tent,primeira
@st.cache_data(ttl=300,show_spinner=False)
def buscar_form_raw(race_id,data_str):
 try:r=http().get(f"{BASE}/card/blocks.sd?race_id={race_id}&r_date={data_str}&blocks=form",timeout=15);r.raise_for_status();return r.json().get("form",{}).get("dogs",[])
 except Exception:return []
def hora_br(hhmm):
 h,m=[int(x) for x in hhmm.split(":")];t=datetime(2000,1,1,h,m)-timedelta(hours=3);return f"{t.hour%12 or 12}:{t.minute:02d}"
def agora_uk():
 try:from zoneinfo import ZoneInfo;return datetime.now(ZoneInfo("Europe/London"))
 except Exception:return datetime.utcnow()
def escolher(c,data_str,modo):st.session_state["sel"]=dict(c,data=data_str,modo=modo);st.session_state["fechar"]=True
def fechar_sidebar():
 components.html("""<script>try{const d=window.parent.document;if(window.parent.innerWidth<900){const b=d.querySelector('[data-testid="stSidebarCollapseButton"] button')||d.querySelector('[data-testid="stSidebarCollapseButton"]')||d.querySelector('button[kind="header"]');if(b)b.click()}}catch(e){}</script>""",height=0)
def tabela_html(headers,rows):st.markdown(dib.tbl(headers,rows),unsafe_allow_html=True)
def preparar(race_id,r_date,c,classe_in,dist_in,pp_in,so_antes=False):
 cache=st.session_state.setdefault("cache_corridas",{});chave=f"{race_id}|{r_date}"
 if chave not in cache:
  res=dib.extrair_dados_racingpost(f"{BASE}/#card/race_id={race_id}&r_date={r_date}")
  if not res or not res[0]:return None
  cache[chave]=res
 dogs,meta,meta_info=cache[chave]
 if so_antes:dogs=[dict(d,runs=[r for r in d["runs"] if (r.get("date_str") or "")<r_date]) for d in dogs]
 classe=(classe_in or c.get("grade") or (meta_info or {}).get("classe") or "").strip().upper();dist=float(dist_in or c.get("dist") or 0)
 if not dist:
  ds_all=[r["dist"] for d in dogs for r in d["runs"] if r["dist"]];dist=float(pd.Series(ds_all).mode().iloc[0]) if ds_all else 480.0
 pp=pp_in or (meta_info or {}).get("post_pick","");ctx={"dist":dist,"today":dib.parse_date(meta["r_date"]),"classe_n":dib.grade_num(classe),"post_pick":[int(x) for x in re.findall(r"\d",pp)],"vazias":[t for t in range(1,7) if t not in {d["trap"] for d in dogs if d["name"]!="vacant"}]}
 ds=[dib.analisar_galgo(d,ctx) for d in dogs];rank,_=dib.finalizar(ds,ctx);ds.sort(key=lambda d:d["trap"]);res=dib.montar_avbs(rank,ctx);s1=res[0] if isinstance(res,tuple) else res
 return {"ds":ds,"rank":rank,"ctx":ctx,"s1":s1,"classe":classe,"dist":dist,"pp":pp}
def titulo_corrida(c,p=None,prefixo=""):
 t=f"{c['pista']} {c['hora']} (BR {hora_br(c['hora'])})" if c.get("hora") else "";extra=f" · {p['classe']} · {int(p['dist'])}m · POST PICK: {p['pp'] or '-'}" if p else f" · {c.get('grade','')} · {c.get('dist','')}m"
 return f"### {prefixo}{t} · Race {c.get('num','')}{extra}"

# Predictor estilo Racing Post, barras por score Overall

def grafico_predictor(ds):
 """Predictor renderizado em iframe próprio (evita o Streamlit ocultar o HTML/CSS)."""
 cores={1:"#d62828",2:"#1d4ed8",3:"#f4f4f4",4:"#111111",5:"#f97316",6:"#f4f4f4"}
 dogs=sorted(ds,key=lambda d:int(d.get("trap",99)))
 valores=[float(d.get("overall") or 0) for d in dogs if not d.get("nd")]
 lo=min(valores,default=0);hi=max(valores,default=1)
 if hi<=lo:hi=lo+1
 svg="""<svg viewBox="0 0 100 55" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
 <g fill="#eaf2f7"><path d="M5 27 18 17 43 20 58 13 75 16 91 10 97 16 84 25 69 26 59 34 56 49 50 49 51 32 38 32 27 46 21 46 27 29 15 31Z"/>
 <path d="M18 19 8 7 4 10 13 24Z"/><path d="M72 17 80 5 85 7 79 22Z"/></g></svg>"""
 rows=[]
 for d in dogs:
  trap=int(d.get("trap",0) or 0)
  if not 1<=trap<=6:continue
  empty=bool(d.get("nd"));val=float(d.get("overall") or 0)
  width=max(8,min(100,12+88*((val-lo)/(hi-lo)))) if not empty else 0
  bg=cores[trap]
  badge_bg=("repeating-linear-gradient(90deg,#111 0 5px,#fff 5px 10px)" if trap==6 else bg)
  color="#111" if trap in (3,4) else ("#e11" if trap==6 else "#fff")
  border="1px solid #111" if trap in (3,4,6) else "none"
  rows.append(f"""<div class="row">
   <div class="trap" style="background:{badge_bg};color:{color};border:{border}">{trap}</div>
   <div class="lane"><div class="bar" style="width:{width:.1f}%;background:{bg}">
    <span class="dog">{svg}</span></div></div></div>""")
 html_doc=f"""<!doctype html><html><head><meta charset="utf-8">
 <style>
 *{{box-sizing:border-box}}body{{margin:0;background:transparent;font-family:Arial,sans-serif}}
 .wrap{{background:#597f9c;border:1px solid #7b9ab3;border-radius:20px;padding:10px 14px;color:#fff}}
 .head{{display:inline-block;background:#c52b25;padding:7px 22px;border-radius:15px 15px 0 0;font-weight:700;font-size:18px}}
 .row{{display:flex;align-items:center;gap:8px;height:47px;margin:5px 0}}
 .trap{{width:39px;min-width:39px;height:39px;display:flex;align-items:center;justify-content:center;font-size:25px;font-weight:800;border-radius:5px}}
 .lane{{height:39px;flex:1;min-width:0;background:#073c61;border-radius:24px;overflow:hidden}}
 .bar{{height:100%;min-width:0;border-radius:24px;display:flex;align-items:center;justify-content:flex-end;padding-right:3px}}
 .dog{{width:34px;height:25px;flex-shrink:0;display:block}}.dog svg{{width:100%;height:100%;display:block}}
 </style></head><body><div class="wrap"><div class="head">Predictor</div>{''.join(rows)}</div></body></html>"""
 components.html(html_doc,height=360,scrolling=False)

def gerar_texto_analise(c,p):
 txt=[titulo_corrida(c,p).replace("### ",""),"","**Planilha de Projeção**","| Trp | Galgo | Overall | Cat | Fatores | Perfil | Grades | Peso | Dias | Split | Time | Méd. Split | Méd. Time | Time Ajust. | Ritmo | Recup. Média | Conf. |","|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
 for d in p["ds"]:
  if d["nd"]:txt.append(f"| {d['trap']} | {d['name']} | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | ");continue
  nome=f"{d['name']} {'🚫' if d.get('bloqueado') else ''} {'🎯' if d.get('alvo') else ''}".strip();fat="<br>".join(f"{k} ({v:+.1f})" for k,v in d["fatores"]) or "-";grades="-".join((r["grade"] or "?") for r in d["runs"])
  fmt=lambda k:f"{d[k]:.2f}" if d.get(k) else "-"
  txt.append(f"| {d['trap']} | {nome} | {d['overall']:.1f} | {d['cat']:.1f} | {fat} | {d['perfil']} | {grades} | {d['peso']:.1f} | {d['dias']} | {fmt('split')} | {fmt('time')} | {fmt('msplit')} | {fmt('mtime')} | {fmt('tadj')} | {fmt('ritmo')} | {d['rec']:+.2f}% | {d['conf']:.0f}% |")
 txt+= ["", "**Classificação:** "+" > ".join(f"{d['pos']}º [T{d['trap']} ]" for d in p["rank"]),"","**AVBs Principais (≥ 60%)**"]
 if not p["s1"]:txt.append("Nenhum confronto atingiu 60%.")
 else:
  txt += ["| Vencedor (Trap/Nome) | Perdedor (Trap/Nome) | Probabilidade |","|---|---|---|"]
  for V,D,prob,star in p["s1"]:txt.append(f"| {V['trap']} - {V['name']} | {D['trap']} - {D['name']} | {prob:.1f}% |")
 txt.append("");txt.append("**🏁 O Cenário da Corrida:**");eleg=[d for d in p["rank"] if not d.get("bloqueado")];bloq=[d for d in p["rank"] if d.get("bloqueado")];alvos=[d for d in p["rank"] if d.get("alvo")]
 if eleg:txt.append(f"- 🏆 Melhor elegível/favorito: {eleg[0]['name']} (Overall {eleg[0]['overall']:.1f}).")
 if bloq:txt.append(f"- 🚫 Favorito bloqueado: {bloq[0]['name']} (confiança {bloq[0]['conf']:.0f}%).")
 if alvos:txt.append("- 🎯 Alvo(s): "+", ".join(d["name"] for d in alvos)+".")
 return "\n".join(txt)

def analisar(c,classe_in,dist_in,pp_in):
 p=preparar(c["id"],c["data"],c,classe_in,dist_in,pp_in)
 if not p:st.error("Não consegui preparar a análise desta corrida.");return
 st.markdown(titulo_corrida(c,p));st.markdown("#### Planilha de Projeção");st.markdown(dib.tabela_projecao(p["ds"]),unsafe_allow_html=True)
 st.markdown("#### Predictor");grafico_predictor(p["ds"]);st.markdown("&nbsp; ".join(badge(d["trap"]) for d in p["rank"]),unsafe_allow_html=True);st.markdown(titulo_corrida(c,p))
 dib.tabela_avb(p["s1"],"1ª Planilha — AVB Principal (Prob ≥ 60%)")
 if hasattr(dib,"gerar_observacoes"):dib.gerar_observacoes(p["rank"],p["s1"],p["ctx"])
 st.markdown("---")
 with st.expander("📋 Exportar Análise (Copiar e Colar para o Chat)"):
  texto=gerar_texto_analise(c,p);botao_copiar(texto);st.text_area("Se o botão acima não funcionar, copie o texto aqui:",texto,height=200)

def link_resultado_rp(c):
 params=f"race_id={c['id']}";track=c.get("track_id") or c.get("trackId");rt=c.get("r_time") or c.get("race_time") or c.get("hora")
 if track:params+=f"&track_id={track}"
 params+=f"&r_date={c['data']}"
 if rt:params+=f"&r_time={rt}"
 return f"{BASE}/#result-meeting-result/{params}"
def mostrar_resultado(c,classe_in,dist_in,pp_in):
 linhas,tent,primeira=buscar_resultado(c["id"],c["data"],c.get("track_id"),c.get("r_time") or c.get("hora"));st.markdown(titulo_corrida(c,None,"📊 Resultado · "));st.link_button("🌐 Abrir resultado oficial / Replay no Racing Post",link_resultado_rp(c),use_container_width=True)
 if not linhas:
  st.warning("Não localizei os corredores no JSON retornado. Isso não significa que a corrida não tenha resultado. Abra o resultado oficial/Replay acima.");st.dataframe(pd.DataFrame(tent),use_container_width=True,hide_index=True)
  with st.expander("Resposta recebida (diagnóstico)"):st.json(primeira if isinstance(primeira,(dict,list)) else {"resposta":primeira})
  return
 tabela_html(["Pos","Trap","Galgo","SP","Tempo","Margem","Comentário"],[[f"{l['pos']}º" if l["pos"]<99 else "NR",badge(l["trap"]),l["nome"],l["sp"],l["tempo"],l["margem"],l["coment"]] for l in linhas])
 try:
  p=preparar(c["id"],c["data"],c,classe_in,dist_in,pp_in,so_antes=True)
  if not p or not p["rank"]:return
  prev={d["trap"]:d["pos"] for d in p["rank"]};real={l["trap"]:l["pos"] for l in linhas if l["trap"] and l["pos"]<99};st.markdown("#### 🔍 Previsto × Real (projeção só com corridas anteriores)")
  tabela_html(["Real","Galgo","Previsto"],[[f"{l['pos']}º" if l["pos"]<99 else "NR",f"{badge(l['trap'])} {l['nome']}",f"{prev.get(l['trap'],'-')}º"] for l in linhas]);fav=p["rank"][0];venc=linhas[0]
  st.markdown(f"- **Vencedor previsto:** {badge(fav['trap'])} {fav['name']} · {'✅ acertou' if fav['trap']==venc['trap'] else '❌ venceu '+venc['nome']}",unsafe_allow_html=True)
  top3_acertos=len(set(d['trap'] for d in p['rank'][:3]).intersection(set(l['trap'] for l in linhas[:3] if l['trap'])))
  st.markdown(f"- **Top 3:** {top3_acertos} de 3 galgos previstos entre os três primeiros.")
  if p["s1"]:
   st.markdown("**AVBs (≥ 60%):**")
   for V,D,prob,star in p["s1"]:
    pv,pd_=real.get(V["trap"]),real.get(D["trap"]);ok="✅" if (pv and pd_ and pv<pd_) else "❌" if (pv and pd_) else "—";st.markdown(f"- {ok} {badge(V['trap'])} {V['name']} ({pv or '-'}º) vence {badge(D['trap'])} {D['name']} ({pd_ or '-'}º) · {prob:.1f}%",unsafe_allow_html=True)
 except Exception as e:st.caption(f"Comparação com a projeção indisponível: {e}")

def mostrar_form(c):
 raw=buscar_form_raw(c["id"],c["data"]);st.markdown(titulo_corrida(c,None,"📄 Form · "))
 if not raw:st.warning("Não consegui carregar o Form desta corrida.");return
 dib.descobrir_chaves(raw);heads=["Data","Pista","Dis","Trp","Split","Bends","Fin","By","Win/Sec","Remarks","WnTm","Gng","Wght","SP","Grade","CalTm"]
 for dog in sorted(raw,key=lambda x:int(re.search(r"\d+",str(x.get("trapNum",9))).group()) if re.search(r"\d+",str(x.get("trapNum",""))) else 9):
  trap=re.search(r"\d+",str(dog.get("trapNum","")));trainer=_get(dog,"trainer",EXTRA) or "";peso=dog.get("weight") or "";st.markdown(f"{badge(trap.group()) if trap else ''} **{dog.get('dogName','?')}**{' · Tnr: '+str(trainer) if trainer else ''}{' · '+str(peso)+' kg' if peso else ''}",unsafe_allow_html=True);rows=[]
  for f in dog.get("forms",[]):
   n=dib.norm_run(f);g=lambda k:dib.pick_fb(f,k);data=n["date"].strftime("%d%b%y") if n["date"] else n["date_str"]
   rows.append([data,n["track"],f"{int(n['dist'])}m" if n["dist"] else "",n["trap"] or "",g("split") or "",n["bends"],g("fin") or "",g("by") or "",_get(f,"winsec",EXTRA) or "",g("remarks") or "",g("wntm") or "",g("gng") or "",g("weight") or "",_get(f,"sp",EXTRA) or "",n["grade"],g("caltm") or ""])
  if rows:tabela_html(heads,rows)
  else:st.caption("Sem corridas anteriores (galgo vacant ou sem histórico).")

def main():
 st.title("🐾 DIB GREYHOUND")
 with st.sidebar:
  modo_txt=st.radio("Ver",["🏁 Corridas","📊 Resultados"],horizontal=True,label_visibility="collapsed");modo="res" if "Resultados" in modo_txt else "ana";data=st.date_input("Data",value=agora_uk().date());data_str=data.strftime("%Y-%m-%d");ocultar=st.checkbox("Ocultar corridas já realizadas",value=True) if modo=="ana" else False
  with st.expander("⚙️ Ajustes (opcional)"):
   classe_in=st.text_input("Classe (vazio = da lista)",value="");dist_in=st.number_input("Distância (m) - 0 = da lista",value=0,step=10);pp_in=st.text_input("Post Pick (ex: 1-2-3)",value="");url_custom=st.text_input("Endereço da lista (use {data})",value="")
  corridas,tentativas,primeira=buscar_lista(data_str,url_custom);mem=st.session_state.setdefault("lista_ok",{})
  if corridas:mem[data_str]=corridas
  elif data_str in mem:corridas=mem[data_str];st.caption("⚠️ Usando a última lista carregada (o site não respondeu agora).")
  if not corridas and any(t.get("Status")==403 for t in tentativas):st.error("O site recusou acesso (403). Aguarde, tente outra data ou recarregue.")
  if not corridas and st.button("🔄 Tentar de novo"):buscar_lista.clear();st.rerun()
  sel=st.session_state.get("sel")
  if corridas:
   pistas=sorted({c["pista"] for c in corridas});filtro=st.multiselect("Pistas (vazio = todas)",pistas);lista=[c for c in corridas if not filtro or c["pista"] in filtro];hoje=data==agora_uk().date();limite=agora_uk().strftime("%H:%M")
   if modo=="ana" and ocultar and hoje:lista=[c for c in lista if c["hora"]>=limite]
   if modo=="res":
    if hoje:lista=[c for c in lista if c["hora"]<limite]
    lista=sorted(lista,key=lambda c:(c["hora"],c["pista"]),reverse=True)
   st.caption(f"{len(lista)} corridas · horário da pista (Brasil = −3h)")
   for c in lista:
    ativo=sel and sel.get("id")==c["id"] and sel.get("modo")==modo;rot=f"{'▶ ' if ativo else ''}{c['hora']} · {c['pista']} R{c['num'] or '?'} · {c['grade'] or '?'} · {c['dist'] or '?'}m";st.button(rot,key=f"{modo}_{c['id']}",use_container_width=True,on_click=escolher,args=(c,data_str,modo))
  else:st.warning("Não consegui carregar a lista. Veja o diagnóstico abaixo.")
  with st.expander("🔎 Diagnóstico da lista"):
   st.dataframe(pd.DataFrame(tentativas),use_container_width=True,hide_index=True)
   if not corridas and primeira is not None:st.caption("Resposta recebida:");st.json(primeira if len(str(primeira))<6000 else {"cortado":str(primeira)[:6000]})
  with st.expander("🔗 Usar link manual"):
   link=st.text_input("Link da corrida",placeholder="Cole o link aqui...")
   if st.button("Analisar link") and link:
    rid=re.search(r"race_id=(\d+)",link);rd=re.search(r"r_date=([\d-]+)",link);track=re.search(r"track_id=(\d+)",link);rt=re.search(r"r_time=([\d:]+)",link)
    if rid and rd:escolher({"id":rid.group(1),"hora":rt.group(1) if rt else "","r_time":rt.group(1) if rt else "","track_id":track.group(1) if track else "","pista":"","num":"","grade":"","dist":0},rd.group(1),"ana");st.rerun()
    else:st.error("Link inválido: precisa ter race_id e r_date.")
 sel=st.session_state.get("sel")
 if sel:
  if sel.get("modo")=="res":aba1,aba2=st.tabs(["📊 Resultado","📄 Form"]); 
  else:aba1,aba2=st.tabs(["📋 Análise","📄 Form"])
  with aba1:
   if sel.get("modo")=="res":mostrar_resultado(sel,classe_in,dist_in,pp_in)
   else:analisar(sel,classe_in,dist_in,pp_in)
  with aba2:mostrar_form(sel)
  if st.session_state.pop("fechar",False):fechar_sidebar()
main()
