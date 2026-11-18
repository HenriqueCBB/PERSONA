"""MEM-01 / R4.1 (CODEX-20261118): bracos de recuperacao SEM modelo de linguagem. CANDIDATO.

Entrada: JSONL de casos sinteticos (formato do persona_r41_benchmark.py: case_id, question, context).
O gabarito fica em arquivo separado e so e lido pelo avaliador (avaliar), nunca pelos bracos.

Bracos:
  A  texto integral + extrator literal (teto de recuperacao, custo maximo em palavras)
  C  indice BM25 sobre fragmentos de N palavras, top-k, + extrator
  D  C + ligacoes tematicas: segue identificadores (XXX-123) achados nos fragmentos para buscar fragmentos ligados
  L* bracos com LLM: interface pronta, marcados PENDENTE (nenhuma chamada de modelo e feita aqui)

O extrator e o MESMO para todos os bracos: a diferenca medida e so a da recuperacao.
Metricas: acerto exato, recall de evidencia (todas as linhas-fato no texto recuperado), palavras entregues.
Somente biblioteca padrao.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict

TOK = re.compile(r"[\wÀ-ÿ]+(?:-[\wÀ-ÿ]+)*", re.UNICODE)
ID_RX = re.compile(r"\b(?:OBJ|PONTE|SETOR)-\d+\b")
FATO_RX = re.compile(r"\[[A-ZÇÃÕÉÊ ]+\][^\[]*?\.(?=\s|$)")


def tokens(s: str) -> list[str]:
    return [t.lower() for t in TOK.findall(s)]


def fragmentos(texto: str, n: int = 40) -> list[str]:
    w = texto.split()
    return [" ".join(w[i:i + n]) for i in range(0, len(w), n)]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.tf = [Counter(tokens(d)) for d in docs]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(docs)
        self.idf = {k: math.log(1 + (n - v + 0.5) / (v + 0.5)) for k, v in df.items()}
        self.k1, self.b = k1, b

    def score(self, q: list[str], i: int) -> float:
        tf, ln, s = self.tf[i], self.len[i], 0.0
        for t in q:
            if t in tf:
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
        return s

    def top(self, query: str, k: int) -> list[int]:
        q = tokens(query)
        ranked = sorted(range(len(self.docs)), key=lambda i: (-self.score(q, i), i))
        return [i for i in ranked[:k] if self.score(q, i) > 0]


# ------------------------- extrator comum (deterministico) -------------------------
def extrair(pergunta: str, texto: str) -> str:
    texto = " ".join(texto.split())  # fragmentos unidos por quebra de linha: normaliza antes de casar fatos
    ent = re.search(r"\b(?:OBJ)-\d+\b", pergunta)
    ent = ent.group(0) if ent else None
    fatos = FATO_RX.findall(texto)
    if "PERMITIDA ou NEGADA" in pergunta:
        geral = [f for f in fatos if f.startswith("[REGRA GERAL]") and ent in f]
        exc = [f for f in fatos if f.startswith("[EXCEÇÃO]") and ent in f]
        est = [f for f in fatos if f.startswith("[ESTADO]") and ent in f]
        if exc and est:
            selo = re.search(r"SETOR-\d+", exc[0])
            if selo and selo.group(0) in est[0]:
                return "PERMITIDA"
        return "NEGADA" if geral else ""
    if "revisão mais recente" in pergunta:
        revs = []
        for f in fatos:
            if ent in f:
                m = re.search(r"revisão (\d+).*?(PX-\d+)", f)
                if m:
                    revs.append((int(m.group(1)), m.group(2)))
        return max(revs)[1] if revs else ""
    for f in fatos:  # fato direto com a entidade
        if ent and ent in f:
            m = re.search(r"PX-\d+", f)
            if m:
                return m.group(0)
            ponte = re.search(r"PONTE-\d+", f)
            if ponte:  # dois saltos dentro do texto entregue
                for g in fatos:
                    if ponte.group(0) in g and g is not f:
                        m2 = re.search(r"PX-\d+", g)
                        if m2:
                            return m2.group(0)
    return ""


# ------------------------------------ bracos ------------------------------------
def braco_A(caso: dict, **_) -> str:
    return caso["context"]


def _vizinho(fr: list[str], sel: set[int]) -> set[int]:
    """Fato cortado na borda: inclui o seguinte (fato comeca aqui e nao termina) e o anterior
    (fragmento traz identificador mas o rotulo [..] do fato ficou no fragmento de tras)."""
    out = set(sel)
    for i in sel:
        if i + 1 < len(fr) and "[" in fr[i] and not fr[i].rstrip().endswith("."):
            out.add(i + 1)
        cabeca = fr[i].split("[", 1)[0]
        if i > 0 and ID_RX.search(cabeca) and "[" in fr[i - 1]:
            out.add(i - 1)
    return out


def braco_C(caso: dict, n: int = 40, k: int = 2, vizinho: bool = False, **_) -> str:
    fr = fragmentos(caso["context"], n)
    sel = set(BM25(fr).top(caso["question"], k))
    if vizinho:
        sel = _vizinho(fr, sel)
    return "\n".join(fr[i] for i in sorted(sel))


def braco_D(caso: dict, n: int = 40, k: int = 2, saltos: int = 1, vizinho: bool = True, **_) -> str:
    fr = fragmentos(caso["context"], n)
    por_id = defaultdict(set)
    for i, f in enumerate(fr):
        for x in ID_RX.findall(f):
            por_id[x].add(i)
    sel = set(BM25(fr).top(caso["question"], k))
    for _ in range(saltos):
        novos = set()
        for i in sel:
            for x in ID_RX.findall(fr[i]):
                novos |= por_id[x]
        sel |= novos
    if vizinho:
        sel = _vizinho(fr, sel)
    return "\n".join(fr[i] for i in sorted(sel))


def braco_llm_pendente(caso: dict, **_) -> str:
    raise NotImplementedError("PENDENTE: braco com LLM exige modelo autorizado e contagem real de tokens pela API")


BRACOS = {
    "A": braco_A,
    "C": braco_C,
    "D": braco_D,
    # controles para atribuir o ganho: so vizinho (sem ligacoes) e so ligacoes (sem vizinho)
    "C+viz": lambda c, **kw: braco_C(c, vizinho=True, **kw),
    "D-viz": lambda c, **kw: braco_D(c, vizinho=False, **kw),
}


def rodar(casos: list[dict], bracos=("A", "C", "D", "C+viz", "D-viz"), **kw) -> list[dict]:
    out = []
    for c in casos:
        for b in bracos:
            texto = BRACOS[b](c, **kw)
            out.append({"case_id": c["case_id"], "architecture": b, "answer": extrair(c["question"], texto),
                        "palavras_entregues": len(texto.split()), "model_id": "sem-llm",
                        "_texto_sha_len": len(texto)})
    return out


def avaliar(respostas: list[dict], gabarito: dict[str, dict], contextos: dict[str, str] | None = None,
            textos: dict[tuple, str] | None = None) -> dict:
    grupos = defaultdict(lambda: {"n": 0, "acertos": 0, "palavras": 0})
    for r in respostas:
        g = gabarito[r["case_id"]]
        k = (r["architecture"], g["length_words"] // 1000 * 1000 or g["length_words"], g["task_class"])
        e = grupos[k]
        e["n"] += 1
        e["acertos"] += int(r["answer"].strip().upper() == g["gold_answer"].strip().upper())
        e["palavras"] += r["palavras_entregues"]
    return {f"{a}|{ln}|{t}": {**v, "acuracia": round(v["acertos"] / v["n"], 4),
                              "palavras_media": round(v["palavras"] / v["n"], 1)}
            for (a, ln, t), v in sorted(grupos.items())}


def recall_evidencia(casos: list[dict], gabarito: dict[str, dict], braco: str, **kw) -> float:
    ok = 0
    for c in casos:
        texto = " ".join(BRACOS[braco](c, **kw).split())
        ok += int(all(" ".join(f.split()) in texto for f in gabarito[c["case_id"]]["evidence_lines"]))
    return ok / max(1, len(casos))


def ler_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]
