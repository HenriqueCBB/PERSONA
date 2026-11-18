import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)
from persona_lab import taskcard as tc

BASE = "a" * 64
ETAPAS = [f"E{i:02d}" for i in range(12)]

FILHO = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from persona_lab import taskcard as tc
card = tc.novo_card("CX-6", "codex", "a" * 64)
ex = tc.Executor(sys.argv[2], card, [f"E{i:02d}" for i in range(12)])
ex.rodar(apos_etapa=lambda e: (print(e, flush=True), time.sleep(0.15)))
'''


class TestCard(unittest.TestCase):
    def test_card_novo_valido(self):
        tc.validar(tc.novo_card("CX-6", "codex", BASE))

    def test_campos_extra_e_faltando(self):
        c = tc.novo_card("CX-6", "codex", BASE)
        c["extra"] = 1
        with self.assertRaises(tc.CardError):
            tc.validar(c)
        c = tc.novo_card("CX-6", "codex", BASE)
        del c["lease"]
        with self.assertRaises(tc.CardError):
            tc.validar(c)

    def test_transicao_proibida(self):
        c = tc.novo_card("CX-6", "codex", BASE)
        with self.assertRaises(tc.CardError):
            tc.transicionar(c, "RELEASED", "codex")

    def test_evidence_ready_exige_evidencia(self):
        c = tc.transicionar(tc.novo_card("CX-6", "codex", BASE), "RUNNING", "codex")
        with self.assertRaises(tc.CardError):
            tc.transicionar(c, "EVIDENCE_READY", "codex")

    def test_auditor_diferente_e_aprovacao_do_titular(self):
        c = tc.transicionar(tc.novo_card("CX-6", "codex", BASE), "RUNNING", "codex")
        c["evidencia"] = [{"ref": "x", "sha256": "b" * 64}]
        c = tc.transicionar(c, "EVIDENCE_READY", "codex")
        with self.assertRaises(tc.CardError):
            tc.transicionar(c, "AUDITED", "codex")
        c = tc.transicionar(c, "AUDITED", "claude")
        with self.assertRaises(tc.CardError):
            tc.transicionar(c, "HUMAN_APPROVED", "chatgpt", papel="executor")
        c = tc.transicionar(c, "HUMAN_APPROVED", "titular", papel="titular")
        c = tc.transicionar(c, "RELEASED", "publisher")
        self.assertEqual([h["para"] for h in c["historico"]],
                         ["RUNNING", "EVIDENCE_READY", "AUDITED", "HUMAN_APPROVED", "RELEASED"])

    def test_epoch_antiga_recusada(self):
        c = tc.novo_card("CX-6", "codex", BASE)
        c["lease"]["epoch"] = 5
        with self.assertRaises(tc.CardError):
            tc.transicionar(c, "RUNNING", "codex", epoch=4)

    def test_tipo_bool_nao_vale_como_int(self):
        c = tc.novo_card("CX-6", "codex", BASE)
        c["lease"]["epoch"] = True
        with self.assertRaises(tc.CardError):
            tc.validar(c)


class TestRetomada(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _kill_no_meio(self, apos=5):
        p = subprocess.Popen([sys.executable, "-c", FILHO, SRC, self.d], stdout=subprocess.PIPE, text=True)
        vistos = 0
        try:
            for _ in p.stdout:
                vistos += 1
                if vistos >= apos:
                    p.send_signal(signal.SIGKILL)
                    break
        finally:
            p.wait(10)
            p.stdout.close()
        return vistos

    def _contagem_efeitos(self):
        with open(os.path.join(self.d, "efeitos.jsonl"), encoding="utf-8") as fh:
            etapas = [json.loads(linha)["etapa"] for linha in fh if linha.strip()]
        return etapas

    def test_sigkill_e_retomada_sem_duplicar(self):
        for corte in (1, 5, 11):
            with self.subTest(corte=corte):
                shutil.rmtree(self.d)
                os.makedirs(self.d)
                self._kill_no_meio(corte)
                antes = self._contagem_efeitos()
                self.assertGreaterEqual(len(antes), corte)
                self.assertLess(len(antes), len(ETAPAS))
                ck = tc.ler(os.path.join(self.d, "checkpoint.json"))
                ex = tc.Executor(self.d, ck["card"], ETAPAS)
                card = ex.rodar()
                depois = self._contagem_efeitos()
                self.assertEqual(depois, ETAPAS, "efeito repetido ou perdido")
                self.assertEqual(card["estado"], "EVIDENCE_READY")
                tc.validar(card)

    def test_crash_entre_efeito_e_checkpoint(self):
        # Efeito gravado mas checkpoint nao: a retomada NAO pode repetir o efeito.
        card = tc.novo_card("CX-6", "codex", BASE)
        ex = tc.Executor(self.d, card, ETAPAS)
        ex._efeito("E00", tc.idem_key("CX-6", BASE, "E00"))
        ex.rodar()
        self.assertEqual(self._contagem_efeitos(), ETAPAS)

    def test_linha_parcial_no_diario(self):
        card = tc.novo_card("CX-6", "codex", BASE)
        with open(os.path.join(self.d, "efeitos.jsonl"), "w", encoding="utf-8") as fh:
            fh.write('{"idem": "trunc')
        tc.Executor(self.d, card, ETAPAS).rodar()
        with open(os.path.join(self.d, "efeitos.jsonl"), encoding="utf-8") as fh:
            ok = [json.loads(linha)["etapa"] for linha in fh.read().split("\n")[1:] if linha.strip()]
        self.assertEqual(ok, ETAPAS)


if __name__ == "__main__":
    unittest.main()
