# -*- coding: utf-8 -*-
# COLETOR STJ - Fase 1 (o motor do "o que mudou").
# A cada vez que roda: baixa a base de precedentes, corrige e organiza,
# compara com a foto da ultima vez e gera 'relatorio.txt' com os novos e os
# que mudaram. Na primeira vez, so guarda a foto inicial.

import pandas as pd
import urllib.request
import io, json, os, re, unicodedata
from collections import Counter
from datetime import datetime

URL_TEMAS = ("https://dadosabertos.web.stj.jus.br/dataset/"
             "4238da2f-c07b-4c1a-b345-4402accacdcf/resource/"
             "df29da13-7d6b-41ba-ad96-cd1a5bbd191c/download/temas.csv")

PASTA = os.path.dirname(os.path.abspath(__file__))
FOTO = os.path.join(PASTA, "foto_anterior.json")      # a foto da ultima rodada
ATUAL = os.path.join(PASTA, "temas_atual.json")        # a base de hoje (para a tela, no futuro)
RELATORIO = os.path.join(PASTA, "relatorio.txt")       # o resumo legivel para voce
TEMPLATE = os.path.join(PASTA, "monitor.html")         # a casca (modelo da tela)
SAIDA_HTML = os.path.join(PASTA, "monitor_gerado.html")# a tela final, ja com os dados reais

ORGAOS = {"S1": "1ª Seção", "S2": "2ª Seção", "S3": "3ª Seção", "CE": "Corte Especial", "": "(sem órgão)"}


def sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower().strip()


def bucket_situacao(s):
    x = sem_acento(s)
    if not x:
        return "(vazio)"
    if any(k in x for k in ["transito em julgado", "acordao publicado", "merito julgado", "revisado"]):
        return "Julgado"
    if any(k in x for k in ["afetad", "admitido", "pendente", "em julgamento", "sobrestad"]):
        return "Aguardando julgamento"
    if any(k in x for k in ["cancelad", "prejudicad"]):
        return "Cancelado/Prejudicado"
    if "vinculada a tema" in x:
        return "Vinculada a tema"
    if "suspens" in x:
        return "Suspensão (SIRDR)"
    return "Outros"


def tipo_amigavel(t):
    return "Tema Repetitivo" if t.strip() == "Tema" else t.strip()


# ---------- baixar ----------
print("Baixando a base de precedentes do STJ... (alguns segundos)")
req = urllib.request.Request(URL_TEMAS, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=180) as r:
    bruto = r.read()

texto, usada = None, None
for enc in ("utf-8", "cp1252", "latin-1"):
    try:
        texto = bruto.decode(enc)
        usada = enc
        break
    except UnicodeDecodeError:
        continue
print(f"Baixado: {len(bruto)} bytes | codificacao: {usada}")

cab = texto.splitlines()[0]
sep = max({";": cab.count(";"), ",": cab.count(","), "\t": cab.count("\t")}.items(),
          key=lambda kv: kv[1])[0]
df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, engine="python", on_bad_lines="skip").fillna("")


# ---------- organizar em registros ----------
def g(row, col):
    return str(row[col]).strip() if col in df.columns else ""


agora = {}
for _, row in df.iterrows():
    seq = g(row, "sequencialPrecedente")
    if not seq:
        continue
    cod = g(row, "orgaoJulgador")
    agora[seq] = {
        "seq": seq,
        "tipo": tipo_amigavel(g(row, "tipoPrecedente")),
        "numero": g(row, "numeroPrecedente"),
        "orgao": ORGAOS.get(cod, cod or "(sem órgão)"),
        "situacao": g(row, "situacao"),
        "bucket": bucket_situacao(g(row, "situacao")),
        "afetacao": g(row, "dataPrimeiraAfetacao"),
        "julgamento": g(row, "dataJulgamento"),
        "publicacao": g(row, "dataPublicacaoAcordao"),
        "questao": g(row, "questaoSubmetidaAJulgamento"),
        "tese": g(row, "teseFirmada"),
        "assuntos": g(row, "Assuntos"),
        "rgstf": g(row, "numeroRepercussaoGeralSTF"),
    }

with open(ATUAL, "w", encoding="utf-8") as f:
    json.dump(list(agora.values()), f, ensure_ascii=False)


# ---------- comparar com a foto anterior ----------
primeira_vez = not os.path.exists(FOTO)
novos, mudancas = [], []
if not primeira_vez:
    with open(FOTO, "r", encoding="utf-8") as f:
        antes = {r["seq"]: r for r in json.load(f)}
    for seq, rec in agora.items():
        if seq not in antes:
            novos.append(rec)
            continue
        a = antes[seq]
        difs = []
        for c in ["situacao", "tese", "julgamento", "publicacao"]:
            if a.get(c, "") != rec.get(c, ""):
                if c == "tese":
                    difs.append("tese: passou a ter texto" if not a.get(c) else "tese: alterada")
                else:
                    difs.append(f"{c}: {(a.get(c) or '(vazio)')[:50]} -> {(rec.get(c) or '(vazio)')[:50]}")
        if difs:
            mudancas.append((rec, difs))


# ---------- montar o relatorio legivel ----------
L = []
L.append("RELATORIO DO COLETOR STJ  -  " + datetime.now().strftime("%d/%m/%Y %H:%M"))
L.append("codificacao: %s | separador: %r | total: %d precedentes | %d colunas"
         % (usada, sep, len(agora), len(df.columns)))
L.append("")

L.append("== POR TIPO ==")
for t, n in Counter(r["tipo"] for r in agora.values()).most_common():
    L.append(f"  {t}: {n}")

L.append("\n== POR SITUACAO (agrupada) ==")
for b, n in Counter(r["bucket"] for r in agora.values()).most_common():
    L.append(f"  {b}: {n}")

L.append("\n== POR ORGAO ==")
for o, n in Counter(r["orgao"] for r in agora.values()).most_common():
    L.append(f"  {o}: {n}")

L.append("")
if primeira_vez:
    L.append("== PRIMEIRA RODADA ==")
    L.append("Esta e a foto inicial; nao ha com o que comparar ainda.")
    L.append("Rode de novo depois (dias depois) e eu mostro aqui os NOVOS e os que MUDARAM.")
else:
    L.append("== NOVOS desde a ultima rodada: %d ==" % len(novos))
    for r in novos[:60]:
        L.append(f"  [{r['tipo']}] {r['numero']} | {r['orgao']} | {r['bucket']}")
    L.append("\n== MUDARAM desde a ultima rodada: %d ==" % len(mudancas))
    for r, difs in mudancas[:60]:
        L.append(f"  [{r['tipo']}] {r['numero']} | {r['orgao']}")
        for d in difs:
            L.append("        - " + d)

L.append("\n== 2 EXEMPLOS REAIS (para conferirmos o conteudo) ==")
def exemplo(tp):
    for r in agora.values():
        if r["tipo"] == tp and r["questao"]:
            return r
    return None
for alvo in ["Tema Repetitivo", "Controvérsia"]:
    r = exemplo(alvo)
    if r:
        L.append("")
        L.append(f"[{r['tipo']}] {r['numero']}  ({r['orgao']})")
        L.append(f"  situacao: {r['situacao']}  (grupo: {r['bucket']})")
        L.append(f"  datas -> afetacao: {r['afetacao'] or '-'} | julgamento: {r['julgamento'] or '-'} | publicacao: {r['publicacao'] or '-'}")
        L.append(f"  assuntos: {r['assuntos'][:200] or '-'}")
        L.append(f"  RG/STF: {r['rgstf'] or '-'}")
        L.append(f"  QUESTAO: {r['questao'][:500]}")
        L.append(f"  TESE: {r['tese'][:500] or '(ainda sem tese)'}")

# ---------- salvar a nova foto (vira a 'anterior' da proxima vez) ----------
with open(FOTO, "w", encoding="utf-8") as f:
    json.dump(list(agora.values()), f, ensure_ascii=False)

with open(RELATORIO, "w", encoding="utf-8") as f:
    f.write("\n".join(L))


# ---------- gerar a TELA (monitor_gerado.html) ja com os dados reais ----------
TOKEN = {"Julgado": "julgado", "Aguardando julgamento": "afetado",
         "Cancelado/Prejudicado": "cancelado", "Revisado": "revisado"}
CURTO = {"Tema Repetitivo": "Tema"}
seqs_novos = {r["seq"] for r in novos}
seqs_mud = {r["seq"] for r, _ in mudancas}

def fmt_num(n):
    n = n.strip()
    try:
        return f"{int(n):,}".replace(",", ".")
    except ValueError:
        return n

STOP = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os", "na", "no",
        "nas", "nos", "à", "ao", "aos", "às", "com", "para", "por", "sob", "sobre", "ou"}

def titulo(s):
    # Converte so os assuntos que vem TODOS EM MAIUSCULAS para Caixa de Titulo,
    # mantendo preposicoes em minusculo. Os que ja vem em caixa mista ficam intactos.
    if not s.isupper():
        return s
    out = []
    for i, w in enumerate(s.lower().split()):
        out.append(w if (i > 0 and w in STOP) else w.capitalize())
    return " ".join(out)

def split_assuntos(s):
    # Assuntos reais vem assim: "8826- DIREITO ..., 8867- Substituicao ...".
    # Tira o codigo do CNJ ("8826- "), separa por virgula e arruma a caixa.
    out = []
    for p in s.split(","):
        p = re.sub(r"^\s*\d+\s*-\s*", "", p).strip()
        if p:
            out.append(titulo(p))
    return out[:6]


# Sinais de texto de ALTA precisao. So entram em acao quando o CNJ etiquetou o
# tema apenas como o generico "Direito Civil" (ou nao etiquetou ramo nenhum) -
# que e justamente onde caem os temas mal classificados na origem. Se a base ja
# deu uma area especifica (Penal, Previdenciario...), confiamos nela.
SINAIS_AREA = [
    ("Direito Tributário", ["tribut", " ctn", "codigo tributario", "credito tributario",
        "divida ativa", "execucao fiscal", " icms", " issqn", " ipi ", " pis ", "cofins",
        " iptu", " itbi", " itcmd", " iof", "imposto de renda", "imposto sobre",
        "contribuicao previdenciaria", "contribuicao social", "isencao fiscal", "creditamento"]),
    ("Direito Penal", ["direito penal", "execucao penal", "trafico", "dosimetria",
        "regime prisional", "reincidencia", " crime", "delito", "habeas corpus"]),
    ("Direito Previdenciário", [" inss", "aposentadoria", "beneficio por incapacidade",
        "auxilio-doenca", "auxilio por incapacidade", "pensao por morte",
        "beneficio assistencial", " loas", "salario-maternidade"]),
    ("Direito do Consumidor", ["consumidor", "relacao de consumo", "codigo de defesa do consumidor"]),
    ("Direito do Trabalho", ["trabalhista", " clt ", "verbas rescisorias", "vinculo empregaticio", " fgts"]),
    ("Direito Administrativo e Outras Matérias de Direito Público",
        ["improbidade", "licitacao", "servidor publico", "concurso publico", "desapropriacao"]),
]

GENERICOS = {"Direito Civil", "(sem classificação)"}


def _ramo_cnj(s):
    # O "ramo do direito" (DIREITO CIVIL, DIREITO TRIBUTARIO, ...) vem em CAIXA
    # ALTA na lista de assuntos, mas NEM SEMPRE na primeira posicao (as vezes
    # aparece no fim). Pega o primeiro trecho em maiuscula que comeca com DIREITO.
    for p in s.split(","):
        p = re.sub(r"^\s*\d+\s*-\s*", "", p).strip()
        if p and p == p.upper() and sem_acento(p).startswith("direito"):
            return titulo(p)
    return "(sem classificação)"


def categoria(assuntos, questao=""):
    ramo = _ramo_cnj(assuntos)
    if ramo in GENERICOS:
        texto = " " + sem_acento((questao or "") + " " + assuntos) + " "
        for area, chaves in SINAIS_AREA:
            if any(k in texto for k in chaves):
                return area
    return ramo

def fmt_data(d):
    # 2008-10-10 -> 10/10/2008
    d = d.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", d)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else d

tela = []
for seq, rec in agora.items():
    curto = CURTO.get(rec["tipo"], rec["tipo"])
    flag = "novo" if seq in seqs_novos else ("mud" if seq in seqs_mud else "")
    tela.append({
        "seq": rec["seq"],
        "num": (curto + " " + fmt_num(rec["numero"])).strip(),
        "tipo": rec["tipo"],
        "orgao": rec["orgao"],
        "situacao": TOKEN.get(rec["bucket"], rec["bucket"]),
        "flag": flag,
        "afet": fmt_data(rec["afetacao"]),
        "julg": fmt_data(rec["julgamento"]),
        "q": rec["questao"],
        "tese": rec["tese"],
        "cat": categoria(rec["assuntos"], rec["questao"]),
        "assuntos": split_assuntos(rec["assuntos"]),
    })

tela_ok = os.path.exists(TEMPLATE)
if tela_ok:
    html = open(TEMPLATE, encoding="utf-8").read()
    dados_js = "const DADOS = " + json.dumps(tela, ensure_ascii=False) + ";"
    dados_js = dados_js.replace("</", "<\\/")
    html = re.sub(r"const DADOS = \[.*?\];", lambda m: dados_js, html, count=1, flags=re.DOTALL)
    hoje = datetime.now().strftime("%d/%m/%Y")
    html = html.replace(
        "⚠ Dados de exemplo, só para desenhar o visual. A versão real é alimentada pelo coletor que lê a base oficial do STJ.",
        f"✓ Dados reais da base oficial do STJ · {len(tela)} precedentes · atualizado em {hoje}")
    html = html.replace("atualizado 03/10/2026", "atualizado " + hoje)
    with open(SAIDA_HTML, "w", encoding="utf-8") as f:
        f.write(html)

print("\nPronto!")
print(" - relatorio.txt         : resumo das contagens e do que mudou  (me mande este)")
if tela_ok:
    print(" - monitor_gerado.html   : a TELA com os %d precedentes reais  (de dois cliques para abrir)" % len(tela))
else:
    print(" - (!) nao achei 'monitor.html' na pasta. Baixe-o junto para eu gerar a tela.")
