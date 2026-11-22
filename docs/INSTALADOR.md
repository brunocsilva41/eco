# Instalador e assistente de configuração do Jarvis

Tudo vive em `installer\` (build) e `src\jarvis\setup\` (assistente em Qt). O instalador é um `.exe` do Inno Setup 6; os modelos de IA **não** vão dentro dele.

```
installer\
  VERSION                 única fonte da versão (semver). build.ps1 lê, valida e passa ao Inno
  Jarvis.iss              script do Inno Setup (pt-BR + en)
  build.ps1               build reproduzível (valida, monta staging, prepara runtime, compila, gera hash e notas)
  manifest.json           modelos: nome, URLs (com espelhos), tamanho, SHA-256, licença; mais llama.cpp e Python embutidos
  requirements.lock.in.txt / requirements.lock.txt   pacotes Python travados (o .lock leva --hash=sha256 de cada wheel)
  make_lock.py, make_notices.py, make_assets.py      auxiliares do build
  payload\                Jarvis.cmd (instalado), Jarvis.pyw (atalho sem console), jarvis_boot.py
  assets\                 ícone e imagens do assistente do Inno (geradas dos tokens do tema)
  LICENSE.pt-BR.txt / LICENSE.en.txt                 página de licença do instalador (ver "Pendências")
  cache\ wheels\ staging\ dist\ tools\               gerados (fora do git)
src\jarvis\setup\         assistente: cli, wizard, páginas, baixador, hardware, áudio
```

## Decisões

### Runtime Python: embeddable oficial + wheels travadas, montado no build
- **Escolhido:** Python 3.14.3 *embeddable* (python.org, assinado pela PSF, hash no manifest) + `pip install --target` de wheels baixadas e **travadas por SHA-256** (`requirements.lock.txt`), tudo no **build**. O instalador entrega a pasta pronta em `runtime\python`.
- **Por quê:** (1) `venv` copiado não é relocável (`pyvenv.cfg` e os launchers apontam para `C:\Python314`); (2) criar o venv no pós-instalação exigiria um Python no PC ou baixar um, e `pip install` de ~36 pacotes (PySide6, onnxruntime, ctranslate2...) na máquina do usuário falha por rede, proxy, antivírus e é lento e não reproduzível; (3) com o embeddable o `Jarvis.cmd` instalado roda **sem Python do sistema** e a instalação é determinística (mesmos bytes que foram testados). Custo: instalador maior (~220 a 260 MB comprimido) e ter de refazer o build a cada atualização de dependência (é o desejado: versão travada).
- DLLs do runtime C++ (`msvcp140*`, `vcruntime140*`) que faltarem são copiadas junto (implantação *app-local*, permitida pela Microsoft), para PCs sem o VC++ Redistributable.

### Modelos fora do .exe
Os modelos somam ~3,5 GB (Qwen3-VL 4B + projetor ~2,95 GB, Whisper small ~0,49 GB, voz ~0,06 GB). Empacotar faria um instalador de ~3,7 GB: lento de baixar, impossível de enviar por vários canais, e cada correção de código forçaria baixar tudo de novo. Baixados no primeiro uso eles ficam em `models\`, reaproveitados nas atualizações. Para quem não tem internet existe o **pacote offline**.

## Build

```powershell
F:\Jarvis\installer\build.ps1            # release (lzma2/max)
F:\Jarvis\installer\build.ps1 -Fast      # compressão rápida, para testes
F:\Jarvis\installer\build.ps1 -Relock    # rebaixa as wheels e regera o .lock com hashes
```
Passos: (a) valida `VERSION`; (b) baixa/confere `llama.cpp b12531 Vulkan` e o Python embeddable (SHA-256 do manifest; confere a assinatura PSF do `python.exe`); (c) wheels offline; (d) monta `installer\staging\app` **só** com `src\jarvis` (sem `__pycache__`, testes), `bin\llama-b12531-vulkan` (só o `llama-server.exe` + DLLs), `runtime\python`, `Jarvis.cmd/.pyw`, `VERSION`, `manifest.json`, licenças e `THIRD-PARTY.txt`; **falha** se aparecer `work\`, `logs\`, `data\`, `models\`, `venv\`, `.git`, `tests`; (e) roda o ISCC; (f) grava `dist\Jarvis-Setup-<versão>.exe`, `.exe.sha256` e `Jarvis-Setup-<versão>-NOTAS.md`.

- O build roda em prioridade baixa e espera a carga da CPU baixar (a máquina é compartilhada com renders). `-NoWait` ignora a espera.
- **Inno Setup:** usa `installer\tools\InnoSetup`, depois as instalações do usuário/sistema. Se não houver nenhuma, baixa o instalador oficial do jrsoftware.org, **confere a assinatura digital** e instala por usuário em `installer\tools\InnoSetup` (sem admin, sem PATH, sem registro global).
- **Assinatura de código (opcional):** defina `JARVIS_SIGN_CMD` com o comando do signtool usando `$f` para o arquivo, p. ex. `signtool sign /fd SHA256 /tr <timestamp> /td SHA256 /f cert.pfx /p <senha> $f`. O build passa isso ao Inno (`SignTool`/`SignedUninstaller`). Sem a variável o instalador sai **sem assinatura** (SmartScreen mostra "editor desconhecido"). Nenhum certificado é criado ou simulado.

## Instalação (Inno Setup, pt-BR e en)
Assistente moderno com marca: idioma, licença, **requisitos** (Windows 19044+, x64, RAM, disco livre na pasta escolhida, GPU/driver, Vulkan), pasta, componentes, tarefas, pronto.
- **Sem admin por padrão:** `%LocalAppData%\Programs\Jarvis`. O Inno oferece "só para mim" ou "para todos os usuários" (pede admin; padrão `Program Files\Jarvis`).
- **Requisitos:** versão do Windows e x64 **bloqueiam**; RAM < 12 GB pergunta se continua; disco insuficiente é barrado pelo Inno (considera os modelos escolhidos); GPU, versão/idade do driver e `vulkan-1.dll` **só avisam** (o instalador nunca atualiza nem mexe em driver).
- **Componentes:** Núcleo (fixo); Modelo de visão e linguagem; Voz; Reconhecimento Whisper (small recomendado, ou base). **Tarefas:** atalho na Área de Trabalho, atalhos no Menu Iniciar (Jarvis, Configurações, Reparar ou reconfigurar, Desinstalar), Iniciar com o Windows (desmarcado).
- A escolha vai para `data\setup\install.json`; o assistente usa isso para saber o que baixar.
- **Atualização por cima:** mesmo `AppId`; troca só `src\`, `runtime\` e `bin\`. `data\`, `models\`, `logs\` e `config.toml` não são tocados.
- **Log:** `SetupLogging` + cópia em `<pasta>\logs\install.log`.
- **Silencioso:** `Jarvis-Setup-<v>.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\Pasta" /LOG="inst.log" /COMPONENTS="core,vision,voice,stt\small" /TASKS="startmenuicon"`; opções próprias: `/DOWNLOADMODELS=1` (baixa os modelos ao final, sem janela) e `/OFFLINEPACK="C:\Jarvis-Modelos"`.
- **Pacote offline:** uma pasta (ou `.zip`) `Jarvis-Modelos` **ao lado do instalador** é detectada e importada ao final (cada arquivo é conferido por SHA-256; o que não bater é ignorado). Para criá-la a partir de uma instalação que já tem os modelos: `Jarvis.cmd setup --make-pack D:\Jarvis-Modelos`. A importação procura por **tamanho + hash**, não pelo nome, então serve qualquer estrutura de pastas. Também há o botão "Usar pacote offline..." no assistente.
- **Desinstalação:** remove programa, runtime, atalhos e a entrada "Iniciar com o Windows" (inclusive a criada depois pelo assistente). **Pergunta** se apaga os dados (memória e conversas, gravações, `config.toml`, logs, chave `HKCU\Software\Jarvis` das preferências de janela): o padrão é **manter**. Pergunta à parte se remove os modelos (~3,5 GB; padrão: remover). Silenciosa: mantém os dados; `/PURGEDATA=1` apaga tudo, `/KEEPMODELS=1` preserva os modelos.

## Assistente de configuração: `Jarvis.cmd setup`
Abre sozinho ao fim da instalação e no primeiro clique no atalho (até concluir). Depois: atalho **Reparar ou reconfigurar o Jarvis** (`setup --repair`). Mesmo visual das Configurações e da Ilha (kit `ui\kit` e tokens `ui\theme.py`; claro/escuro conforme a preferência), teclado completo (Tab, Enter, Alt+setas), foco visível, nome acessível em cada controle, estado nunca só por cor, 100% pt-BR. Salva o progresso a cada etapa (fechar no meio e reabrir oferece "continuar de onde parei").

1. **Boas-vindas.** 2. **Seu computador:** Windows, x64, RAM, disco, GPU Vulkan (via `llama-server --list-devices`), driver antigo (só aviso), microfone/alto-falante padrão, tela/DPI. 3. **Modelos:** seleção, baixar com progresso/velocidade/tempo restante, pausar/retomar, conferir SHA-256, pacote offline, mensagens de offline/disco/hash. 4. **Microfone e som:** padrão do Windows ou dispositivo; medidor ao vivo; aviso de "sem sinal". 5. **Teste de voz:** fala de exemplo com a voz Piper e eco do microfone (grava 4 s e toca) com medidor. 6. **Calibragem do VAD:** 3 s de silêncio + 1 frase; sugere `audio.vad_threshold` a partir das probabilidades do Silero. 7. **Atalhos:** F9 (falar), emergência, mudo; testa se o Windows aceita cada um (RegisterHotKey) e sugere trocas em conflito. 8. **Permissões:** Equilibrado ou Estrito; explica o YOLO **sem permitir ligá-lo** (só em Configurações > Permissões ou pela tecla física). 9. **Verificação final:** roda o `doctor` com resultado legível e dica por falha. 10. **Tudo pronto:** resumo, Iniciar com o Windows (opcional) e abrir o Jarvis.

As escolhas são gravadas no `config.toml` pelo mesmo `SettingsStore` das Configurações (validação e backup iguais).

Modos sem janela (usados pelo instalador e úteis em scripts): `setup --fetch [--components vision,voice,stt_small]`, `setup --offline PASTA_OU_ZIP`, `setup --make-pack PASTA`, `setup --status`. Códigos de saída: 0 ok, 2 uso/arquivo, 3 sem internet, 4 falha/integridade, 5 disco cheio, 130 cancelado. `setup --capture PASTA` gera PNG de todas as telas offscreen (desenvolvimento).

## Modelos e licenças (`installer\manifest.json`)
| Arquivo | Tamanho | Fonte oficial | Licença |
|---|---|---|---|
| Qwen3VL-4B-Instruct-Q4_K_M.gguf | 2,50 GB | huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF @1cd86af | Apache-2.0 |
| mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf | 454 MB | idem | Apache-2.0 |
| pt_BR-faber-medium.onnx (+ .json) | 63 MB | huggingface.co/rhasspy/piper-voices @e9c8a39 | dados CC0; Piper GPL-3.0 |
| silero_vad.onnx (v6.2) | 2,3 MB | github.com/snakers4/silero-vad @5cd7945 | MIT |
| faster-whisper small / base | 484 MB / 145 MB | huggingface.co/Systran @536b066 / @ebe41f7 | MIT |
| llama.cpp b12531 Vulkan (embutido) | 38,9 MB | github.com/ggml-org/llama.cpp releases | MIT |
| Python 3.14.3 embeddable (embutido) | 12,0 MB | python.org | PSF |

Os SHA-256 foram calculados dos arquivos locais em uso e **conferidos com o hash LFS publicado** pelo Hugging Face. As URLs são fixadas por commit (o conteúdo não muda). Espelhos (também só HTTPS, e sempre sujeitos ao mesmo SHA-256): ModelScope (Qwen, organização oficial Qwen) e jsDelivr (Silero). Para trocar um modelo: edite `manifest.json` (URL, tamanho, SHA-256) e recompile.

## Baixador (`setup\download.py`)
Só HTTPS (redirecionamento para http é recusado); cabeçalho `Range` para retomar o `.part` (se o servidor responder 200 recomeça); SHA-256 calculado durante o download e **obrigatório** antes de promover o arquivo (`.part` adulterado é descartado); tamanho anunciado conferido; 3 tentativas por URL com espera crescente e troca de espelho; checagem de espaço em disco antes de começar; cache `verified.json` evita recalcular 2,5 GB a cada abertura; User-Agent genérico, sem dados do usuário.

## Segurança
Nada de segredo no instalador. O servidor do modelo continua só em `127.0.0.1` (validado pela config). O instalador não abre portas nem mexe no firewall/PATH. Downloads só HTTPS + hash. Instalação por usuário: `data\` e `logs\` recebem ACL só para o usuário e o SYSTEM (`icacls`, sem herança). Instalação por máquina: usuários comuns recebem gravação em `data`, `logs`, `models` e criação de arquivos na raiz (o Jarvis grava `config.toml` ali); o código fica somente leitura.

## Pendências e limites conhecidos
- **Licença do próprio Jarvis:** `LICENSE.*.txt` traz aviso de privacidade, "sem garantia" e as licenças de terceiros, mas o bloco "Termos do Jarvis" é um **marcador** para o Bruno definir. O pacote `piper-tts` é GPL-3.0 e o PySide6 é LGPL-3.0: distribuir o instalador a terceiros exige manter os textos de licença (vão em `THIRD-PARTY.txt` e nos `dist-info`) e oferecer o código-fonte.
- Os dados ficam dentro da pasta de instalação (o `config.py` fixa `ROOT\data` e `ROOT\config.toml`); por isso o modo "por máquina" compartilha dados entre usuários. Recomendado: por usuário.
- `ToggleSwitch` do kit guarda uma animação já apagada e falha ao esconder; o assistente usa uma subclasse protegida (`widgets.make_toggle`). Vale corrigir no kit.
- `Jarvis.cmd` (dev e instalado) não aceita argumentos com espaço entre aspas (a expansão de `%ARGS%` quebra); no assistente, `--capture` deve receber caminho sem espaço pelo `.cmd`.
- Sem assinatura de código, o Windows SmartScreen avisa na primeira execução.

## Verificação do pacote (build de 2026-11-22, HEAD 24a397a)
- `build.ps1` reprova o staging se tiver `work`, `logs`, `data`, `models`, `venv`, `.git`, `tests`, `config.toml` (o pacote usa o PADRÃO, sem `input_device`/`output_device` fixos) ou, no código empacotado, caminhos de usuário (`C:\Users\<nome>`), e-mails e "Fuxi". O nome "Bruno" aparece em 19 arquivos de `src\jarvis` como nome do dono em prompts e comentários (ex.: `memory\search.py:162`, `tools\memory_tools.py:207`, `context\manager.py:38`): o build só AVISA; para um pacote de terceiros convém trocar por texto neutro (fora do escopo do instalador). Os `.pyc` são compilados com caminho neutro (`-s/-p`), sem o caminho da máquina de build.
- Teste de modelos sem copiar 3,5 GB: junção (`mklink /J`) de `models\` da instalação de teste para a pasta existente; **remova a junção com `rmdir` antes de desinstalar** (nunca com `/PURGEDATA` por cima dela).
