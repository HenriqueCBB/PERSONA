# CODEX-20261118 — Relatório de execução (CANDIDATO)

- **Executor:** Claude (sessão de código na nuvem, Opus), no papel de executor de engenharia do pacote CODEX-20261118. Acionado pelo titular em 18/11/2026.
- **Independência:** não sou autor do controlador v2 (ChatGPT) nem do verificador de 22 testes do Gemini. **Sou da mesma família de modelo que o autor do pacote R5 e do verificador R4 (Claude).** O R5 pedia "quem verifica não pode ser o Claude". Esta reprodução vale como **execução reprodutível com logs e hashes**, não como auditoria independente de outro fornecedor. Para fechar V1–V3 de forma independente, o ChatGPT ou o Gemini precisam repetir por amostragem.
- **Janela:** 2026-11-18, cerca de 02:36 a 02:55 UTC. Ambiente: contêiner Linux, Python 3.13.18, só biblioteca padrão.
- **Estado:** tudo CANDIDATO. Nada oficial foi alterado: v9.7, Mapa Vivo v0.4, QUADRO e módulos ficaram intactos.
- **P0:** não abri os módulos 03, 05 e 07, nem pastas PRIVADO, Takeout ou WhatsApp. O repositório recebe só código novo e dados sintéticos. Os artefatos de terceiros (R5, v2, verificadores) ficam fora do git e são citados só pelo SHA-256.

Regra usada abaixo: **EXECUTEI** = rodei aqui, com log; **LI** = li o arquivo; **NÃO FIZ** = não executado, com o motivo.

## Resumo

| Etapa | Tarefa | Resultado | Esperado × obtido |
|---|---|---|---|
| E1 | CX-1 / V1–V3 | **OK, com uma lacuna** | 112/112 testes OK; mutação **344/345** (99,7%); test_quadro 17/17; test_persona_saida 8/8; patch F-BIAS-4 a765f445… → **c8614ec9…**. O 22/22 do R4 na base real **NÃO FOI FEITO**, porque exige os módulos 03/05/07 (restritos). |
| E2 | CX-2 / VER-01 | **OK** | R4: 7/7 controles fail-closed. O verificador de 22 do Gemini dá **22/22 em base corrompida** (falso positivo confirmado) e aceita rejeição pelo motivo errado. |
| E3 | CX-3 / DB-01 | **OK, com 2 limites** | 75/75 (36+23+16) reproduzidos. 6/6 testes adversariais novos. Limites: sem âncora externa, truncamento coerente e rollback de arquivo passam despercebidos. Os testes originais emitem ResourceWarning, e `reproduce_a1_a4_v1.py` falha por causa do caminho fixo `/mnt/data`. |
| E4 | CX-4 / SEC-01 | **OK no corpus próprio** | Gate novo: 0 FN e 0 FP em 70 casos sintéticos (35 positivos, 35 negativos). O `persona_saida.py` do R5 deixa passar 17 dos 35 positivos (48,6%). |
| E5 | CX-6 / HAND-01 | **OK** | Schema e executor. SIGKILL em 3 pontos, com retomada sem efeito repetido nem perdido. O teste achou e corrigiu um defeito meu (linha parcial no diário). |
| E6 | CX-5 / CI-01 | **OK localmente** | Workflow com `permissions: read` e actions fixadas por SHA. Dois "PRs ruins" reprovam (exit 1). Não houve execução no GitHub Actions. |
| E7 | CX-7 / MEM-01 | **OK, sem LLM** | Nova semente 20261118, 90 casos (2k/8k/32k palavras). A = 100% com 2.000 a 32.000 palavras; C = 86,7% com 64 palavras; **C+vizinho = D = 100% com 93 palavras**. As ligações temáticas não acrescentam ganho além do tratamento de borda. Os braços com LLM ficaram PENDENTES. |
| E8 | CX-9 | **NÃO FIZ** | Exige liberação do titular, e o código do cofre não estava no pacote. |

## E1 — CX-1 (V1–V3 do QUADRO)

- **EXECUTEI** a conferência de hashes:
  - ZIP R5 `e2fc19e1…b595`, igual ao esperado;
  - `sha256sum -c SHA256SUMS.txt`: 17/17 OK;
  - controlador `a89d8a03…2bad`, igual ao esperado;
  - verificador R4 `8dfe0fff…522d`, igual ao esperado.
- **EXECUTEI** a suíte do controlador: `python3 -m unittest -v persona_controle_v2_candidato test_patch_v2_regression test_v2_adversarial test_v3_mutacao` → **Ran 112, OK, exit 0**.
- **EXECUTEI** a mutação: `python3 tools/persona_mutacao.py --src controle_v3 --module persona_controle_v2_candidato.py --targets Controller,canonical,digest --cmd "…" --jobs 4`.
  - Resultado: 345 válidos, 344 mortos, 1 sobrevivente (#145, L371, TROCA_AND_OR). Levou cerca de 6 min.
  - Por operador: TROCA_AND_OR 31/32; todos os outros 100%.
- **Sobrevivente #145: confirmo que é equivalente**, por análise própria:
  - o mutante troca `not releases or releases[0][0] != 0` por `not releases and …`;
  - com a lista vazia, o mutante tenta ler `releases[0]`, gera IndexError, cai no `except` e devolve False, igual ao original;
  - com a lista não vazia, a linha seguinte (`rev != i` com `i=0`) devolve False para revisão inicial diferente de 0;
  - o comportamento observável é o mesmo nos dois casos.
- **EXECUTEI** `test_quadro`: Ran 17, OK. E `test_persona_saida`: Ran 8, OK.
- **EXECUTEI** o F-BIAS-4:
  - o manifesto v9.7 baixado tem SHA `a765f445…649d`, igual ao esperado;
  - `aplicar_fbias4.py` grava uma cópia com SHA **`c8614ec9…f47a`**, igual ao esperado;
  - o diff tem só 1 linha, a âncora F-BIAS-4 (519a0991… → f7f0888a…);
  - a segunda execução é recusada (não sobrescreve).
  - O manifesto tem 53 âncoras, todas em SKILL.md, 01 e 04, nenhuma em módulo restrito.
- **NÃO FIZ** o "R4 dá 22/22 na v9.7.1 real".
  - Motivo: `verify_skill_directory` lê obrigatoriamente os módulos 03, 05 e 07, que contêm dados institucionais e pessoais restritos. A regra 2 do pacote proíbe abri-los.
  - Também não versionei o verificador: o próprio código tem valores institucionais e nomes de terceiros chumbados (checagens B11/T18).
  - Quem tem acesso legítimo à base pode rodar: `python3 verificador_v9_7_candidato_claude_r4.py` dentro da pasta da skill com o manifesto v9.7.1.

## E2 — CX-2 (VER-01): controles negativos T18–T20

- Harness `test_ver01_failclosed.py` (no ZIP do Drive, não no git):
  - importa cada verificador e troca `verify_skill_directory` por um **oráculo sintético** com as mesmas mensagens de erro;
  - monta uma base 100% sintética.
- O que se testa é a lógica de `run_20_acceptance_and_mutation_tests`: preflight, mutação de fato aplicada e motivo certo.

| Controle | R4 (Claude) | 22 do Gemini |
|---|---|---|
| Base íntegra → 22/22 | OK | OK |
| Base corrompida em T18 (soma) | **falha no preflight** ✔ | **22/22 (falso positivo)** ✘ |
| Base corrompida em T19 (PREF-01) | falha no preflight ✔ | 22/22 ✘ |
| Base corrompida em T20 (sem C19) | falha no preflight ✔ | 22/22 ✘ |
| Verificador insensível | falha ✔ | falha ✔ |
| Rejeição pelo motivo errado | falha ✔ | **22/22** ✘ |
| Mutação sem alvo no texto | falha com "mutação não aplicada" ✔ | falha, mas com mensagem enganosa ("deveria falhar") |

- **Divergência D5 fechada:** o falso positivo existe no verificador do Gemini e foi corrigido no R4. Isso vale para a lógica do harness. A função real sobre a base real continua não executada (ver E1).
- **Defeito do meu próprio harness, achado e corrigido antes de concluir:** `self.fail` dentro de `assertRaises(Exception)` era engolido, o que mascarava 2 falsos positivos.

## E3 — CX-3 (DB-01)

- **EXECUTEI** as suítes do ZIP v2 em cópia temporária:
  - `persona_controle_v2_candidato.py`: Ran 36, OK;
  - `test_patch_v2_regression.py`: Ran 23, OK, com 2 avisos ResourceWarning;
  - `test_v2_adversarial.py`: Ran 16, OK, com 34 linhas de ResourceWarning (conexões sqlite não fechadas nos testes);
  - total **75/75**.
- `reproduce_a1_a4_v1.py` dá **exit 1**: grava em `/mnt/data/...`, caminho fixo. Numa cópia com caminho relativo, os defeitos A1–A4 do v1 são reproduzidos (4/4).
- **Novos testes adversariais** (`test_db01_adversarial.py`, ZIP do Drive). Comando: `python3 -W error::ResourceWarning`, 6/6 OK, sem ResourceWarning.
  - A1: dois **processos** (spawn) fazem commit ao mesmo tempo, em 20 rodadas. Sempre exatamente 1 commit e o outro recebe `STALE_BASE`; histórico válido.
  - A1b: dois processos recebem a mesma mensagem. Resultado `RECEIVED` + `ALREADY_RECEIVED`.
  - A2: ator privilegiado derruba os triggers e trunca a cauda (mensagem e evento). **Com âncora externa: detectado. Sem âncora: aceito** (limite documentado no próprio v2, agora medido).
  - A2b: truncar o evento de commit é detectado sem âncora, e o commit seguinte é bloqueado.
  - A3: rollback do arquivo SQLite para um snapshot antigo. **Detectado só com âncora externa.**
  - A3b: fork divergente (dois ramos internamente válidos). Detectado pela âncora do ramo oficial.
- **Consequência:** a âncora externa (`anchor()` guardada fora do SQLite) é **obrigatória** para a integridade prometida. Hoje ela não é gravada automaticamente (P1-3 do relatório GitHub).

## E4 — CX-4 (SEC-01): gate de saída P0

- **Código novo:** `src/persona_lab/p0_gate.py`. É compatível com a denylist com sal do R5.
- Camadas:
  - normalização anti-ofuscação (NFKC, largura zero, dígitos largos);
  - CPF e CNPJ com dígito verificador, aceitando espaços e pontuação;
  - RG, NUP, UG/UASG, documento SIAFI, e-mail (inclusive "(at)"), celular;
  - chaves (OpenAI, GitHub, AWS, Google, Slack), Bearer, JWT, chave privada, `senha=<valor>`;
  - injeção: ignorar regras, exfiltração, ação destrutiva, comentário HTML oculto, papel falso de sistema;
  - termos restritos guardados por hash com sal.
- É fail-closed: entrada que não é texto, ou erro interno, conta como bloqueio. Achados mostram só a máscara.
- **Corpus sintético** (`tests/corpus_p0.py`, semente 20261118): 35 positivos e 35 negativos parecidos. Os negativos incluem hashes, IDs do Drive, CPF com DV inválido, texto que *discute* injeção, a frase do SECURITY.md e outros.

| Gate | FN | FP |
|---|---|---|
| `p0_gate.py` (novo) | 0/35 | 0/35 |
| `persona_saida.py` (R5) | **17/35** (CPF ofuscado, RG, e-mail "(at)", JWT, Bearer, chave privada, senha, todas as injeções) | 0/35 |

- Durante o trabalho, a varredura do próprio repositório achou **3 falsos positivos reais** em texto legítimo:
  - uma frase do SECURITY.md;
  - "e-mail" usado como substantivo;
  - o exemplo de atribuição de senha usado neste relatório.
- Corrigi separando "exfiltração" de "ação destrutiva", tirando "e-mail" da lista de verbos e usando placeholder `<valor>`. As 3 frases viraram casos negativos.
- Isto é um sinal honesto de que a taxa de FP em texto real será maior que 0.
- **Limite principal:** o corpus foi escrito pelo mesmo autor do gate, então há risco de sobreajuste. O 0/0 **não** é evidência independente. Próximo passo: corpus cego feito pelo ChatGPT, com gabarito selado. A meta de H-E (≤ 5% de FP) precisa ser medida assim.

## E5 — CX-6 (HAND-01)

- `schemas/taskcard.schema.json` + `src/persona_lab/taskcard.py`.
- Estados `RESERVED→RUNNING→EVIDENCE_READY→AUDITED→HUMAN_APPROVED→RELEASED`, mais BLOCKED e RELEASED_LEASE.
- Regras:
  - auditor diferente do autor;
  - `HUMAN_APPROVED` só com papel `titular` (papel **declarado**, não autenticado);
  - lease com epoch (fencing);
  - `bool` não vale como `int` (classe de defeito do A4).
- Checkpoint atômico (tmp + fsync + replace). Diário de efeitos só-acréscimo, com chave de idempotência por etapa.
- **EXECUTEI** 10 testes, OK:
  - SIGKILL após 1, 5 e 11 de 12 etapas, e a retomada produz exatamente as 12 etapas uma vez cada;
  - crash entre efeito e checkpoint;
  - linha parcial no diário.
- **Defeito meu achado pelo teste e corrigido:** depois de um crash no meio de uma linha, o próximo registro era colado nela.

## E6 — CX-5 (CI-01)

- Arquivos: `pyproject.toml` (sem dependências: o lock de runtime é vazio por desenho), `.github/workflows/ci.yml` e `scripts/ci_local.sh`.
- O workflow:
  - roda em `pull_request` e em push nos ramos de trabalho;
  - tem `permissions: contents: read` e `persist-credentials: false`;
  - fixa as actions por SHA (checkout v4.2.2 `11bd7190…`, setup-python v5.3.0 `0b93645e…`, conferidos via `git ls-remote`);
  - usa matriz Python 3.11, 3.12 e 3.13.
- Passos do script local:
  1. compilação;
  2. **varredura P0 de todos os arquivos versionados**;
  3. testes com ResourceWarning tratado como erro;
  4. ruff.
- **EXECUTEI:**
  - CI limpa: exit 0, 23 testes, 18 arquivos varridos e 0 bloqueados, lint OK;
  - PR ruim 1 (detecção de CPF desligada): 5 FAIL, exit 1;
  - PR ruim 2 (arquivo com CPF sintético válido): `BLOQUEADO docs/vazamento.md: ['CPF']`, exit 1.
- **NÃO FIZ:** `act` (indisponível) e execução no GitHub Actions. O workflow vai rodar no primeiro push do ramo, e o resultado precisa ser conferido lá.

## E7 — CX-7 (MEM-01 / R4.1)

- **EXECUTEI** `persona_r41_benchmark.py --test`: PASSOU, 45 casos.
- Não usei a semente 41 do "piloto cego". O gerador está no próprio ZIP, então o gabarito dele pode ser regenerado (risco já apontado no OP2).
- Gerei um conjunto **novo**: `--seed 20261118 --lengths 2000 8000 32000 --reps 2`, com 90 casos. Separei as entradas do gabarito, e os braços só recebem as entradas.
- **Código novo:** `src/persona_lab/mem_bench.py`. Um extrator determinístico comum a todos os braços, para que a diferença medida seja só a da recuperação.

| Braço | 2k | 8k | 32k | Palavras entregues | Recall de evidência |
|---|---|---|---|---|---|
| A — texto integral | 1,000 | 1,000 | 1,000 | 2.000 / 8.000 / 32.000 | 1,00 |
| C — BM25 top-2, fragmentos de 40 palavras | 0,867 | 0,867 | 0,867 | 64 | 0,867 |
| C+viz — C + fragmento vizinho | 1,000 | 1,000 | 1,000 | 93 | 1,00 |
| D-viz — C + ligações temáticas | 0,933 | 0,933 | 0,933 | 67 | 0,933 |
| D — C + ligações + vizinho | 1,000 | 1,000 | 1,000 | 93 | 1,00 |

- **Leitura:**
  - o erro de C vem de fatos cortados na borda do fragmento;
  - as ligações temáticas recuperam só parte disso (D-viz);
  - o tratamento de borda sozinho (C+viz) já empata com D.
  - Logo, **H-C se confirma nesta escala**: as ligações temáticas não se pagam.
- **Defeito meu achado antes de concluir:** o extrator não atravessava a quebra de linha entre fragmentos e errava casos "temporal". Corrigi e criei teste de regressão.
- **Limites:**
  - o corpus é fácil, porque cada fato tem identificador único (OBJ-/PONTE-) e o BM25 acha por token raro;
  - não testa paráfrase sem ID;
  - o resultado é igual em 2k, 8k e 32k pelo mesmo motivo;
  - não mede raciocínio de LLM: os braços com LLM ficaram PENDENTES (interface `braco_llm_pendente`).
  - A semente está registrada. Para cegamento real, o avaliador deve gerar com semente secreta.

## Riscos e decisões para o titular

1. **O repositório GitHub está PÚBLICO.** O plano do projeto (REL-GITHUB §4, DEC-2) recomenda **privado**. Hoje ele só tem código genérico e dados sintéticos, e a varredura P0 deu 0 bloqueios. Mesmo assim, recomendo mudar para privado em Settings → General → Danger Zone. Eu não tenho essa permissão.
2. **V3 completo (22/22 na v9.7.1 real)** só pode rodar onde os módulos restritos já estão: no ambiente do titular ou numa IA que já tenha acesso autorizado. Basta 1 comando (ver E1).
3. **Âncora externa** do controlador: decidir onde guardar `anchor()` após cada commit (ex.: linha só-acréscimo no QUADRO ou no CANAL). Sem isso, rollback e truncamento coerente não são detectáveis.

## Próximas ações sugeridas

- **ChatGPT:** reproduzir por amostragem 2 resultados com hash (sugiro E1-mutação e E3-A3) e gerar um corpus cego para SEC-01.
- **Claude coordenador:** CL-2 e CL-3 (registrar no QUADRO V1 e V2 como reproduzidos, V3 como parcial e DB-01, SEC-01, HAND-01, CI-01 e MEM-01 como candidatos).
- **Codex:** corrigir o ResourceWarning e o `/mnt/data` do v2, em PR próprio.

Status de tudo: **CANDIDATO**. Esta entrega não é aprovação.
