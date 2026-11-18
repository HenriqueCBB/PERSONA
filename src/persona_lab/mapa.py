"""MAPA-1 (CANDIDATO): registro unico do mapa mental -> mapas compilados com teto de tokens.

Principio: o mapa NAO e escrito a mao em varios documentos (isso gerou 4 mapas e 3 bootstraps
concorrentes). Existe UM registro (nos + arestas + fontes) e os mapas sao VISTAS compiladas dele:

  Mapas de leitura (entram no contexto; teto de tokens verificado):
    M1 CONTEXTO  - onde estou: estado oficial, o que mudou, tarefas, decisoes pendentes, revisar primeiro
    M2 REGRAS    - como agir: nucleo, niveis RAE, gatilhos, erros proibidos, P0, preferencias ativas
    M3 CONTEUDO  - o que sei e onde esta: supernos (topo) e temas (desce sob demanda)
    M4 CRUZAMENTO- o que liga areas distantes: lentes x supernos, pontes, lacunas (so em pergunta aberta)
  Mapa de consulta (nao entra no contexto; abre-se o item exato):
    M5 ENDERECOS - apelido curto -> ID real da fonte, classe P0, estado
  Pacote de partida = M2 + M1 + M3 topo (um arquivo so).

Cruzamento entre mapas: SOMENTE por ID/apelido. Cada coisa existe uma vez no registro.
Filtro P0 por consumidor: claude/chatgpt (privado), gemini (so com codificacao), externo (so PUB + gate).
Somente biblioteca padrao (tiktoken opcional para contar tokens).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

TIPOS = ("fonte", "artefato", "afirmacao", "decisao", "preferencia", "restricao", "evento", "tarefa")
# Migracao (OP2-C1): nomes antigos -> tipo efetivo. 'hypothesis' vira afirmacao com natureza=hipotese.
MIGRACAO = {"claim": ("afirmacao", None), "hypothesis": ("afirmacao", "hipotese"), "decision": ("decisao", None),
            "preference": ("preferencia", None), "constraint": ("restricao", None), "event": ("evento", None),
            "FONTE": ("fonte", None), "AFIRMACAO": ("afirmacao", None), "DECISAO": ("decisao", None),
            "TAREFA": ("tarefa", None), "ARTEFATO": ("artefato", None)}
NATUREZAS = {"fato", "hipotese", "regra", "roteamento", "proibicao", "procedimento", "preferencia", "decisao",
             "referencia", "tarefa", "evento", "estado", "sintese"}
ESTADOS = {"oficial", "candidato", "laboratorio", "superado", "quarentena"}
EVIDENCIAS = {"verificada", "calculada", "declarada", "relatada", "hipotetica", "contestada"}
VIGENCIAS = {"ativa", "substituida", "revogada", "suspensa"}
P0 = ("PUB", "INT", "PRIV", "REST", "COFRE")  # ordem crescente de restricao
SUPERNOS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
LENTES = ("L1", "L2", "L3", "L4")
VISOES = ("M1", "M2", "M3", "M4")

# 8 arestas com dominio e contradominio (OP2 anexo A, corrigido: pertencimento a superno e ATRIBUTO,
# nao aresta; 'ponte' e a ligacao tipada entre supernos diferentes, exigida pelo M4).
ARESTAS = {
    "deriva_de": ({"afirmacao", "artefato", "decisao", "preferencia", "restricao"}, {"fonte", "artefato"}),
    "sustenta": ({"fonte", "afirmacao", "evento"}, {"afirmacao", "decisao"}),
    "contradiz": ({"fonte", "afirmacao", "evento"}, {"afirmacao", "decisao", "preferencia"}),
    "depende_de": ({"tarefa", "decisao"}, {"tarefa", "decisao", "restricao"}),
    "substitui": (set(TIPOS), set(TIPOS)),  # mesmo tipo; motivo obrigatorio
    "avaliado_por": (set(TIPOS), {"evento"}),
    "relacionado_a": ({"afirmacao", "fonte"}, {"afirmacao", "fonte"}),  # provisoria; fora da recuperacao obrigatoria
    "ponte": ({"afirmacao", "decisao", "artefato", "restricao"}, {"afirmacao", "decisao", "artefato", "restricao"}),
}
MOTIVOS_SUBSTITUI = {"correcao", "revisao", "revogacao"}
# Unicas transformacoes que permitem classe P0 menor que a da origem: declaradas e auditaveis (o gate confere o texto).
TRANSFORMACOES_SEGURAS = {"anonimizacao", "sanitizacao"}
RESULTADOS = {"valida", "invalida", "inconclusivo"}
ID_RX = re.compile(r"^[A-Z][A-Z0-9_.-]{1,40}$")
ALIAS_RX = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
TETOS = {"M1": 450, "M2": 900, "M3": 700, "M3_TEMA": 500, "M4": 650, "PACOTE": 2000}


class RegistroError(ValueError):
    pass


def _tok():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return lambda s: len(enc.encode(s)), "o200k_base"
    except Exception:  # noqa: BLE001 - sem tiktoken: estimativa conservadora
        return lambda s: (len(s) + 2) // 3, "chars/3"


contar_tokens, TOKENIZADOR = _tok()


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ----------------------------------------------------------------------------------- validacao
def validar(reg: dict) -> dict:
    """Erros bloqueiam; avisos vao para a fila de revisao. Devolve {'erros': [...], 'avisos': [...]}."""
    erros, avisos = [], []
    nos = reg.get("nos", [])
    idx = {}
    alias = {}
    for n in nos:
        nid = n.get("id", "")
        if not ID_RX.match(nid):
            erros.append(f"ID_INVALIDO {nid!r}")
        if nid in idx:
            erros.append(f"ID_DUPLICADO {nid}")
        idx[nid] = n
        if n.get("tipo") not in TIPOS:
            erros.append(f"TIPO_INVALIDO {nid}:{n.get('tipo')}")
        for campo, dom in (("estado", ESTADOS), ("evidencia", EVIDENCIAS), ("vigencia", VIGENCIAS)):
            if n.get(campo) not in dom:
                erros.append(f"{campo.upper()}_INVALIDO {nid}:{n.get(campo)}")
        if n.get("natureza") not in NATUREZAS:
            erros.append(f"NATUREZA_INVALIDA {nid}:{n.get('natureza')}")
        if n.get("p0") not in P0:
            erros.append(f"P0_AUSENTE {nid}")  # fail-closed: sem classe nao compila
        if any(s not in SUPERNOS for s in n.get("supernos", [])):
            erros.append(f"SUPERNO_INVALIDO {nid}")
        if any(x not in LENTES for x in n.get("lentes", [])):
            erros.append(f"LENTE_INVALIDA {nid}")
        if any(v not in VISOES for v in n.get("visoes", [])):
            erros.append(f"VISAO_INVALIDA {nid}")
        if len(n.get("titulo", "")) > 90:
            erros.append(f"TITULO_LONGO {nid}")
        if len(n.get("texto", "")) > 420:
            erros.append(f"TEXTO_LONGO {nid} ({len(n.get('texto', ''))} > 420): detalhe vai para a fonte")
        if n.get("tipo") in ("fonte", "artefato"):
            a = n.get("alias", "")
            if not ALIAS_RX.match(a):
                erros.append(f"ALIAS_INVALIDO {nid}:{a!r}")
            elif a in alias:
                erros.append(f"ALIAS_DUPLICADO {a}")
            alias[a] = nid
    for n in nos:
        for campo in ("fontes", "aponta"):  # fontes = proveniencia (propaga P0); aponta = onde esta o detalhe
            for a in n.get(campo, []):
                if a not in alias:
                    erros.append(f"{'FONTE' if campo == 'fontes' else 'PONTEIRO'}_INEXISTENTE {n['id']} -> [{a}]")
    tem_deriva = defaultdict(list)
    for e in reg.get("arestas", []):
        tipo, s, d = e.get("tipo"), e.get("de"), e.get("para")
        if tipo not in ARESTAS:
            erros.append(f"ARESTA_TIPO_INVALIDO {tipo}")
            continue
        if s not in idx or d not in idx:
            erros.append(f"ARESTA_PENDENTE {tipo} {s}->{d}")
            continue
        dom, cod = ARESTAS[tipo]
        ts, td = idx[s]["tipo"], idx[d]["tipo"]
        if ts not in dom or td not in cod:
            erros.append(f"ARESTA_DOMINIO {tipo} {s}({ts})->{d}({td})")
        if tipo == "substitui" and (ts != td or e.get("motivo") not in MOTIVOS_SUBSTITUI):
            erros.append(f"SUBSTITUI_INVALIDA {s}->{d}")
        if tipo == "avaliado_por" and e.get("resultado") not in RESULTADOS:
            erros.append(f"AVALIACAO_SEM_RESULTADO {s}->{d}")
        if tipo == "relacionado_a" and (not e.get("motivo") or e.get("provisoria") is not True):
            erros.append(f"RELACIONADO_SEM_MOTIVO {s}->{d}")
        if tipo == "ponte":
            if not e.get("motivo") or not e.get("mecanismo"):
                erros.append(f"PONTE_SEM_MECANISMO {s}->{d}")
            if set(idx[s].get("supernos", [])) & set(idx[d].get("supernos", [])):
                erros.append(f"PONTE_MESMO_SUPERNO {s}->{d}")
        if tipo == "deriva_de":
            tem_deriva[s].append((d, e.get("transformacao")))
        if s == d:
            erros.append(f"ARESTA_LACO {s}")
    # seguranca: nada "lava" classe P0. Derivado de fonte mais restrita herda a classe,
    # salvo deriva_de com transformacao=anonimizacao (sem chave de reidentificacao no registro).
    ordem = {c: i for i, c in enumerate(P0)}
    for n in nos:
        origens = [idx[alias[a]]["p0"] for a in n.get("fontes", []) if a in alias]
        origens += [idx[d]["p0"] for d, tr in tem_deriva.get(n["id"], []) if d in idx and tr not in TRANSFORMACOES_SEGURAS]
        if origens and n.get("p0") in ordem and ordem[n["p0"]] < max(ordem[o] for o in origens if o in ordem):
            erros.append(f"P0_LAVAGEM {n['id']} ({n['p0']}) deriva de fonte {max(origens, key=ordem.get)}")
    # proveniencia como gate separado da prioridade (OP2-C2)
    for n in nos:
        exige = n["tipo"] not in ("fonte", "artefato", "evento", "tarefa") and n.get("estado") in ("oficial", "candidato")
        if exige and not n.get("fontes") and n["id"] not in tem_deriva:
            avisos.append(f"SEM_PROVENIENCIA {n['id']}")
        if n.get("evidencia") == "contestada":
            avisos.append(f"CONTESTADA {n['id']}")
    # regra ARTEFATO->FONTE (OP2 T2): artefato citado como fonte precisa derivar de uma fonte
    for a, nid in alias.items():
        citado = idx[nid]["tipo"] == "artefato" and any(a in n.get("fontes", []) for n in nos)
        if citado and not any(idx[d]["tipo"] == "fonte" for d, _ in tem_deriva.get(nid, []) if d in idx):
            avisos.append(f"ARTEFATO_SEM_FONTE_PRIMARIA {a}")
    return {"erros": erros, "avisos": avisos}


# -------------------------------------------------------------------------------- utilidades
def _indices(reg):
    idx = {n["id"]: n for n in reg["nos"]}
    alias = {n["alias"]: n for n in reg["nos"] if n.get("alias")}
    grau = Counter(e["para"] for e in reg.get("arestas", []))
    return idx, alias, grau


def fila_revisao(reg: dict, limite: int = 5) -> dict:
    """Ordem lexicografica explicavel (substitui soma ponderada do IPR): P0 bloqueado sai da fila e vai para
    autorizacao; depois sem proveniencia > contestada > vigencia nao ativa > impacto (quantos dependem) > id."""
    _idx, _, grau = _indices(reg)
    av = validar(reg)["avisos"]
    semprov = {a.split()[1] for a in av if a.startswith("SEM_PROVENIENCIA")}
    autorizacao = [n["id"] for n in reg["nos"] if n.get("estado") == "quarentena"]
    cand = [n for n in reg["nos"] if n["id"] not in autorizacao and n["tipo"] not in ("fonte",)]

    def chave(n):
        return (-(n["id"] in semprov), -(n.get("evidencia") == "contestada"), -(n.get("vigencia") != "ativa"),
                -grau.get(n["id"], 0), n["id"])
    ordem = [n["id"] for n in sorted(cand, key=chave)
             if n["id"] in semprov or n.get("evidencia") == "contestada" or n.get("vigencia") != "ativa"]
    return {"revisar": ordem[:limite], "autorizacao": autorizacao}


def pontes(reg: dict) -> list[tuple]:
    _idx, _, _ = _indices(reg)
    out = []
    for e in reg.get("arestas", []):
        if e["tipo"] == "ponte":
            out.append((e["de"], e["para"], e.get("estado", "hipotese"), e["motivo"]))
    for n in reg["nos"]:  # pertencimento multiplo tambem e ponte (calculada)
        if len(n.get("supernos", [])) >= 2 and n["tipo"] != "fonte":
            out.append((n["id"], "+".join(n["supernos"]), "multipertenca", n["titulo"]))
    return out


def matriz_cruzamento(reg: dict) -> dict:
    m = defaultdict(list)
    for n in reg["nos"]:
        if n["tipo"] == "fonte":
            continue
        for s in n.get("supernos", []):
            for le in n.get("lentes", []):
                m[(s, le)].append(n["id"])
    lacunas = [(s, le) for s in SUPERNOS for le in LENTES if (s, le) not in m]
    return {"celulas": dict(m), "lacunas": lacunas}


# ------------------------------------------------------------------------------- compilacao
CONSUMIDORES = {"claude": "PRIV", "chatgpt": "PRIV", "gemini": "INT", "externo": "PUB"}


def _visivel(n, teto):
    return P0.index(n["p0"]) <= P0.index(teto)


def _ref(alias_ou_id, reg, ids_inline):
    if not ids_inline:
        return f"[{alias_ou_id}]"
    _, alias, _ = _indices(reg)
    n = alias.get(alias_ou_id)
    return f"[{alias_ou_id} {n['drive_id']}]" if n and n.get("drive_id") else f"[{alias_ou_id}]"


def _linha(n, reg, teto, ids_inline, com_texto=True, com_fontes=False):
    """Mapa carregado mostra para ONDE ir (aponta); a proveniencia (fontes) fica no registro/M5,
    salvo na camada de tema (com_fontes=True), onde a citacao importa."""
    alvos = list(dict.fromkeys(n.get("aponta", []) + (n.get("fontes", []) if com_fontes else [])))
    if not _visivel(n, teto) or n["p0"] in ("REST", "COFRE"):
        refs = " ".join(_ref(a, reg, ids_inline) for a in list(dict.fromkeys(n.get("aponta", []) + n.get("fontes", []))))
        return f"- {n['id']} [{n['p0']}] {n['titulo']} — conteudo so na fonte {refs}".rstrip()
    corpo = f": {n['texto']}" if com_texto and n.get("texto") else ""
    marca = {"oficial": "", "candidato": "*", "laboratorio": " (lab)"}.get(n.get("estado"), f" ({n.get('estado')})")
    base = f"- {n['titulo']}{marca}{corpo}"
    refs = [_ref(a, reg, ids_inline) for a in alvos if f"[{a}]" not in base]
    return base + ((" " + " ".join(refs)) if refs else "")


def compilar(reg: dict, consumidor: str = "claude", utc: str = "", ids_inline: bool = False,
             codificado: bool = False) -> dict:
    """Devolve {'M1'..'M4','M3_TEMAS','M5','PACOTE','meta'}. Fail-closed por consumidor."""
    if consumidor not in CONSUMIDORES:
        raise RegistroError(f"CONSUMIDOR_DESCONHECIDO {consumidor}")
    if consumidor == "gemini" and not codificado:
        raise RegistroError("GEMINI_EXIGE_CODIFICACAO (decisao do titular de 18/11: RPD/IIR antes de qualquer envio)")
    v = validar(reg)
    if v["erros"]:
        raise RegistroError("REGISTRO_INVALIDO: " + "; ".join(v["erros"][:8]))
    teto = CONSUMIDORES[consumidor]
    nos = [n for n in reg["nos"] if n.get("estado") not in ("superado", "quarentena")]
    if consumidor in ("gemini", "externo"):  # acima da classe: some por completo (nem o titulo sai)
        nos = [n for n in nos if _visivel(n, teto)]
    # proposta vinda de conversa so entra nos mapas depois de aprovada pelo titular (fica no registro + contagem no M1)
    pendentes = [n for n in nos if n.get("aprovado") is False]
    nos = [n for n in nos if n.get("aprovado") is not False]
    meta = reg.get("meta", {})
    cab = lambda m, t: f"# PERSONA · {m} {t} · {meta.get('versao', 'v?')} · {utc or 'utc?'} · para {consumidor}"

    def bloco(visao, natureza=None, tipo=None):
        return [n for n in nos if visao in n.get("visoes", []) and (natureza is None or n.get("natureza") in natureza)
                and (tipo is None or n["tipo"] in tipo)]

    # M2 REGRAS
    m2 = [cab("M2", "REGRAS — como agir")]
    for titulo, sel in (("Núcleo", {"regra"}), ("Gatilhos → destino", {"roteamento"}),
                        ("Nunca (cemitério de erros)", {"proibicao"}), ("Procedimentos", {"procedimento"}),
                        ("Preferências ativas", {"preferencia"})):
        itens = bloco("M2", sel)
        if itens:
            m2.append(f"## {titulo}")
            m2 += [_linha(n, reg, teto, ids_inline) for n in itens]
    # M1 CONTEXTO
    m1 = [cab("M1", "CONTEXTO — onde estou")]
    for titulo, sel in (("Estado", {"estado"}), ("Decisões do titular", {"decisao"}), ("Tarefas", {"tarefa"}),
                        ("Avisos", {"fato"})):
        itens = bloco("M1", sel)
        if itens:
            m1.append(f"## {titulo}")
            m1 += [_linha(n, reg, teto, ids_inline) for n in itens]
    if pendentes:
        origens = sorted({n.get("origem", "?") for n in pendentes})
        m1.append("## Propostas aguardando o titular")
        m1.append(f"- {len(pendentes)} nós de {len(origens)} conversa(s): " + ", ".join(origens[:3]))
    ids_vis = {n["id"] for n in nos}
    fr = fila_revisao({"nos": nos, "arestas": [e for e in reg.get("arestas", []) if e["de"] in ids_vis and e["para"] in ids_vis]})
    if fr["revisar"] or fr["autorizacao"]:
        m1.append("## Revisar primeiro (calculado)")
        m1.append("- " + " · ".join(fr["revisar"]) if fr["revisar"] else "- nada")
        if fr["autorizacao"]:
            m1.append("- aguardando autorização: " + " · ".join(fr["autorizacao"]))
    # M3 CONTEUDO (topo + temas)
    sinteses = {n["supernos"][0]: n for n in nos if n.get("natureza") == "sintese" and n.get("supernos")}
    m3 = [cab("M3", "CONTEÚDO — o que sei e onde está"), "Topo: 1 linha por supernó. Desça só o tema necessário."]
    temas = {}
    for s in SUPERNOS:
        if s not in sinteses:
            continue
        sn = sinteses[s]
        filhos = [n for n in nos if s in n.get("supernos", []) and "M3" in n.get("visoes", []) and n is not sn]
        m3.append(f"- {s} {sn['titulo']}: {sn['texto']}" + (f" ({len(filhos)} tema{'s' if len(filhos) > 1 else ''})" if filhos else ""))
        t = [cab("M3", f"TEMA {s} — {sn['titulo']}")] + [_linha(n, reg, teto, ids_inline, com_fontes=True) for n in filhos]
        temas[s] = "\n".join(t)
    # M4 CRUZAMENTO
    m4 = [cab("M4", "CRUZAMENTO — só em pergunta aberta ou 'mapa mental geral'")]
    m4 += [_linha(n, reg, teto, ids_inline) for n in bloco("M4")]
    vis = {n["id"] for n in nos if _visivel(n, teto)}
    mc = matriz_cruzamento({"nos": [n for n in nos if n["id"] in vis]})
    nomes_l = reg.get("lentes", {})
    if mc["celulas"]:
        abrev = {le: nomes_l.get(le, le)[:3] for le in LENTES}
        m4.append("## Densidade supernó × lente (nº de nós; abra M3 do supernó)")
        for s in SUPERNOS:
            celulas = [f"{abrev[le]} {len(mc['celulas'][(s, le)])}" for le in LENTES if (s, le) in mc["celulas"]]
            if celulas:
                m4.append(f"- {s}: " + " · ".join(celulas))
    listados = {n["id"] for n in bloco("M4")}
    pts = [p for p in pontes({"nos": [n for n in nos if n["id"] in vis],
                              "arestas": [e for e in reg.get("arestas", []) if e["de"] in vis and e["para"] in vis]})]
    explicitas = [p for p in pts if p[2] != "multipertenca"]
    multi = [p for p in pts if p[2] == "multipertenca" and p[0] not in listados]
    if explicitas or multi:
        m4.append("## Pontes")
        m4 += [f"- {a} ↔ {b} ({est}): {mot}" for a, b, est, mot in explicitas[:8]]
        if multi:
            m4.append("- em 2+ supernós: " + ", ".join(f"{a}({b})" for a, b, _, _ in multi[:10]))
    if mc["lacunas"]:
        m4.append("## Lacunas para exploração deliberada")
        m4.append("- " + ", ".join(f"{s}×{nomes_l.get(le, le)[:3]}" for s, le in mc["lacunas"][:16]))
    # M5 ENDERECOS (consulta)
    m5 = [cab("M5", "ENDEREÇOS — apelido → fonte (consulta; não carregar inteiro)")]
    for n in sorted((n for n in reg["nos"] if n.get("alias")), key=lambda n: n["alias"]):
        if not _visivel(n, teto) and consumidor in ("externo", "gemini"):
            continue
        did = n.get("drive_id", "-") if consumidor in ("claude", "chatgpt") else "-"
        m5.append(f"- {n['alias']} = {did} · {n['tipo']} · {n['p0']} · {n['estado']} · {n['titulo']}")
    views = {"M1": "\n".join(m1), "M2": "\n".join(m2), "M3": "\n".join(m3), "M4": "\n".join(m4),
             "M5": "\n".join(m5), "M3_TEMAS": temas}
    views["PACOTE"] = "\n\n".join([views["M2"], views["M1"], views["M3"]])
    if consumidor == "externo":
        from persona_lab.p0_gate import checar
        for k in ("M1", "M2", "M3", "M4", "M5", "PACOTE"):
            if checar(views[k]):
                raise RegistroError(f"P0_GATE_BLOQUEOU {k}")
    medidas = {k: contar_tokens(views[k]) for k in ("M1", "M2", "M3", "M4", "M5", "PACOTE")}
    medidas.update({f"M3_TEMA_{s}": contar_tokens(t) for s, t in temas.items()})
    views["meta"] = {"consumidor": consumidor, "tokenizador": TOKENIZADOR, "tokens": medidas,
                     "registro_sha256": sha256_json({"nos": reg["nos"], "arestas": reg.get("arestas", [])}),
                     "avisos": v["avisos"], "estouros": verificar_tetos(medidas)}
    return views


def verificar_tetos(medidas: dict, tetos: dict = TETOS) -> list[str]:
    out = []
    for k, v in medidas.items():
        teto = tetos.get("M3_TEMA") if k.startswith("M3_TEMA_") else tetos.get(k)
        if teto and v > teto:
            out.append(f"{k}={v}>{teto}")
    return out


def cobertura(texto: str, exigidos: list[str]) -> dict:
    """Regressao: quais gatilhos/apelidos exigidos aparecem no texto carregado."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    t = norm(texto)
    faltam = [x for x in exigidos if norm(x) not in t]
    return {"exigidos": len(exigidos), "presentes": len(exigidos) - len(faltam), "faltam": faltam}
