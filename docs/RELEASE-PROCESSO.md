# Processo de release do Eco

Tudo acontece no GitHub Actions, por tag. Não há segredo além do `GITHUB_TOKEN` automático.

## Fluxo

1. No código: atualize `installer/VERSION` (ex.: `0.2.0`) e crie a seção `## [0.2.0] - AAAA-MM-DD` no `CHANGELOG.md` (obrigatória, com data e conteúdo).
2. Faça push na `master` e espere o workflow **CI** ficar verde.
3. Marque e envie a tag: `git tag v0.2.0 && git push origin v0.2.0`.
4. O workflow **Release** roda as etapas abaixo, cada uma em um job separado. A release só é criada se **todas** passarem.
5. No fim, o Release dispara o workflow **Site (GitHub Pages)**, que regenera `releases.json` da release real e republica o site.

## Etapas do workflow Release (`.github/workflows/release.yml`)

| # | Job | O que verifica |
|---|---|---|
| 1 | Versão | tag `vX.Y.Z` = `installer/VERSION` = seção do `CHANGELOG`; o commit da tag está na `master` |
| 2 | Lint | `compileall -W error`, sintaxe de todos os `.ps1`, actionlint (binário com SHA-256 fixado) |
| 3 | Testes unitários | `tests/*.py` sem GPU/microfone/login (`tools/ci/tests-manifest.json`) |
| 4 | Testes de interface | suítes de UI offscreen em 100% escuro e 150% claro |
| 5 | Schema | `schema.uncovered_fields()` vazio |
| 6 | Privacidade | segredos, e-mails pessoais, caminhos pessoais (aviso) e **autores de todos os commits** (só e-mail `noreply` do GitHub) |
| 7 | Licenças e wheels | `requirements.lock.txt` coerente com o `.in`, todas as linhas com hash, `pip --require-hashes`, `THIRD-PARTY.txt` |
| 8 | Build | `installer/build.ps1` em `windows-latest` (Inno Setup, lzma2/max); whisper.cpp vem de pacote fixado por SHA-256 |
| 9 | Teste-fumaça | runner limpo: confere SHA-256, instala em silêncio em pasta temporária, `tools`, `config`, `doctor`, desinstala e confere a limpeza |
| 10 | Publicar | só se 1–9 = sucesso; atestado de procedência; cria como **rascunho**, sobe `Eco-Setup-<v>.exe`, `.sha256`, `Eco-Setup.exe` (alias estável) e `.sha256`, e só então publica |

Execução manual (**Actions → Release → Run workflow**) é um **ensaio**: roda as etapas 1–9 e não publica.

## Reexecutar uma etapa

Abra a execução em **Actions** e use **Re-run failed jobs** (só as etapas que falharam e as que dependem delas). Se a causa estava no código, corrija, atualize a tag: `git push --delete origin v0.2.0`, `git tag -f v0.2.0 <commit>`, `git push origin v0.2.0`.

## O instalador não cabe no CI? (honesto)

O build usa binários do whisper.cpp compilados com Vulkan (precisam de Visual Studio Build Tools e Vulkan SDK). O CI **não recompila**: baixa `eco-whispercpp-vulkan-v1.9.5-win-x64.zip` da release `deps-whispercpp-v1.9.5` do próprio repositório e confere o SHA-256 de `tools/ci/deps.lock.json`. Para publicar o pacote uma única vez:

```powershell
gh release create deps-whispercpp-v1.9.5 <pasta>\eco-whispercpp-vulkan-v1.9.5-win-x64.zip --title "Dependências: whisper.cpp v1.9.5 (Vulkan)" --notes "Binários pré-compilados usados pelo build. SHA-256 fixado em tools/ci/deps.lock.json." --prerelease
```

Alternativa se o build no runner falhar: runner self-hosted nesta máquina (`gh` > Settings > Actions > Runners; só com tags protegidas) ou construir localmente com `installer\build.ps1` e usar `tools\ci\smoke_installer.ps1` + `tools\ci\make_release_assets.ps1` antes de publicar à mão com `gh release create`.

## Site e download direto

- O botão **Baixar** aponta para `https://github.com/<dono>/<repo>/releases/latest/download/Eco-Setup.exe`. Essa URL responde 302 para o CDN com `Content-Disposition: attachment`, então o navegador **baixa na hora, sem abrir a página do repositório**. O atributo `download` do HTML é ignorado entre origens; não é ele que faz o download.
- Versão, data, tamanho e SHA-256 vêm de `site/releases.json`, gerado por `tools/ci/gen_releases_json.py` da release real; o `.sha256` publicado precisa coincidir com o `digest` da API.
- O site é republicado quando `site/**` muda na `master`, quando uma release é publicada e manualmente. O Release chama o Pages por `workflow_dispatch` (eventos feitos com `GITHUB_TOKEN` não disparam outros workflows).

## Proteções recomendadas

- Branch `master`: exigir os checks do **CI** antes do merge.
- Tags `v*`: ruleset para só administradores criarem/apagarem (Settings → Rules → Rulesets, target *tag*).
- Actions: permissões padrão só leitura (já declaradas por job); ações fixadas por SHA (o Dependabot atualiza).
- Instalador sem assinatura de código: o SmartScreen pode avisar; a verificação é o SHA-256 e `gh attestation verify`.

## Testes locais dos scripts

`python -I tools/ci/check_version.py --tag v0.2.0`, `check_lock.py`, `schema_check.py`, `scan_repo.py --history`, `run_tests.py --group unit`, `gen_releases_json.py` (com release de mentira), `smoke_installer.ps1` (instalador real, pasta temporária). O que só dá para provar no GitHub: o build no `windows-latest`, o Pages e o atestado.
