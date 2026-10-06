# -*- coding: utf-8 -*-
# COLETOR DE NOTICIAS + INFORMATIVO - acompanhamento do STJ.
#
# Gera DUAS listas separadas:
#   NOTICIAS    -> aba "Noticias": STJ oficial (noticias) + imprensa (Google News), filtrada por relevancia.
#   INFORMATIVO -> aba "Informativo": somente o feed oficial do Informativo de Jurisprudencia do STJ.
#
# Mostra SEMPRE so manchete/titulo + fonte + data + link para o site original (e, no informativo,
# o resumo oficial do STJ, que e conteudo publico). Nunca o texto integral de materia de imprensa.

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from collections import Counter
import json
import os
import re
import html
import unicodedata

PASTA = os.path.dirname(os.path.abspath(__file__))
ALVO = os.path.join(PASTA, "monitor_gerado.html")
if not os.path.exists(ALVO):
    ALVO = os.path.join(PASTA, "monitor.html")
NOTICIAS_JSON = os.path.join(PASTA, "noticias.json")

DIAS_NOTICIAS = 30
DIAS_INFORMATIVO = 180   # informativo e material de referencia; guardamos uma janela maior
MAX_NOTICIAS = 120
MAX_INFORMATIVO = 60


def gnews(consulta):
    base = "https://news.google.com/rss/search?"
    return base + urllib.parse.urlencode({"q": consulta, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})


# destino: "informativo" vai para a aba Informativo; "noticias" para a aba Noticias.
# tipo: "stj" = oficial (nunca filtrado por relevancia); "gnews" = imprensa (filtrada).
FONTES = [
    {"tipo": "stj", "destino": "noticias", "fonte": "STJ (Notícias)",
     "url": "http://feeds.feedburner.com/STJNoticias"},
    {"tipo": "stj", "destino": "noticias", "fonte": "STJ (Notícias)",
     "url": "https://res.stj.jus.br/hrestp-c-portalp/RSS.xml"},
    {"tipo": "gnews", "destino": "noticias", "fonte": None, "url": gnews("STJ")},
    {"tipo": "gnews", "destino": "noticias", "fonte": None, "url": gnews('"Superior Tribunal de Justiça"')},
    {"tipo": "gnews", "destino": "noticias", "fonte": None, "url": gnews("STJ site:migalhas.com.br")},
    {"tipo": "gnews", "destino": "noticias", "fonte": None, "url": gnews("STJ site:conjur.com.br")},
    {"tipo": "gnews", "destino": "noticias", "fonte": None, "url": gnews("STJ site:jota.info")},
    {"tipo": "gnews", "destino": "noticias", "fonte": None, "url": gnews("STJ site:valor.globo.com")},
    {"tipo": "gnews", "destino": "noticias", "fonte": None, "url": gnews("STJ site:poder360.com.br")},
]


def sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


CATEGORIAS = [
    ("Audiência pública", ["audiencia publica"]),
    ("Regimento", ["regiment", "emenda regimental", "resolucao", "portaria",
                   "instrucao normativa", "ato normativo", "norma interna", "enunciado administrativo"]),
    ("Julgamento", ["julga", "julgou", "julgament", "decide", "decidiu", "decisao", "mantem", "manteve",
                    "nega", "negou", "condena", "absolve", "fixa tese", "fixou tese", "repetitivo",
                    "sumula", "reconhece", "reconheceu", "valida", "anula", "anulou", "turma",
                    "secao", "corte especial", "relator", "acordao", "tese firmada", " tese ",
                    "provimento", "recurso especial", "habeas corpus", "entende que", "entendeu que"]),
]


def classificar(titulo):
    t = " " + sem_acento(titulo) + " "
    for nome, chaves in CATEGORIAS:
        if any(k in t for k in chaves):
            return nome
    return "Institucional"


def baixar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def limpar_gnews(titulo):
    titulo = html.unescape((titulo or "").strip())
    if " - " in titulo:
        titulo = titulo.rsplit(" - ", 1)[0].strip()
    return titulo


def limpar_resumo(desc, limite=300):
    txt = re.sub(r"<[^>]+>", " ", desc or "")        # tira HTML
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return (txt[:limite] + " […]") if len(txt) > limite else txt


def parse_data(pub):
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def coletar():
    noticias, informativo = [], []
    vistos_n, vistos_i = set(), set()
    limite_n = datetime.now(timezone.utc) - timedelta(days=DIAS_NOTICIAS)
    limite_i = datetime.now(timezone.utc) - timedelta(days=DIAS_INFORMATIVO)
    for fonte in FONTES:
        try:
            raw = baixar(fonte["url"])
            root = ET.fromstring(raw)
        except Exception as e:
            print("  (pulei:", fonte["url"][:48], "->", e, ")")
            continue
        oficial = fonte["tipo"] == "stj"
        for it in root.iter("item"):
            titulo_raw = it.findtext("title") or ""
            link = it.findtext("link") or ""
            pub = it.findtext("pubDate") or ""
            dt = parse_data(pub)

            if fonte["destino"] == "informativo":
                titulo = html.unescape(titulo_raw.strip())
                if not titulo or not link:
                    continue
                if dt is not None and dt < limite_i:
                    continue
                chave = re.sub(r"[^a-z0-9]", "", sem_acento(titulo))[:80]
                if chave in vistos_i:
                    continue
                vistos_i.add(chave)
                informativo.append({
                    "titulo": titulo,
                    "resumo": limpar_resumo(it.findtext("description") or ""),
                    "data": dt.strftime("%d/%m/%Y") if dt else "",
                    "link": link,
                    "_ts": dt.timestamp() if dt else 0,
                })
                continue

            # ---- noticias ----
            if oficial:
                titulo = html.unescape(titulo_raw.strip())
                nome_fonte = fonte["fonte"]
            else:
                titulo = limpar_gnews(titulo_raw)
                src = it.find("source")
                nome_fonte = (src.text if src is not None else "") or "Imprensa"
            if not titulo or not link:
                continue
            if dt is not None and dt < limite_n:
                continue
            categoria = classificar(titulo)
            if not oficial and categoria == "Institucional":
                continue  # corta imprensa irrelevante
            chave = re.sub(r"[^a-z0-9]", "", sem_acento(titulo))[:80]
            if chave in vistos_n:
                continue
            vistos_n.add(chave)
            noticias.append({
                "titulo": titulo, "fonte": nome_fonte, "oficial": oficial,
                "categoria": categoria, "data": dt.strftime("%d/%m/%Y") if dt else "",
                "link": link, "_ts": dt.timestamp() if dt else 0,
            })

    noticias.sort(key=lambda x: x["_ts"], reverse=True)
    informativo.sort(key=lambda x: x["_ts"], reverse=True)
    noticias = noticias[:MAX_NOTICIAS]
    informativo = informativo[:MAX_INFORMATIVO]
    for x in noticias + informativo:
        x.pop("_ts", None)
    return noticias, informativo


def injetar(pagina, nome_const, lista):
    dados_js = (f"const {nome_const} = " + json.dumps(lista, ensure_ascii=False) + ";").replace("</", "<\\/")
    nova = re.sub(r"const " + nome_const + r" = \[.*?\];", lambda m: dados_js, pagina, count=1, flags=re.DOTALL)
    return nova, (nova != pagina)


print("Buscando noticias e informativo do STJ...")
noticias, informativo = coletar()
print(f"Noticias: {len(noticias)}  | por categoria: {dict(Counter(n['categoria'] for n in noticias))}")
print(f"  oficiais STJ: {sum(1 for n in noticias if n['oficial'])} | imprensa: {sum(1 for n in noticias if not n['oficial'])}")
with open(NOTICIAS_JSON, "w", encoding="utf-8") as f:
    json.dump({"noticias": noticias}, f, ensure_ascii=False)

if os.path.exists(ALVO):
    pagina = open(ALVO, encoding="utf-8").read()
    pagina, ok1 = injetar(pagina, "NOTICIAS", noticias)
    if not ok1:
        print("(!) nao encontrei 'const NOTICIAS' na pagina.")
    with open(ALVO, "w", encoding="utf-8") as f:
        f.write(pagina)
    print("Injetado em:", os.path.basename(ALVO))

print("Pronto!")
