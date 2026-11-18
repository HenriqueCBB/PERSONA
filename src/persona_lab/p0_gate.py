"""Gate tecnico de saida P0 (SEC-01, CODEX-20261118). CANDIDATO.

Bloqueia texto que nao pode sair do ambiente privado (busca, plugin, GitHub, log, e-mail).
Fail-closed: entrada que nao e str, ou erro interno, conta como BLOQUEADO.

Camadas:
  1. Normalizacao anti-ofuscacao: NFKC, remove caracteres de largura zero e controles.
  2. Identificadores BR com digito verificador: CPF, CNPJ; RG, NUP, UG/UASG, doc SIAFI, telefone, e-mail.
  3. Credenciais: chaves de API conhecidas, Bearer/JWT, AWS, bloco de chave privada, senha=valor.
  4. Injecao de instrucoes (prompt injection): ordens dirigidas a IA, exfiltracao, comentario oculto.
  5. Lista de termos restritos guardada so como hash com sal (compativel com persona_saida.py do R5).

Achados nunca reproduzem o trecho: so tipo, posicao e mascara.
Somente biblioteca padrao. Uso CLI: python -m persona_lab.p0_gate arquivo.txt  (exit 1 = bloqueado)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata

ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b‌‍⁠﻿­"), None)


def normalizar_visual(texto: str) -> str:
    t = unicodedata.normalize("NFKC", texto).translate(ZERO_WIDTH)
    return "".join(c if (c in "\n\t" or unicodedata.category(c)[0] != "C") else " " for c in t)


def normalizar_termo(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


def _dv_cpf(d: str) -> bool:
    if len(d) != 11 or len(set(d)) == 1:
        return False
    s1 = sum(int(c) * w for c, w in zip(d[:9], range(10, 1, -1)))
    s2 = sum(int(c) * w for c, w in zip(d[:10], range(11, 1, -1)))
    return (s1 * 10 % 11) % 10 == int(d[9]) and (s2 * 10 % 11) % 10 == int(d[10])


def _dv_cnpj(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def dv(nums, w):
        r = sum(int(c) * k for c, k in zip(nums, w)) % 11
        return 0 if r < 2 else 11 - r
    return dv(d[:12], w1) == int(d[12]) and dv(d[:13], [6] + w1) == int(d[13])


_SEP = r"[\s.\-/]?"
PADROES = [
    ("CPF", re.compile(rf"(?<![\w])\d{{3}}{_SEP}\d{{3}}{_SEP}\d{{3}}{_SEP}\d{{2}}(?![\w])"), lambda s: _dv_cpf(re.sub(r"\D", "", s))),
    ("CNPJ", re.compile(rf"(?<![\w])\d{{2}}{_SEP}\d{{3}}{_SEP}\d{{3}}{_SEP}\d{{4}}{_SEP}\d{{2}}(?![\w])"), lambda s: _dv_cnpj(re.sub(r"\D", "", s))),
    ("RG", re.compile(r"\bRG\s*(?:n[º°o.]*\s*)?[:\-]?\s*\d{1,2}\.?\d{3}\.?\d{3}-?[\dXx]\b", re.IGNORECASE), None),
    ("NUP", re.compile(r"(?<!\d)\d{5}\.\d{6}/\d{4}-\d{2}(?!\d)"), None),
    ("UG_UASG", re.compile(r"\b(?:UASG|UGE?|UG\s+gestora)\s*(?:n[º°o.]*\s*)?[:\-]?\s*\d{6}\b", re.IGNORECASE), None),
    ("DOC_SIAFI", re.compile(r"\b(?:19|20)\d{2}\s?(?:NE|NF|OB|PF|NS|RA|GR|NL|DF|DR)\s?\d{6}\b"), None),
    ("EMAIL", re.compile(r"\b[\w.+-]+\s?(?:@|\(at\)|\[at\])\s?[\w-]+(?:\s?(?:\.|\(dot\)|\[dot\])\s?[\w-]+)+\b", re.IGNORECASE), None),
    ("TELEFONE", re.compile(r"(?<![\w.])(?:\+55\s?)?\(?\d{2}\)?\s?9\d{4}[-\s]?\d{4}\b"), None),
    ("CHAVE_API", re.compile(r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})"), None),
    ("TOKEN_BEARER", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"), None),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), None),
    ("CHAVE_PRIVADA", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"), None),
    ("SENHA_ATRIBUIDA", re.compile(r"\b(?:senha|password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*['\"]?(?![<{*$%])[^\s'\"<>]{6,}", re.IGNORECASE), None),
]

# Injecao: ordem dirigida a um agente + verbo de acao perigosa, ou comentario oculto com ordem.
_ALVO = r"(?:assistente|assistant|ia\b|ai\b|agente|agent|modelo|model|llm|chatgpt|claude|gemini|codex|sistema|system)"
_ORDEM = (r"(?:ignore|ignora|desconsidere|disregard|forget|esque[cç]a)\s+(?:\w+\s+){0,3}"
          r"(?:instru[cç][oõ]es|instructions|regras|rules|prompt)")
_EXFIL = (r"(?:envie|enviar|mande|send|copie|copy|exfiltr\w*|publique|post|upload|curl|wget)\b[^\n]{0,80}?"
          r"(?:@|https?://|para\s+fora|externo|external|[ií]ndice|senha|token|credencia|chave|"
          r"persona|drive|arquivo|reposit)")
_DESTR = (r"(?:apague|apagar|delete|remova|rm\s+-rf)\b[^\n]{0,40}?"
          r"(?:este aviso|esta mensagem|this (?:note|message)|os logs|o hist[oó]rico|todos os arquivos|all files|everything|tudo)")
INJECAO = [
    ("INJ_IGNORAR_REGRAS", re.compile(_ORDEM, re.IGNORECASE)),
    ("INJ_EXFILTRACAO", re.compile(_EXFIL, re.IGNORECASE)),
    ("INJ_ACAO_DESTRUTIVA", re.compile(_DESTR, re.IGNORECASE)),
    ("INJ_COMENTARIO_OCULTO", re.compile(rf"<!--[^>]*?{_ALVO}[^>]*?-->", re.IGNORECASE | re.DOTALL)),
    ("INJ_PAPEL_FALSO", re.compile(r"(?:^|\n)\s*(?:system|sistema|assistant)\s*:\s*(?:voc[eê]|you)\s", re.IGNORECASE)),
]

# Negacao/discussao: texto que FALA de injecao sem ordenar (ex.: aula, politica). So afeta INJ_*.
_META = re.compile(r"(?:exemplo de|exemplos de|example of|detect\w*|bloque\w*|nunca|never|n[aã]o (?:siga|obede[cç]a)|"
                   r"o que [eé]|what is|defin\w*|pol[ií]tica)", re.IGNORECASE)


def _mascara(s: str) -> str:
    s = s.strip()
    return (s[:2] + "***" + s[-1:]) if len(s) > 4 else "***"


def _h(sal: str, termo: str) -> str:
    return hashlib.sha256((sal + "\x1f" + termo).encode("utf-8")).hexdigest()


def checar(texto, denylist: dict | None = None) -> list[dict]:
    """Devolve lista de achados; lista vazia = liberado. Fail-closed."""
    try:
        if not isinstance(texto, str):
            return [{"tipo": "ENTRADA_INVALIDA", "inicio": 0, "mascara": "***"}]
        t = normalizar_visual(texto)
        achados = []
        for tipo, rx, valid in PADROES:
            for m in rx.finditer(t):
                if valid and not valid(m.group(0)):
                    continue
                achados.append({"tipo": tipo, "inicio": m.start(), "mascara": _mascara(m.group(0))})
        for tipo, rx in INJECAO:
            for m in rx.finditer(t):
                janela = t[max(0, m.start() - 60): m.start()]
                if tipo != "INJ_COMENTARIO_OCULTO" and _META.search(janela):
                    continue
                achados.append({"tipo": tipo, "inicio": m.start(), "mascara": "***"})
        if denylist:
            alvo = set(denylist["hashes"])
            palavras = normalizar_termo(t).split()
            for n in denylist.get("ngramas", [1, 2, 3]):
                for i in range(len(palavras) - n + 1):
                    if _h(denylist["sal"], " ".join(palavras[i:i + n])) in alvo:
                        achados.append({"tipo": "TERMO_RESTRITO", "inicio": i, "mascara": "***"})
        return sorted(achados, key=lambda a: (a["tipo"], a["inicio"]))
    except Exception:  # noqa: BLE001 - fail-closed intencional: qualquer erro bloqueia
        return [{"tipo": "ERRO_INTERNO", "inicio": 0, "mascara": "***"}]


def liberar(texto, denylist: dict | None = None) -> bool:
    return not checar(texto, denylist)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        with open(argv[0], encoding="utf-8") as fh:
            texto = fh.read()
    else:
        texto = sys.stdin.read()
    achados = checar(texto)
    print(json.dumps({"liberado": not achados, "achados": achados}, ensure_ascii=False))
    return 1 if achados else 0


if __name__ == "__main__":
    sys.exit(main())
