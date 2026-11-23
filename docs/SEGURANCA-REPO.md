# Varredura de segredos e dados pessoais antes de publicar (2026-11-22)

Escopo: 268 arquivos rastreados no HEAD (`47fbf68`) e os 33 commits de todo o histórico (`git grep` em todas as revisões,
`git rev-list --objects --all`, `git log --all`). Valores sensíveis estão mascarados aqui.

## Resumo
- Nenhum segredo real encontrado: sem chaves (`sk-`, `ghp_`, `hf_`, `AKIA`, JWT, chave privada), sem senhas/tokens
  literais, sem URL com credencial, sem IPs privados, em todo o histórico.
- Nunca foram a commit: `data\`, `logs\`, `models\`, `bin\`, `venv\`, `work\`, `.remotion\`, `@AutomationLog.txt`, `*.db`,
  `*.wav`, `*.gguf`, `*.exe`, `*.zip`, `*.pyc`, `tests\audio_*`. (Conferido com `git log --all --name-only`.)
- Tamanho: `git count-objects -vH` = 631 objetos soltos, **1,39 MiB**, sem pacotes. Maior blob do histórico: 339 KB
  (`installer/assets/wizard-246x459.bmp`); maior fonte: ~50 KB. Sem binários grandes no histórico.
- `.gitignore` reescrito (raiz). Foram removidos do índice (continuam no disco) 5 arquivos de log de bancada:
  `tests/b2.err`, `tests/b2.log`, `tests/bench_reduced.log`, `tests/bench_small.err`, `tests/bench_small.log`
  (sem dados pessoais; só limpeza). Continuam no histórico, inofensivos.

## Achados
| # | Local | Tipo | Gravidade | Ação sugerida |
|---|---|---|---|---|
| 1 | Todos os commits (autor e committer) | E-mail pessoal do autor (mascarado) e usuário `brunocsilva41` | Média (ficará público) | Decisão do dono: aceitar, ou usar o e-mail `noreply` do GitHub nos próximos commits (`git config user.email`). Mudar os antigos exigiria reescrever o histórico (não feito; antes de publicar é o único momento barato) |
| 2 | `src/bench_validate.py` linhas 12-13 (desde `1b0c4b9`) | Caminho `C:\Users\<nome completo>\OpenBot\Shared\...` (nome de usuário do Windows) | Baixa | Em `src\**`, não alterado. Trocar por variável de ambiente/argumento; ou apagar o script de bancada. Fica no histórico |
| 3 | `src/f2/record_usuario.py` linha 2 | Modelo do microfone/headset pessoal (docstring) e nome de arquivo com o primeiro nome | Baixa | Em `src\**`, só reportado |
| 4 | `config.toml` linhas 7-8 | Nome do headset do dono em exemplo comentado | Baixa | Trocar por um exemplo genérico (arquivo fora do meu escopo; decisão do dono) |
| 5 | `docs/*.md`, `PLANO.md`, `src\**` (docstrings/comentários) | Primeiro nome do dono ("usuário") em dezenas de linhas; nomes de pastas pessoais `capturas/...` em `docs/DESIGN-DECISOES.md` (linhas 3 e 159) e hardware real (CPU/GPU, `F:\Eco`) em `PLANO.md` | Baixa | Aceitar ou revisar. O nome aparece como "dono/usuário" no texto; não é segredo |
| 6 | `src/jarvis/core/auditkey.py`, `src/jarvis/memory/secrets.py` | Falso positivo de busca por "key/secret": código que gera/guarda chave em `data\` e filtro de segredos | Nenhuma | Nenhuma; conferido que não há valor literal |
| 7 | `installer/Eco.iss:222` | Falso positivo de e-mail (`GlobalMemoryStatusEx@kernel32.dll`) | Nenhuma | Nenhuma |
| 8 | `installer/manifest.json` | URLs de download com hash de revisão (Hugging Face/ModelScope), sem token | Nenhuma | Nenhuma |
| 9 | `tests/stt_test.jsonl`, `tests/stt_results_piper.jsonl`, `tests/frases_pt.txt` | Frases de teste e transcrições (áudio sintético Piper/SAPI, sem voz do dono) | Nenhuma | Nenhuma |

## Estado do disco (não rastreado, protegido por `.gitignore`)
`data\jarvis.db` (conversas e memória reais), `logs\audit.jsonl` e demais logs, `data\control\*.key` (chave do YOLO),
`bin\` e `models\` (binários), `work\`, `.remotion\`, `@AutomationLog.txt`, `installer\dist|staging|wheels|tools|cache`,
`tests\audio_piper`, `tests\audio_sapi` e (quando existir) `tests\audio_usuario` (voz do dono). Verificado com
`git check-ignore -v` por amostra. Atenção: as regras `*.wav`, `*.log` e `*.db` valem para o repositório inteiro.

## Não verificado
- Conteúdo binário (PNG/BMP/ICO) em busca de metadados pessoais (EXIF); só tamanhos foram vistos.
- Arquivos novos de outros agentes ainda não commitados (`src\**`): a varredura é do HEAD e do histórico.
- Ferramentas dedicadas (gitleaks/trufflehog) não foram executadas; a busca foi por padrões com `git grep`. Recomenda-se
  rodar `gitleaks detect` uma vez antes do primeiro push.
- Dados pessoais em texto livre (ex.: nomes de terceiros em exemplos): só amostragem.

## Antes do primeiro push (decisões do dono)
1. Definir o e-mail público dos commits (achado 1) e se aceita o histórico atual.
2. Decidir sobre o caminho pessoal em `src/bench_validate.py` e o headset em `config.toml`/`record_usuario.py`.
3. Definir a licença (README: PENDENTE) e revisar GPL-3.0 do piper-tts.
