import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from persona_lab import mem_bench as mb

RUIDO = " ".join(f"grupo-{i}" for i in range(300))


def caso(cid, fatos, pergunta, gold, pos=0.5):
    w = RUIDO.split()
    c = int(len(w) * pos)
    ctx = " ".join(w[:c]) + " " + " ".join(fatos) + " " + " ".join(w[c:])
    return ({"case_id": cid, "question": pergunta, "context": ctx},
            {"case_id": cid, "gold_answer": gold, "evidence_lines": fatos, "length_words": len(ctx.split()),
             "task_class": cid.split("-")[0]})


CASOS = [
    caso("needle-1", ["[FATO PRINCIPAL] Identificador OBJ-111111; código de auditoria registrado: PX-1234567."],
         "Qual o código de auditoria registrado para o identificador OBJ-111111? Responda somente o código.", "PX-1234567"),
    caso("temporal-1", ["[VERSÃO ANTERIOR] Unidade OBJ-222222, revisão 1: identificador PX-1000001.",
                        "[VERSÃO NOVA] Unidade OBJ-222222, revisão 2 (substitui a 1): identificador PX-2000002."],
         "Qual identificador está vigente na revisão mais recente da unidade OBJ-222222? Responda somente o identificador.",
         "PX-2000002"),
    caso("exception-1", ["[REGRA GERAL] Processo OBJ-333333: autorização NEGADA, como padrão.",
                         "[EXCEÇÃO] Processo OBJ-333333: se houver selo SETOR-42, autorização PERMITIDA apesar da regra geral.",
                         "[ESTADO] Processo OBJ-333333 possui selo SETOR-42."],
         "Qual autorização se aplica ao processo OBJ-333333, consideradas regra, exceção e estado? Responda PERMITIDA ou NEGADA.",
         "PERMITIDA"),
    caso("two_hop-1", ["[PONTE A] A unidade OBJ-444444 depende do protocolo associado ao PONTE-777777.",
                       "[PONTE B] O protocolo do PONTE-777777 usa o código PX-7654321."],
         "Qual código usa o protocolo associado à unidade OBJ-444444? Responda somente o código.", "PX-7654321"),
]


class TestMemBench(unittest.TestCase):
    def test_braco_A_e_teto(self):
        for c, g in CASOS:
            with self.subTest(c["case_id"]):
                self.assertEqual(mb.extrair(c["question"], mb.braco_A(c)), g["gold_answer"])

    def test_C_e_D_entregam_menos_palavras(self):
        for c, _ in CASOS:
            self.assertLess(len(mb.braco_C(c).split()), len(mb.braco_A(c).split()))
            self.assertLess(len(mb.braco_D(c).split()), len(mb.braco_A(c).split()))

    def test_D_segue_ponte_quando_fatos_separados(self):
        fatos = ["[PONTE A] A unidade OBJ-555555 depende do protocolo associado ao PONTE-888888.",
                 "[PONTE B] O protocolo do PONTE-888888 usa o código PX-1111111."]
        w = RUIDO.split()
        ctx = " ".join(w[:20]) + " " + fatos[0] + " " + " ".join(w[20:250]) + " " + fatos[1] + " " + " ".join(w[250:])
        c = {"case_id": "x", "question": "Qual código usa o protocolo associado à unidade OBJ-555555? Responda somente o código.",
             "context": ctx}
        self.assertEqual(mb.extrair(c["question"], mb.braco_D(c)), "PX-1111111")

    def test_extrator_atravessa_quebra_de_linha(self):
        # regressao: fato partido entre dois fragmentos unidos por \n
        t = ("[VERSÃO ANTERIOR] Unidade OBJ-1, revisão 1: identificador PX-1. "
             "[VERSÃO NOVA] Unidade OBJ-1, revisão 2 (substitui a 1):\nidentificador PX-2.")
        q = "Qual identificador está vigente na revisão mais recente da unidade OBJ-1? Responda somente o identificador."
        self.assertEqual(mb.extrair(q, t), "PX-2")

    def test_extrator_nao_ve_gabarito(self):
        c, _g = CASOS[0]
        self.assertNotIn("gold_answer", c)

    def test_llm_pendente(self):
        with self.assertRaises(NotImplementedError):
            mb.braco_llm_pendente(CASOS[0][0])

    def test_avaliar(self):
        casos = [c for c, _ in CASOS]
        gab = {g["case_id"]: g for _, g in CASOS}
        res = mb.avaliar(mb.rodar(casos), gab)
        self.assertTrue(all(v["n"] == 1 for v in res.values()))
        self.assertEqual(mb.recall_evidencia(casos, gab, "A"), 1.0)


if __name__ == "__main__":
    unittest.main()
