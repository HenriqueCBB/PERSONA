#!/usr/bin/env bash
# CI-01: mesmos passos do GitHub Actions, executaveis localmente. Exit != 0 = PR reprovado.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "python: $(python3 --version)"
echo "== 1/4 compilacao"
python3 -m compileall -q src tests
echo "== 2/4 gate P0 sobre os arquivos versionados (nada restrito no repositorio)"
python3 scripts/p0_scan_repo.py
echo "== 3/4 testes (ResourceWarning vira erro)"
python3 -W error::ResourceWarning -m unittest discover -s tests -v
echo "== 4/4 lint opcional"
if command -v ruff >/dev/null 2>&1; then ruff check src tests scripts; else echo "ruff ausente: pulado"; fi
echo "CI OK"
