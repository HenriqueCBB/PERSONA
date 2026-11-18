import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from persona_lab import mapa as mp

ID_FALSO = "1" + "x" * 32 + "Ab9"  # formato de ID do Drive, sintetico


def no(i, tipo, natureza, titulo, texto="", p0="INT", visoes=(), supernos=(), lentes=(), fontes=(), aponta=(),
       estado="oficial", evidencia="declarada", vigencia="ativa", **kw):
    d = {"id": i, "tipo": tipo, "natureza": natureza, "titulo": titulo, "texto": texto, "p0": p0,
         "visoes": list(visoes), "supernos": list(supernos), "lentes": list(lentes), "fontes": list(fontes),
         "aponta": list(aponta), "estado": estado, "evidencia": evidencia, "vigencia": vigencia}
    d.update(kw)
    return d


def registro():
    return {"meta": {"versao": "teste"}, "lentes": {"L1": "Ciência", "L2": "Sociopolítica"},
            "nos": [
                no("F-OPE", "fonte", "referencia", "Operador epistêmico", alias="OPE", drive_id=ID_FALSO),
                no("F-MOD3", "fonte", "referencia", "Módulo restrito", p0="REST", alias="M03", drive_id=ID_FALSO[::-1]),
                no("F-PRIV", "fonte", "referencia", "Nota pessoal", p0="PRIV", alias="NOTA", drive_id="1" + "y" * 35),
                no("R-NUCLEO", "restricao", "regra", "Núcleo", "Português; não inventar fonte.", visoes=["M2"], fontes=["OPE"]),
                no("G-RESUMO", "restricao", "roteamento", '"/resumo" → OPE', "síntese densa.", visoes=["M2"], aponta=["OPE"],
                   fontes=["OPE"]),
                no("E1", "restricao", "proibicao", "Expor dado sensível", visoes=["M2"], fontes=["OPE"]),
                no("ST-V", "afirmacao", "estado", "Versão oficial v9.7", visoes=["M1"], fontes=["OPE"]),
                no("S1-SIN", "afirmacao", "sintese", "Engenharia", "memória e código.", supernos=["S1"], visoes=["M3"],
                   fontes=["OPE"]),
                no("S6-SIN", "afirmacao", "sintese", "Trabalho institucional", "conteúdo restrito.", supernos=["S6"],
                   visoes=["M3"], aponta=["M03"]),
                no("T-S1-A", "afirmacao", "fato", "Tema mapas", "registro único.", supernos=["S1"], lentes=["L1"],
                   visoes=["M3"], fontes=["OPE"]),
                no("T-S6-A", "afirmacao", "fato", "Tema restrito", "não sai.", p0="REST", supernos=["S6"], lentes=["L2"],
                   visoes=["M3"], fontes=["M03"]),
                no("H-X", "afirmacao", "hipotese", "Hipótese cruzada", "mecanismo X.", supernos=["S1", "S5"],
                   lentes=["L1", "L2"], visoes=["M4"], fontes=["OPE"], evidencia="hipotetica"),
                no("P-PESSOAL", "preferencia", "preferencia", "Preferência pessoal", "detalhe pessoal.", p0="PRIV",
                   visoes=["M2"], fontes=["NOTA"]),
                no("SEMFONTE", "afirmacao", "fato", "Afirmação sem fonte", supernos=["S1"], visoes=["M3"]),
            ],
            "arestas": [{"tipo": "ponte", "de": "T-S1-A", "para": "S6-SIN", "motivo": "m", "mecanismo": "x"}]}


class TestValidacao(unittest.TestCase):
    def test_registro_valido(self):
        v = mp.validar(registro())
        self.assertEqual(v["erros"], [])
        self.assertIn("SEM_PROVENIENCIA SEMFONTE", v["avisos"])

    def _erro(self, mut, prefixo):
        r = registro()
        mut(r)
        erros = mp.validar(r)["erros"]
        self.assertTrue(any(e.startswith(prefixo) for e in erros), erros)

    def test_erros_bloqueiam(self):
        self._erro(lambda r: r["nos"].append(copy.deepcopy(r["nos"][3])), "ID_DUPLICADO")
        self._erro(lambda r: r["nos"][3].update(tipo="claim"), "TIPO_INVALIDO")
        self._erro(lambda r: r["nos"][3].pop("p0"), "P0_AUSENTE")
        self._erro(lambda r: r["arestas"].append({"tipo": "sustenta", "de": "F-OPE", "para": "NAOEXISTE"}), "ARESTA_PENDENTE")
        self._erro(lambda r: r["arestas"].append({"tipo": "depende_de", "de": "F-OPE", "para": "R-NUCLEO"}), "ARESTA_DOMINIO")
        self._erro(lambda r: r["arestas"].append({"tipo": "substitui", "de": "E1", "para": "ST-V", "motivo": "revisao"}),
                   "SUBSTITUI_INVALIDA")
        self._erro(lambda r: r["arestas"].append({"tipo": "ponte", "de": "T-S1-A", "para": "S1-SIN", "motivo": "m",
                                                  "mecanismo": "x"}), "PONTE_MESMO_SUPERNO")
        self._erro(lambda r: r["arestas"].append({"tipo": "relacionado_a", "de": "T-S1-A", "para": "H-X"}),
                   "RELACIONADO_SEM_MOTIVO")
        self._erro(lambda r: r["nos"][3].update(texto="x" * 500), "TEXTO_LONGO")
        self._erro(lambda r: r["nos"][3].update(fontes=["NAOHA"]), "FONTE_INEXISTENTE")

    def test_p0_nao_lava(self):
        self._erro(lambda r: r["nos"][9].update(fontes=["M03"]), "P0_LAVAGEM")
        r = registro()  # derivado anonimizado pode baixar a classe
        r["nos"].append(no("ANON", "afirmacao", "fato", "Agregado anonimizado", supernos=["S6"], visoes=["M3"]))
        r["arestas"].append({"tipo": "deriva_de", "de": "ANON", "para": "F-MOD3", "transformacao": "anonimizacao"})
        self.assertEqual(mp.validar(r)["erros"], [])

    def test_migracao_v96(self):
        self.assertEqual(mp.MIGRACAO["hypothesis"], ("afirmacao", "hipotese"))
        self.assertTrue(all(t in mp.TIPOS for t, _ in mp.MIGRACAO.values()))


class TestCompilacao(unittest.TestCase):
    def test_visoes_e_tetos(self):
        v = mp.compilar(registro(), "claude", utc="2026-11-18T00:00Z")
        for k in ("M1", "M2", "M3", "M4", "M5", "PACOTE"):
            self.assertTrue(v[k].startswith("# PERSONA"), k)
        self.assertEqual(v["meta"]["estouros"], [])
        self.assertIn("S1", v["M3_TEMAS"])
        self.assertEqual(v["PACOTE"].count("# PERSONA"), 3)

    def test_restrito_so_ponteiro_mesmo_para_claude(self):
        v = mp.compilar(registro(), "claude")
        self.assertNotIn("não sai.", v["M3_TEMAS"]["S6"])
        self.assertIn("conteudo so na fonte [M03]", v["M3_TEMAS"]["S6"])

    def test_privado_visivel_para_claude_e_some_para_externo(self):
        self.assertIn("detalhe pessoal", mp.compilar(registro(), "claude")["M2"])
        ext = mp.compilar(registro(), "externo")
        todo = "\n".join(ext[k] for k in ("M1", "M2", "M3", "M4", "M5")) + "\n".join(ext["M3_TEMAS"].values())
        for proibido in ("detalhe pessoal", "Preferência pessoal", "Tema restrito", ID_FALSO):
            self.assertNotIn(proibido, todo)

    def test_gemini_exige_codificacao(self):
        with self.assertRaises(mp.RegistroError):
            mp.compilar(registro(), "gemini")
        g = mp.compilar(registro(), "gemini", codificado=True)
        self.assertNotIn("detalhe pessoal", g["M2"])

    def test_registro_invalido_nao_compila(self):
        r = registro()
        r["nos"][3].pop("p0")
        with self.assertRaises(mp.RegistroError):
            mp.compilar(r, "claude")

    def test_apelido_economiza_tokens(self):
        a = mp.compilar(registro(), "claude")
        b = mp.compilar(registro(), "claude", ids_inline=True)
        self.assertLess(a["meta"]["tokens"]["PACOTE"], b["meta"]["tokens"]["PACOTE"])
        self.assertIn(ID_FALSO, a["M5"])  # o ID completo continua no mapa de consulta

    def test_cruzamento_e_fila(self):
        v = mp.compilar(registro(), "claude")
        self.assertIn("- S1: Ciê 2", v["M4"])  # densidade supernó × lente
        self.assertIn("Lacunas", v["M4"])
        self.assertIn("Hipótese cruzada", v["M4"])
        self.assertIn("T-S1-A ↔ S6-SIN", v["M4"])  # ponte explícita
        self.assertIn("SEMFONTE", v["M1"])

    def test_cobertura(self):
        v = mp.compilar(registro(), "claude")
        c = mp.cobertura(v["PACOTE"], ["/resumo", "gatilho inexistente"])
        self.assertEqual(c["presentes"], 1)
        self.assertEqual(c["faltam"], ["gatilho inexistente"])


if __name__ == "__main__":
    unittest.main()
