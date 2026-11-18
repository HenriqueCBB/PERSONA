"""HAND-01 (CODEX-20261118): task card + executor retomavel. CANDIDATO, laboratorio.

- Estados: RESERVED -> RUNNING -> EVIDENCE_READY -> AUDITED -> HUMAN_APPROVED -> RELEASED.
  Desvios: qualquer estado nao final -> BLOCKED; RESERVED/RUNNING -> RELEASED_LEASE (desistencia).
  HUMAN_APPROVED so pode ser dado por ator do papel 'titular' (papel DECLARADO: nao e autenticacao).
- Checkpoint atomico (arquivo temporario + fsync + os.replace).
- Efeitos com idempotency key por etapa num diario so-acrescimo: retomada apos SIGKILL nao repete efeito.
- Lease com epoch: escrita de dono antigo (epoch menor) e recusada (fencing token).
Somente biblioteca padrao.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime

ESTADOS = ["RESERVED", "RUNNING", "EVIDENCE_READY", "AUDITED", "HUMAN_APPROVED", "RELEASED", "BLOCKED", "RELEASED_LEASE"]
TRANSICOES = {
    "RESERVED": {"RUNNING", "BLOCKED", "RELEASED_LEASE"},
    "RUNNING": {"EVIDENCE_READY", "BLOCKED", "RELEASED_LEASE"},
    "EVIDENCE_READY": {"AUDITED", "BLOCKED"},
    "AUDITED": {"HUMAN_APPROVED", "BLOCKED"},
    "HUMAN_APPROVED": {"RELEASED", "BLOCKED"},
    "RELEASED": set(), "BLOCKED": set(), "RELEASED_LEASE": set(),
}
REQUIRED = ["schema_version", "id", "estado", "utc", "autor_declarado", "base_hash", "evidencia",
            "proximo_executor", "bloqueio", "lease", "idempotency_key", "historico"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class CardError(ValueError):
    pass


def agora() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def idem_key(card_id: str, base_hash: str, etapa: str) -> str:
    return sha256(f"{card_id}\x1f{base_hash}\x1f{etapa}".encode())


def novo_card(card_id: str, autor: str, base_hash: str) -> dict:
    return {"schema_version": "persona-taskcard-1", "id": card_id, "estado": "RESERVED", "utc": agora(),
            "autor_declarado": autor, "base_hash": base_hash, "evidencia": [], "proximo_executor": autor,
            "bloqueio": None, "lease": {"dono": autor, "epoch": 1, "expira_utc": None},
            "idempotency_key": idem_key(card_id, base_hash, "card"), "historico": []}


def validar(card: dict) -> None:
    if not isinstance(card, dict):
        raise CardError("CARD_NAO_E_OBJETO")
    faltam = [k for k in REQUIRED if k not in card]
    extras = [k for k in card if k not in REQUIRED]
    if faltam or extras:
        raise CardError(f"CAMPOS faltam={faltam} extras={extras}")
    if card["schema_version"] != "persona-taskcard-1":
        raise CardError("SCHEMA_VERSION")
    if not re.match(r"^[A-Z0-9][A-Z0-9-]{1,40}$", str(card["id"])):
        raise CardError("ID_INVALIDO")
    if card["estado"] not in ESTADOS:
        raise CardError("ESTADO_INVALIDO")
    if not UTC_RX.match(str(card["utc"])):
        raise CardError("UTC_INVALIDO")
    if not isinstance(card["autor_declarado"], str) or not card["autor_declarado"].strip():
        raise CardError("AUTOR_INVALIDO")
    for k in ("base_hash", "idempotency_key"):
        if not isinstance(card[k], str) or not HEX64.match(card[k]):
            raise CardError(f"{k.upper()}_INVALIDO")
    if not isinstance(card["evidencia"], list) or any(
            not isinstance(e, dict) or not isinstance(e.get("ref"), str) or not HEX64.match(str(e.get("sha256", "")))
            for e in card["evidencia"]):
        raise CardError("EVIDENCIA_INVALIDA")
    lease = card["lease"]
    if not isinstance(lease, dict) or type(lease.get("epoch")) is not int or lease["epoch"] < 0:
        raise CardError("LEASE_INVALIDA")
    if card["estado"] in ("EVIDENCE_READY", "AUDITED", "HUMAN_APPROVED", "RELEASED") and not card["evidencia"]:
        raise CardError("ESTADO_EXIGE_EVIDENCIA")


def transicionar(card: dict, para: str, ator: str, papel: str = "executor", epoch: int | None = None) -> dict:
    validar(card)
    de = card["estado"]
    if para not in TRANSICOES[de]:
        raise CardError(f"TRANSICAO_PROIBIDA {de}->{para}")
    if epoch is not None and epoch < card["lease"]["epoch"]:
        raise CardError("LEASE_EPOCH_ANTIGA")
    if para == "HUMAN_APPROVED" and papel != "titular":
        raise CardError("APROVACAO_EXIGE_TITULAR")
    if para == "AUDITED" and ator == card["autor_declarado"]:
        raise CardError("AUDITOR_IGUAL_AUTOR")
    novo = json.loads(json.dumps(card))
    novo["estado"] = para
    novo["utc"] = agora()
    novo["historico"].append({"de": de, "para": para, "utc": novo["utc"], "ator": ator})
    validar(novo)
    return novo


def gravar_atomico(path: str, obj) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def ler(path: str, padrao=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return padrao


class Executor:
    """Executa etapas de um card com checkpoint. Efeito = linha no diario de efeitos (so-acrescimo)."""

    def __init__(self, pasta: str, card: dict, etapas: list[str]):
        self.pasta = pasta
        self.ck = os.path.join(pasta, "checkpoint.json")
        self.diario = os.path.join(pasta, "efeitos.jsonl")
        self.card = card
        self.etapas = etapas

    def efeitos_feitos(self) -> set[str]:
        feitos = set()
        try:
            with open(self.diario, encoding="utf-8") as fh:
                for linha in fh:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        feitos.add(json.loads(linha)["idem"])
                    except (ValueError, KeyError):
                        continue  # linha parcial de um crash: ignorada, etapa sera refeita uma vez
        except FileNotFoundError:
            pass
        return feitos

    def _efeito(self, etapa: str, idem: str) -> None:
        if idem in self.efeitos_feitos():
            return  # idempotente: ja aplicado antes do crash
        prefixo = ""
        if os.path.exists(self.diario) and os.path.getsize(self.diario) > 0:
            with open(self.diario, "rb") as fh:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    prefixo = "\n"  # fecha linha parcial deixada por crash, sem colar o novo registro nela
        with open(self.diario, "a", encoding="utf-8") as fh:
            fh.write(prefixo + json.dumps({"idem": idem, "etapa": etapa}) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def rodar(self, apos_etapa=None) -> dict:
        estado = ler(self.ck, {"card": self.card, "concluidas": []})
        card = estado["card"]
        if card["estado"] == "RESERVED":
            card = transicionar(card, "RUNNING", card["autor_declarado"])
            gravar_atomico(self.ck, {"card": card, "concluidas": estado["concluidas"]})
        for etapa in self.etapas:
            if etapa in estado["concluidas"]:
                continue
            self._efeito(etapa, idem_key(card["id"], card["base_hash"], etapa))
            estado["concluidas"].append(etapa)
            gravar_atomico(self.ck, {"card": card, "concluidas": estado["concluidas"]})
            if apos_etapa:
                apos_etapa(etapa)
        with open(self.diario, "rb") as fh:
            ev = {"ref": "efeitos.jsonl", "sha256": sha256(fh.read())}
        card = json.loads(json.dumps(card))
        card["evidencia"] = [ev]
        card = transicionar(card, "EVIDENCE_READY", card["autor_declarado"])
        gravar_atomico(self.ck, {"card": card, "concluidas": estado["concluidas"]})
        return card
