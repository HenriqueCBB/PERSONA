"""Roda o gate P0 sobre todos os arquivos versionados (git ls-files). Exit 1 se algo nao puder sair.
O corpus de teste SINTETICO (tests/corpus_p0.py) e o proprio gate sao excluidos por conterem padroes de proposito."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from persona_lab.p0_gate import checar

EXCLUIR = {"tests/corpus_p0.py", "tests/test_p0_gate.py", "src/persona_lab/p0_gate.py"}
arquivos = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
ruins = 0
for f in arquivos:
    if f in EXCLUIR or not os.path.isfile(f):
        continue
    try:
        with open(f, encoding="utf-8") as fh:
            achados = checar(fh.read())
    except UnicodeDecodeError:
        continue
    if achados:
        ruins += 1
        print(f"BLOQUEADO {f}: {sorted({a['tipo'] for a in achados})}")
print(f"p0_scan: {len(arquivos)} arquivos, {ruins} bloqueados")
sys.exit(1 if ruins else 0)
