# Atualização automática

Módulos: `core/updates.py` (descoberta), `core/updater.py` (estado, download, hash, instalação), `core/credstore.py` (token no
Cofre do Windows), `ui/update_flow.py` (orquestração Qt), `ui/update_dialog.py` (pop-up), `ui/settings/updates_page.py` (seção em
Configurações). Testes: `python tests/test_updates.py` (8 testes, sem rede).

## Fluxo
1. **Quando verifica:** `[updates] enabled` liga/desliga tudo. Ao iniciar (`check_on_start`, 20 s depois de subir) e a cada
   `interval_hours` (1–168; o relógio confere de 30 em 30 min). Vive no processo da Ilha/bandeja: precisa de `ui.tray_enabled` ou
   `ui.island_enabled`. Com tudo desligado só o menu manual existe... na bandeja; sem bandeja, use Configurações > Atualizações.
2. **Canal:** `stable` (só versões finais, `/releases/latest`) ou `prerelease` (a maior versão publicada, inclusive pré; rascunhos nunca).
3. **Aviso:** tem versão nova, não foi **ignorada** e o **Lembrar depois** (24 h) venceu → notificação da bandeja + pop-up com notas
   e os botões **Baixar**, **Instalar automaticamente**, **Lembrar depois**, **Ignorar esta versão**. «Verificar atualizações…» da
   bandeja usa o mesmo fluxo (e mostra o pop-up mesmo para versão ignorada; mostra erro ou «já está atualizado»).
   Estado em `data\updates\state.json` (ignorada, lembrar depois, última verificação).
4. **Acesso (repositório privado ou público):** API pública → token somente-leitura no Cofre de Credenciais do Windows
   (alvo `Eco/GitHubUpdateToken`, nunca em config/log) → GitHub CLI (`gh`) logado. Sem nenhuma via num repositório privado a
   mensagem é: «o repositório é privado … não há acesso com login» + como resolver. Nunca diz «atualizado» por falha de acesso.
5. **Download:** `data\updates\download\Eco-Setup-X.exe.part`, com **retomada** (Range; no `gh` também). Só HTTPS, inclusive
   redirecionamentos; o `Authorization` nunca vai para outro host. Ao terminar confere SHA-256 e tamanho e só então renomeia.
6. **SHA-256:** vem do `.exe.sha256` da release, do `digest` da API e/ou do corpo («SHA-256: `…`»). Se houver mais de uma fonte,
   todas devem concordar; nenhuma = recusa. Arquivo com hash errado é apagado. O script auxiliar confere de novo antes de executar.
7. **Instalar:** o script auxiliar é montado em memória e passado por `-EncodedCommand` (nada em disco que um processo comum possa
   trocar antes de rodar elevado). Espera por PID o Eco fechar (o núcleo é encerrado pelo canal normal; **nada é morto à
   força**; passou de 90 s, aborta sem alterar nada), confere o SHA-256 de novo, roda
   `Eco-Setup.exe /VERYSILENT /NORESTART /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /DIR=<instalação>`, grava
   `data\updates\last_install.json` e relança. Dados, config e modelos ficam (instalação por cima, mesmo AppId).
   - **Elevação automática:** se a pasta da instalação não aceita escrita do usuário (Program Files, «para todos os usuários»),
     o script é lançado com `ShellExecuteW` verbo `runas`: o Windows mostra o UAC, o usuário clica Sim e o resto é automático. Já
     elevado, o script copia o instalador para `%windir%\Temp\eco-upd-*` (só administrador escreve), confere o SHA-256 da CÓPIA
     (hash antes e depois da elevação; se mudou, recusa) e executa a cópia.
   - **UAC recusado:** nada é alterado, o Eco não é fechado, o download fica guardado e o botão vira «Tentar de novo».
   - **Relançar sem elevação:** o script cria `data\updates\relaunch.lnk` e o abre com `explorer.exe`, que inicia o Eco com
     o token do usuário normal (não administrador).
   - **Pasta de desenvolvimento:** recusada com explicação em português (não é uma instalação; não há o que atualizar).
   Ao abrir, a bandeja avisa «Eco atualizado» ou o motivo da falha.

## Config (`[updates]`, seção «Atualizações»; grupo `schema.G_UPD`)
`enabled`, `check_on_start`, `interval_hours`, `channel`, `repo` (`dono/repositorio`), `auto_install` (mostra «Instalar
automaticamente»). **Não existe campo de token**: ele só entra pela página (campo mascarado → Cofre do Windows → limpa a tela).

## API do widget das Configurações
```python
from jarvis.ui.settings.updates_page import UpdatesPage
page = UpdatesPage(parent=None, cfg_loader=None, session=None)   # cfg_loader: () -> Config
page.key == "updates"; page.title; page.subtitle
page.ensure_loaded()   # monta sob demanda (não consulta a rede sozinho)
page.filter(query) -> int; page.shutdown(); page.scroll_to(key)
```
Contrato `PageLike` da janela. Os campos `updates.*` do schema são desenhados pela janela (grupo `G_UPD`); a página só cuida de
estado, ações e token. `UpdateSession(cfg_loader, quit_cb, current_override, target_dir, relaunch)` expõe `check/download/install/
ignore/remind_later/cancel` e sinais `checked/progress/ready/failed/installing/state_changed`.

## Prova (22/11/2026, uma pasta de teste, nada na instalação do usuário)
- Release real `v0.1.3` do repositório **privado**: a consulta pública deu 404 e o `gh` entregou a release (via `gh`).
- Instalada a v0.1.2 do build local em uma pasta de teste; versão simulada `0.1.2` → `0.1.3` disponível.
- Download de 184.815.177 bytes interrompido em ~43 MB e **retomado** pelo `.part`; SHA-256 `76b5fac0…b87ed` igual ao da release.
- Hashes divergentes entre fontes foram recusados; instalador adulterado/sem hash não roda (testes).
- Instalação por cima via `apply.ps1` desacoplado (o Python que a lançou já tinha saído): `last_install.json` = `{code 0, version 0.1.3}`,
  VERSION 0.1.3, arquivo de dados do usuário intacto.
- Capturas offscreen: `capturas/ui-prints\updates\` (página e pop-up).

## Não verificado
Clique real em «Instalar automaticamente» com o Eco em execução (fechamento por `quit_cb` + relançamento); relançamento
(`relaunch`) após a instalação; token do Cofre do Windows com repositório privado (provado só pelo `gh`); instalação por cima da
instalação do usuário; instalação «para todos os usuários» (exige admin); tela de pop-up no processo real da Ilha com DPI 150/200%;
canal `prerelease` contra uma release real; falta de rede no meio do download real.
