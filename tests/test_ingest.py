import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from persona_lab import ingest as ig
from persona_lab import mapa as mp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus_p0 import EMAIL_FICTICIO, ISCA_INJECAO  # iscas ficam no unico arquivo isento da varredura P0

CONV = "claude:sintetica-001"


def msgs(n=6, conv=CONV, injetar=False):
    out = []
    for i in range(1, n + 1):
        papel = "titular" if i % 2 else "ia"
        txt = f"mensagem sintetica {i}"
        if injetar and i == 3:
            txt = ISCA_INJECAO
        out.append({"conversa": conv, "msg": f"m{i:04d}", "ordem": i, "papel": papel, "tipo": "texto", "texto": txt})
    return out


def grava(path, linhas):
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in linhas)


def capsula(nos, conv=CONV):
    return "texto livre antes\n<<<CAPSULA " + json.dumps({"formato": "persona-capsula-1", "conversa": conv,
                                                           "nos": nos}, ensure_ascii=False) + " CAPSULA>>>"


BASE = {"meta": {"versao": "t"}, "nos": [
    {"id": "D-OLD", "tipo": "decisao", "natureza": "decisao", "titulo": "Decisão antiga", "texto": "x", "p0": "INT",
     "visoes": ["M1"], "supernos": [], "lentes": [], "fontes": [], "aponta": [], "estado": "oficial",
     "evidencia": "declarada", "vigencia": "ativa"}], "arestas": []}


def _arquivar_em_processo(bruto, pasta):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    from persona_lab import ingest
    return ingest.arquivar(bruto, pasta)


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.arq = os.path.join(self.d, "arquivo")
        self.bruto = os.path.join(self.d, "bruto.jsonl")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_T01_ordem_e_integridade(self):
        m = msgs()
        m[2]["ordem"] = 1
        grava(self.bruto, m)
        with self.assertRaises(ig.IngestError):
            ig.arquivar(self.bruto, self.arq)
        grava(self.bruto, msgs())
        r = ig.arquivar(self.bruto, self.arq)
        self.assertEqual(r["status"], "VERIFIED")
        with open(os.path.join(self.arq, r["arquivo"]), "rb") as fh:
            self.assertEqual(ig.sha256_bytes(fh.read()), r["sha256"])

    def test_T02_lacuna_multimodal_vira_parcial(self):
        m = msgs()
        m[1].update(tipo="imagem", texto="")
        grava(self.bruto, m)
        self.assertEqual(ig.arquivar(self.bruto, self.arq)["status"], "PARTIAL")

    def test_T03_reinicio_no_meio_sem_duplicar(self):
        grava(self.bruto, msgs(4))
        r1 = ig.arquivar(self.bruto, self.arq)
        grava(self.bruto, msgs(6))
        r2 = ig.arquivar(self.bruto, self.arq)
        self.assertEqual((r1["versao"], r2["versao"]), (1, 2))
        self.assertTrue(os.path.exists(os.path.join(self.arq, r1["arquivo"])))  # v1 preservada
        cap = ig.extrair_capsula(capsula([{"tipo": "decisao", "titulo": "Decidiu X", "msgs": ["m0001"]}]))
        m1 = ig.mapa_conversa(cap, msgs(6))
        reg = ig.aplicar_candidatos(BASE, m1, ig.reconciliar(BASE, m1))
        d2 = ig.reconciliar(reg, ig.mapa_conversa(cap, msgs(6)))
        self.assertEqual([o["op"] for o in d2["operacoes"]], ["nenhuma"])

    def test_T04_idempotencia_e_trava(self):
        grava(self.bruto, msgs())
        a = ig.arquivar(self.bruto, self.arq)
        b = ig.arquivar(self.bruto, self.arq)
        self.assertTrue(b.get("idempotente"))
        self.assertEqual(a["sha256"], b["sha256"])
        with ig.trava(self.arq), self.assertRaises(FileExistsError), ig.trava(self.arq, tentativas=3):
            pass

    def test_T04b_dois_processos_ao_mesmo_tempo(self):
        import multiprocessing as mpc
        grava(self.bruto, msgs())
        ctx = mpc.get_context("spawn")
        with ctx.Pool(2) as pool:
            res = pool.starmap(_arquivar_em_processo, [(self.bruto, self.arq)] * 2)
        self.assertEqual(sorted(bool(r.get("idempotente")) for r in res), [False, True])
        with open(os.path.join(self.arq, "MANIFESTO.jsonl"), encoding="utf-8") as fh:
            self.assertEqual(len([x for x in fh if x.strip()]), 1)

    def test_T05_link_reversivel(self):
        cap = ig.extrair_capsula(capsula([{"tipo": "decisao", "titulo": "ok", "msgs": ["m0002"]},
                                          {"tipo": "decisao", "titulo": "sem fonte", "msgs": ["m9999"]}]))
        m = ig.mapa_conversa(cap, msgs())
        self.assertEqual(len(m["nos"]), 1)
        self.assertEqual(m["nos"][0]["msgs"], ["m0002"])
        self.assertEqual(m["rejeitados"][0]["motivo"][:20], "PONTEIRO_SEM_MENSAGE")

    def test_T06_supersessao_preserva_original(self):
        cap = ig.extrair_capsula(capsula([{"tipo": "decisao", "titulo": "Decisão nova", "msgs": ["m0003"],
                                           "relacao": "atualiza:D-OLD"}]))
        m = ig.mapa_conversa(cap, msgs())
        d = ig.reconciliar(BASE, m)
        self.assertEqual(d["operacoes"][0]["op"], "nova_versao")
        novo = ig.aplicar_candidatos(BASE, m, d)
        antigo = next(n for n in novo["nos"] if n["id"] == "D-OLD")
        self.assertEqual(antigo, BASE["nos"][0])  # original intacto
        self.assertEqual(mp.validar(novo)["erros"], [])
        self.assertTrue(any(e["tipo"] == "substitui" for e in novo["arestas"]))

    def test_T06b_tipo_divergente_rejeitado(self):
        cap = ig.extrair_capsula(capsula([{"tipo": "afirmacao", "titulo": "x", "msgs": ["m0001"],
                                           "relacao": "substitui:D-OLD"}]))
        d = ig.reconciliar(BASE, ig.mapa_conversa(cap, msgs()))
        self.assertEqual(d["operacoes"][0]["op"], "rejeitar")

    def test_T07_p0_negado_ao_externo(self):
        cap = ig.extrair_capsula(capsula([{"tipo": "afirmacao", "titulo": "Dado pessoal", "texto": EMAIL_FICTICIO,
                                           "msgs": ["m0001"], "p0": "INT", "supernos": ["S7"]}]))
        m = ig.mapa_conversa(cap, msgs())
        self.assertEqual(m["nos"][0]["p0"], "PRIV")  # identificador detectado sobe a classe
        reg = ig.aplicar_candidatos(BASE, m, ig.reconciliar(BASE, m))
        ext = mp.compilar(reg, "externo")
        self.assertNotIn(EMAIL_FICTICIO.split()[-1], json.dumps(ext, ensure_ascii=False))

    def test_T07b_no_compartilhavel_de_bruto_privado_exige_sanitizacao(self):
        cap = ig.extrair_capsula(capsula([{"tipo": "decisao", "titulo": "Decisão limpa", "texto": "sem identificador",
                                           "msgs": ["m0001"], "p0": "INT", "supernos": ["S1"]}]))
        m = ig.mapa_conversa(cap, msgs())
        self.assertEqual(m["nos"][0]["fontes"], [])
        novo = ig.aplicar_candidatos(BASE, m, ig.reconciliar(BASE, m))
        self.assertEqual(mp.validar(novo)["erros"], [])
        self.assertTrue(any(e.get("transformacao") == "sanitizacao" for e in novo["arestas"]))
        # sem a aresta declarada, citar o bruto privado direto e lavagem de classe
        n = next(x for x in novo["nos"] if x["id"] == m["nos"][0]["id"])
        n["fontes"] = [m["fonte"]["alias"]]
        novo["arestas"] = [e for e in novo["arestas"] if e.get("transformacao") != "sanitizacao"]
        self.assertTrue(any(e.startswith("P0_LAVAGEM") for e in mp.validar(novo)["erros"]))

    def test_proposta_so_entra_no_mapa_apos_aprovacao(self):
        cap = ig.extrair_capsula(capsula([{"tipo": "decisao", "titulo": "Decisão proposta X", "texto": "limpa",
                                           "msgs": ["m0001"], "p0": "INT", "supernos": ["S1"], "visoes": ["M1"]}]))
        m = ig.mapa_conversa(cap, msgs())
        novo = ig.aplicar_candidatos(BASE, m, ig.reconciliar(BASE, m))
        v = mp.compilar(novo, "claude")
        self.assertNotIn("Decisão proposta X", v["M1"])
        self.assertIn("1 nós de 1 conversa(s)", v["M1"])
        next(n for n in novo["nos"] if n["id"] == m["nos"][0]["id"])["aprovado"] = True  # titular aprovou
        self.assertIn("Decisão proposta X", mp.compilar(novo, "claude")["M1"])

    def test_T08_injecao_vai_para_quarentena(self):
        grava(self.bruto, msgs(injetar=True))
        r = ig.arquivar(self.bruto, self.arq)
        self.assertEqual(r["status"], "VERIFIED")  # bruto preservado intacto
        cap = ig.extrair_capsula(capsula([{"tipo": "tarefa", "titulo": "Tarefa da mensagem 3", "msgs": ["m0003"]}]))
        m = ig.mapa_conversa(cap, ig.ler_bruto(os.path.join(self.arq, r["arquivo"])))
        self.assertEqual(m["quarentena"], [m["nos"][0]["id"]])
        d = ig.reconciliar(BASE, m)
        self.assertEqual(d["operacoes"][0]["op"], "quarentena")
        self.assertEqual(ig.checkpoint(r, m, d)["status"], "PARTIAL")

    def test_T09_sem_bruto_e_FAILED(self):
        r = ig.arquivar(os.path.join(self.d, "nao_existe.jsonl"), self.arq)
        self.assertEqual(r["status"], "FAILED")
        self.assertEqual(ig.checkpoint(r, None, None)["status"], "FAILED")

    def test_T10_inventario_por_plataforma(self):
        grava(self.bruto, msgs())
        ig.arquivar(self.bruto, self.arq)
        b2 = os.path.join(self.d, "b2.jsonl")
        grava(b2, msgs(3, conv="chatgpt:sint-9"))
        ig.arquivar(b2, self.arq)
        ig.arquivar(None, self.arq)
        inv = ig.inventario(self.arq)
        self.assertEqual(inv["claude"]["conversas"], 1)
        self.assertEqual(inv["chatgpt"]["VERIFIED"], 1)
        self.assertEqual(inv["desconhecida"]["FAILED"], 1)

    def test_uso_util_acumula_uma_vez_por_conversa(self):
        base = json.loads(json.dumps(BASE))
        base["nos"].append({"id": "F-X", "tipo": "fonte", "natureza": "referencia", "titulo": "Fonte X", "texto": "",
                            "p0": "INT", "alias": "FX", "visoes": [], "supernos": [], "lentes": [], "fontes": [],
                            "aponta": [], "estado": "oficial", "evidencia": "verificada", "vigencia": "ativa"})
        txt = "<<<CAPSULA " + json.dumps({"formato": "persona-capsula-1", "conversa": CONV, "nos": [],
                                         "consultados": ["FX"], "aproveitados": [{"alias": "FX", "msg": "m0002"}]}) + " CAPSULA>>>"
        m = ig.mapa_conversa(ig.extrair_capsula(txt), msgs())
        novo = ig.aplicar_candidatos(base, m, ig.reconciliar(base, m))
        novo = ig.aplicar_candidatos(novo, m, ig.reconciliar(novo, m))  # reprocessar não conta de novo
        fx = next(n for n in novo["nos"] if n.get("alias") == "FX")
        self.assertEqual((fx["uso_consultas"], fx["uso_aproveitamentos"]), (1, 1))

    def test_preferencia_circunstancial_por_padrao(self):
        cap = ig.extrair_capsula(capsula([{"tipo": "preferencia", "titulo": "Prefere X hoje", "msgs": ["m0001"]}]))
        self.assertTrue(ig.mapa_conversa(cap, msgs())["nos"][0]["circunstancial"])

    def test_capsula_ausente_ou_de_outra_conversa(self):
        with self.assertRaises(ig.IngestError):
            ig.extrair_capsula("sem bloco")
        cap = ig.extrair_capsula(capsula([], conv="claude:outra"))
        with self.assertRaises(ig.IngestError):
            ig.mapa_conversa(cap, msgs())


if __name__ == "__main__":
    unittest.main()
