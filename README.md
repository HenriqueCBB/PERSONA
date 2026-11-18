# PERSONA — laboratório de código (CANDIDATO)

Código de laboratório do método PERSONA: **somente biblioteca padrão do Python e dados 100% sintéticos**.
Nada aqui é versão oficial; a base canônica continua fora deste repositório. Toda entrega é CANDIDATA
até revisão independente e aprovação do titular.

| Módulo | Tarefa | O que faz |
|---|---|---|
| `src/persona_lab/p0_gate.py` | SEC-01 | Gate de saída P0: bloqueia identificadores BR (com DV), credenciais e injeção de instruções. Fail-closed. |
| `src/persona_lab/taskcard.py` + `schemas/taskcard.schema.json` | HAND-01 | Task card com estados `RESERVED→RUNNING→EVIDENCE_READY→AUDITED→HUMAN_APPROVED→RELEASED`, checkpoint atômico e retomada sem repetir efeitos após `SIGKILL`. |
| `src/persona_lab/mem_bench.py` | MEM-01 | Braços de recuperação sem LLM (A texto integral, C BM25, D BM25 + ligações) e avaliador com gabarito separado. Braços com LLM: PENDENTE. |
| `.github/workflows/ci.yml`, `scripts/ci_local.sh` | CI-01 | CI mínima: compilação, varredura P0 do repositório, testes (ResourceWarning = erro), lint. |

Rodar localmente: `bash scripts/ci_local.sh` (o mesmo script roda no GitHub Actions).

Relatório da rodada: [`docs/CODEX-20261118-RELATORIO.md`](docs/CODEX-20261118-RELATORIO.md).
Regras para agentes: [`AGENTS.md`](AGENTS.md). Segurança: [`SECURITY.md`](SECURITY.md).
