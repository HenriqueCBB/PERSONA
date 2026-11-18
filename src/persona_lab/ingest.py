"""AUTOINGEST Fase A (CANDIDATO): toda conversa vira BRUTO + MAPA, sem perder a fonte original.

Fluxo (PRP-PERSONA-AUTOINGEST-CONVERSAS-20261118-001):
  1. arquivar(): bruto JSONL (1 mensagem por linha, ordem, papel, texto) -> arquivo so-acrescimo + manifesto
  2. extrair_capsula(): bloco <<<CAPSULA {json} CAPSULA>>> escrito pela IA ao fechar a sessao
  3. mapa_conversa(): nos candidatos com ponteiro para message_id (link reversivel), P0 e quarentena de injecao
  4. reconciliar(): propostas (criar, nova_versao, contradicao, substituicao, confirmacao) - NUNCA edita o oficial
  5. checkpoint: PENDING | PARTIAL | VERIFIED | FAILED, ultimo turno, hashes, proxima acao

Captura automatica universal NAO existe nas apps de consumo: isto e a fase assistida
(a IA gera bruto visivel + capsula; o script processa). Somente biblioteca padrao.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager

from persona_lab.p0_gate import checar

PAPEIS = {"titular", "ia", "sistema", "ferramenta"}
TIPOS_MSG = {"texto", "voz_transcrita", "imagem", "arquivo", "ausente"}
STATUS = ("PENDING", "PARTIAL", "VERIFIED", "FAILED")
CAPSULA_RX = re.compile(r"<<<CAPSULA\s*(\{.*?\})\s*CAPSULA>>>", re.DOTALL)
P0_ORDEM = ("PUB", "INT", "PRIV", "REST", "COFRE")
REL_RX = re.compile(r"^(cria|atualiza|contradiz|substitui|confirma)(?::([A-Z][A-Z0-9_.-]{1,40}))?$")


class IngestError(ValueError):
    pass


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@contextmanager
def trava(pasta: str, tentativas: int = 200, espera: float = 0.01):
    """Um escritor por vez (T04). O_EXCL garante exclusividade; espera limitada, depois falha (fail-closed)."""
    import time
    caminho = os.path.join(pasta, ".trava")
    for _ in range(tentativas):
        try:
            fd = os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(espera)
    else:
        raise FileExistsError(f"TRAVA_OCUPADA {caminho}")
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        os.unlink(caminho)


def _grava_atomico(path: str, dados: bytes) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "wb") as fh:
        fh.write(dados)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def ler_bruto(path: str) -> list[dict]:
    msgs = []
    with open(path, encoding="utf-8") as fh:
        for n, linha in enumerate(fh, 1):
            if linha.strip():
                try:
                    msgs.append(json.loads(linha))
                except ValueError as exc:
                    raise IngestError(f"LINHA_INVALIDA {n}") from exc
    return msgs


def validar_bruto(msgs: list[dict]) -> dict:
    """T01 ordem/integridade e T02 lacunas multimodais."""
    if not msgs:
        raise IngestError("BRUTO_VAZIO")
    conversas = {m.get("conversa") for m in msgs}
    if len(conversas) != 1 or None in conversas:
        raise IngestError("CONVERSA_INCONSISTENTE")
    vistos, ultimo, lacunas = set(), 0, []
    for m in msgs:
        if m.get("papel") not in PAPEIS or m.get("tipo", "texto") not in TIPOS_MSG:
            raise IngestError(f"CAMPO_INVALIDO {m.get('msg')}")
        if m.get("msg") in vistos:
            raise IngestError(f"MSG_DUPLICADA {m.get('msg')}")
        if not isinstance(m.get("ordem"), int) or m["ordem"] <= ultimo:
            raise IngestError(f"FORA_DE_ORDEM {m.get('msg')}")
        if m["ordem"] != ultimo + 1:
            lacunas.append(f"salto {ultimo}->{m['ordem']}")
        if m.get("tipo") in ("ausente", "imagem", "arquivo") and not m.get("texto"):
            lacunas.append(f"sem_texto {m['msg']}:{m.get('tipo')}")
        vistos.add(m["msg"])
        ultimo = m["ordem"]
    return {"conversa": msgs[0]["conversa"], "n": len(msgs), "ultimo": msgs[-1]["msg"], "lacunas": lacunas}


def arquivar(bruto_path: str | None, pasta: str) -> dict:
    """Copia so-acrescimo do bruto. Mesmo conteudo = no-op (idempotente). Conteudo novo = nova versao
    (nunca sobrescreve). Bruto indisponivel = FAILED (T09: nunca VERIFIED sem fonte)."""
    os.makedirs(pasta, exist_ok=True)
    man_path = os.path.join(pasta, "MANIFESTO.jsonl")
    if not bruto_path or not os.path.exists(bruto_path):
        reg = {"conversa": None, "status": "FAILED", "motivo": "BRUTO_INDISPONIVEL", "arquivo": bruto_path}
        with open(man_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
        return reg
    with open(bruto_path, "rb") as fh:
        dados = fh.read()
    info = validar_bruto(ler_bruto(bruto_path))
    h = sha256_bytes(dados)
    seguro = re.sub(r"[^A-Za-z0-9_.-]", "_", info["conversa"])
    with trava(pasta):
        anteriores = []
        if os.path.exists(man_path):
            with open(man_path, encoding="utf-8") as fh:
                anteriores = [json.loads(x) for x in fh if x.strip()]
        mesmos = [a for a in anteriores if a.get("conversa") == info["conversa"] and a.get("status") != "FAILED"]
        if any(a["sha256"] == h for a in mesmos):
            return {**next(a for a in mesmos if a["sha256"] == h), "idempotente": True}
        versao = len(mesmos) + 1
        destino = os.path.join(pasta, f"{seguro}__v{versao}.jsonl")
        _grava_atomico(destino, dados)
        with open(destino, "rb") as fh:  # leitura de volta (PREF-07)
            if sha256_bytes(fh.read()) != h:
                raise IngestError("LEITURA_DE_VOLTA_DIVERGIU")
        status = "PARTIAL" if info["lacunas"] else "VERIFIED"
        reg = {"conversa": info["conversa"], "versao": versao, "arquivo": os.path.basename(destino), "sha256": h,
               "bytes": len(dados), "n_msgs": info["n"], "ultimo_msg": info["ultimo"], "lacunas": info["lacunas"],
               "status": status}
        with open(man_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
        return reg


def extrair_capsula(texto: str) -> dict:
    m = CAPSULA_RX.search(texto or "")
    if not m:
        raise IngestError("CAPSULA_AUSENTE")
    try:
        cap = json.loads(m.group(1))
    except ValueError as exc:
        raise IngestError("CAPSULA_JSON_INVALIDO") from exc
    if cap.get("formato") != "persona-capsula-1" or not isinstance(cap.get("nos"), list):
        raise IngestError("CAPSULA_FORMATO")
    return cap


def _id_no(conversa: str, n: dict) -> str:
    base = f"{conversa}\x1f{'|'.join(n.get('msgs', []))}\x1f{n.get('titulo', '')}"
    return "CV-" + sha256_bytes(base.encode())[:10].upper()


def mapa_conversa(capsula: dict, msgs: list[dict]) -> dict:
    """Nos candidatos com link reversivel (T05) e quarentena de injecao (T08)."""
    info = validar_bruto(msgs)
    if capsula.get("conversa") != info["conversa"]:
        raise IngestError("CAPSULA_DE_OUTRA_CONVERSA")
    por_id = {m["msg"]: m for m in msgs}
    alias = "CV" + sha256_bytes(info["conversa"].encode())[:8].upper()
    fonte = {"id": "F-" + alias, "tipo": "fonte", "natureza": "referencia", "titulo": f"Conversa {info['conversa']}",
             "texto": "", "p0": capsula.get("p0_bruto", "PRIV"), "alias": alias, "visoes": [], "supernos": [],
             "lentes": [], "fontes": [], "aponta": [], "estado": "candidato", "evidencia": "verificada",
             "vigencia": "ativa", "drive_id": capsula.get("drive_id_bruto", "")}
    nos, quarentena, rejeitados = [], [], []
    for n in capsula["nos"]:
        faltam = [x for x in n.get("msgs", []) if x not in por_id]
        if not n.get("msgs") or faltam:
            rejeitados.append({"titulo": n.get("titulo"), "motivo": f"PONTEIRO_SEM_MENSAGEM {faltam or 'vazio'}"})
            continue
        rel = REL_RX.match(n.get("relacao", "cria"))
        if not rel:
            rejeitados.append({"titulo": n.get("titulo"), "motivo": "RELACAO_INVALIDA"})
            continue
        trecho = " ".join(por_id[x].get("texto", "") for x in n["msgs"])
        achados = {a["tipo"] for a in checar(n.get("texto", "") + "\n" + n.get("titulo", ""))}
        injecao_fonte = {a["tipo"] for a in checar(trecho) if a["tipo"].startswith("INJ_")}
        p0 = n.get("p0", "PRIV")
        if achados - {a for a in achados if a.startswith("INJ_")} and p0 in ("PUB", "INT"):
            p0 = "PRIV"  # identificador detectado no texto do no: sobe a classe (fail-closed)
        natureza = n.get("natureza") or {"decisao": "decisao", "preferencia": "preferencia", "tarefa": "tarefa",
                                         "evento": "evento", "restricao": "regra"}.get(n.get("tipo"), "fato")
        no = {"id": _id_no(info["conversa"], n), "tipo": n.get("tipo", "afirmacao"), "natureza": natureza,
              "titulo": n.get("titulo", "")[:90], "texto": n.get("texto", "")[:420], "p0": p0,
              "visoes": n.get("visoes", ["M3"]), "supernos": n.get("supernos", []), "lentes": n.get("lentes", []),
              "fontes": [alias], "aponta": [], "estado": "candidato",
              "evidencia": n.get("evidencia", "declarada"), "vigencia": "ativa",
              "msgs": n["msgs"], "relacao": rel.group(1), "alvo": rel.group(2),
              "origem": info["conversa"], "aprovado": False}
        if no["tipo"] == "preferencia" and not n.get("duravel"):
            no["natureza"] = "preferencia"
            no["circunstancial"] = True  # nao vira preferencia duravel sem confirmacao explicita do titular
        if P0_ORDEM.index(no["p0"]) < P0_ORDEM.index(fonte["p0"]):
            # no compartilhavel extraido de bruto mais restrito: so com sanitizacao declarada (aresta deriva_de),
            # nunca por citacao direta; o texto ja passou pelo gate (identificador detectado = classe sobe)
            no["fontes"] = []
            no["sanitizado_de"] = fonte["id"]
        if injecao_fonte or {a for a in achados if a.startswith("INJ_")}:
            no["estado"] = "quarentena"
            no["motivo_quarentena"] = sorted(injecao_fonte | {a for a in achados if a.startswith("INJ_")})
            quarentena.append(no["id"])
        nos.append(no)
    # N1 (taxa de uso util): o que foi aberto na sessao e o que de fato sustentou a resposta (com ponteiro)
    consultados = sorted(set(capsula.get("consultados", [])))
    aproveitados = sorted({a["alias"] for a in capsula.get("aproveitados", [])
                           if isinstance(a, dict) and a.get("msg") in por_id and a.get("alias") in consultados})
    uso = {a: {"consultas": 1, "aproveitamentos": int(a in aproveitados)} for a in consultados}
    return {"conversa": info["conversa"], "fonte": fonte, "nos": nos, "quarentena": quarentena, "uso": uso,
            "rejeitados": rejeitados, "tarefas": capsula.get("tarefas", []), "pendencias": capsula.get("pendencias", [])}


def reconciliar(registro: dict, mapa: dict) -> dict:
    """Propostas de delta. O oficial nunca muda aqui: nova_versao cria no novo + aresta substitui (T06)."""
    ids = {n["id"]: n for n in registro.get("nos", [])}
    ops = []
    for n in mapa["nos"]:
        if n["id"] in ids:
            ops.append({"op": "nenhuma", "no": n["id"], "motivo": "ja_registrado"})  # idempotente (T03/T04)
            continue
        if n["estado"] == "quarentena":
            ops.append({"op": "quarentena", "no": n["id"], "motivo": n.get("motivo_quarentena")})
            continue
        alvo = n.get("alvo")
        if n["relacao"] != "cria" and alvo not in ids:
            ops.append({"op": "rejeitar", "no": n["id"], "motivo": f"ALVO_INEXISTENTE {alvo}"})
            continue
        if n["relacao"] in ("atualiza", "substitui") and ids[alvo]["tipo"] != n["tipo"]:
            ops.append({"op": "rejeitar", "no": n["id"], "motivo": f"TIPO_DIVERGENTE {n['tipo']}!={ids[alvo]['tipo']}"})
            continue
        if n["relacao"] == "cria":
            ops.append({"op": "criar", "no": n["id"]})
        elif n["relacao"] == "atualiza":
            ops.append({"op": "nova_versao", "no": n["id"], "aresta": {"tipo": "substitui", "de": n["id"], "para": alvo,
                                                                       "motivo": "revisao"}})
        elif n["relacao"] == "substitui":
            ops.append({"op": "substituicao", "no": n["id"], "aresta": {"tipo": "substitui", "de": n["id"],
                                                                        "para": alvo, "motivo": "correcao"}})
        elif n["relacao"] == "contradiz":
            ops.append({"op": "contradicao", "no": n["id"], "aresta": {"tipo": "contradiz", "de": n["id"], "para": alvo},
                        "revisar": [alvo]})
        else:
            ops.append({"op": "confirmacao", "no": n["id"], "aresta": {"tipo": "sustenta", "de": n["id"], "para": alvo}})
    return {"conversa": mapa["conversa"], "operacoes": ops,
            "aprovacao": "titular aprova promocao; ate la tudo e candidato"}


def aplicar_candidatos(registro: dict, mapa: dict, delta: dict) -> dict:
    """Aplica so o que vira CANDIDATO (nunca oficial). Devolve novo registro; o original fica intacto."""
    novo = json.loads(json.dumps(registro))
    ids = {n["id"] for n in novo["nos"]}
    if mapa["fonte"]["id"] not in ids:
        novo["nos"].append(mapa["fonte"])
    por_alias = {n.get("alias"): n for n in novo["nos"] if n.get("alias")}
    for a, u in mapa.get("uso", {}).items():  # acumula uso por fonte; uma vez por conversa (idempotente)
        n = por_alias.get(a)
        if n is None or mapa["conversa"] in n.get("uso_conversas", []):
            continue
        n["uso_conversas"] = n.get("uso_conversas", []) + [mapa["conversa"]]
        n["uso_consultas"] = n.get("uso_consultas", 0) + u["consultas"]
        n["uso_aproveitamentos"] = n.get("uso_aproveitamentos", 0) + u["aproveitamentos"]
    por_id = {n["id"]: n for n in mapa["nos"]}
    extras = ("msgs", "relacao", "alvo", "circunstancial", "motivo_quarentena", "sanitizado_de")
    for op in delta["operacoes"]:
        if op["op"] in ("criar", "nova_versao", "substituicao", "contradicao", "confirmacao") and op["no"] not in ids:
            origem = por_id[op["no"]]
            n = {k: v for k, v in origem.items() if k not in extras}
            novo["nos"].append(n)
            if origem.get("sanitizado_de"):
                novo.setdefault("arestas", []).append({"tipo": "deriva_de", "de": n["id"], "para": origem["sanitizado_de"],
                                                       "transformacao": "sanitizacao", "msgs": origem["msgs"]})
            if "aresta" in op:
                novo.setdefault("arestas", []).append(op["aresta"])
    return novo


def checkpoint(arquivo_reg: dict, mapa: dict | None, delta: dict | None) -> dict:
    status = arquivo_reg.get("status", "FAILED")
    if mapa is None or delta is None:
        status = "FAILED" if status == "FAILED" else "PENDING"
    elif mapa["quarentena"] or mapa["rejeitados"]:
        status = "PARTIAL" if status != "FAILED" else "FAILED"
    return {"conversa": arquivo_reg.get("conversa"), "status": status, "ultimo_msg": arquivo_reg.get("ultimo_msg"),
            "sha256_bruto": arquivo_reg.get("sha256"),
            "mapa_sha256": sha256_bytes(json.dumps(mapa, sort_keys=True, ensure_ascii=False).encode()) if mapa else None,
            "proxima_acao": {"VERIFIED": "titular revisa propostas", "PARTIAL": "resolver lacunas/quarentena",
                             "PENDING": "gerar capsula", "FAILED": "obter bruto"}[status]}


def inventario(pasta: str) -> dict:
    """T10: cobertura por plataforma a partir do manifesto."""
    man = os.path.join(pasta, "MANIFESTO.jsonl")
    out = {}
    if not os.path.exists(man):
        return out
    with open(man, encoding="utf-8") as fh:
        for linha in fh:
            r = json.loads(linha)
            plat = (r.get("conversa") or "desconhecida:").split(":")[0]
            d = out.setdefault(plat, {"conversas": set(), "VERIFIED": 0, "PARTIAL": 0, "FAILED": 0})
            if r.get("conversa"):
                d["conversas"].add(r["conversa"])
            d[r["status"]] = d.get(r["status"], 0) + 1
    return {k: {**v, "conversas": len(v["conversas"])} for k, v in out.items()}
