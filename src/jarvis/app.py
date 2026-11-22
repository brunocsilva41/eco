"""Orquestrador do Jarvis: liga áudio, cérebro, agente, segurança e atalhos numa só aplicação.

Threads:
- principal: laço de entrada (tecla de falar, texto, mudo, supervisão, pedidos de controle); captura e transcreve a fala;
- requisição: um pedido por vez (agente -> ferramentas -> fala), cancelável;
- voz: síntese + reprodução (voice.py); atalhos: laço de mensagens do Windows (win/hotkeys.py).
A tecla de emergência cancela o token de sessão (tudo que estiver rodando) e solta mouse/teclado. Cada pedido nasce
do token de sessão CAPTURADO no momento da fala: se a emergência disparar no meio, o pedido nunca chega a rodar.
Apertar a tecla de falar durante uma resposta interrompe o Jarvis (barge-in por tecla).
Configuração: `apply_config` aplica na hora o que é seguro (temperatura, timeouts, ferramentas ligadas...) e lista o que
exige reiniciar; o app em execução também atende `reload`/`restart` pedidos pela tela de Configurações.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass

from . import config as cfgmod
from .agent import Agent
from .audio.capture import Microphone
from .audio.playback import Speaker
from .audio.stt import Transcriber
from .audio.tts import Synthesizer
from .config import Config, ConfigError
from .core import logsetup
from .core.cancel import CancelToken, Cancelled
from .core.events import EventBus, State
from .core.permissions import YOLO
from .core.state import StateMachine
from .llm.client import LlmClient
from .llm.server import LlamaServer
from .memory import Memory
from .safety import ConfirmationBroker, EmergencyStop
from .settings import control
from .settings.store import SettingsStore
from .tools import catalog
from .tools.registry import ToolRegistry
from .voice import Voice
from .win import dpi
from .win import input as win_input
from .win.hotkeys import HotkeyError, HotkeyListener, KeyHold
from .win.keys import parse_combo

log = logging.getLogger(__name__)

LOAD_TIMEOUT_S = 300.0
SUPERVISE_EVERY_S = 2.0
CONTROL_EVERY_S = 1.0
RESTART_EXIT = control.RESTART_EXIT_CODE


class StartupError(RuntimeError):
    """Falha que impede o Jarvis de funcionar com segurança; a mensagem lista todos os problemas."""


@dataclass
class _Parts:
    memory: Memory
    registry: ToolRegistry
    server: LlamaServer
    llm: LlmClient
    mic: Microphone
    speaker: Speaker
    stt: Transcriber
    tts: Synthesizer
    voice: Voice
    agent: Agent
    confirmer: ConfirmationBroker
    hotkeys: HotkeyListener


class JarvisApp:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.bus = EventBus()
        self.state = StateMachine(self.bus)
        self._session = CancelToken()
        self._session_lock = threading.Lock()
        self._stop = threading.Event()
        self._exit_code = 0
        self._muted = False
        self._req_thread: threading.Thread | None = None
        self._req_cancel: CancelToken | None = None
        self._text_q: "queue.Queue[str]" = queue.Queue()
        self._p: _Parts | None = None
        self._pending_restart: tuple[str, ...] = ()
        self._started = time.time()
        self._hotkeys_ok = True
        self._settings = SettingsStore()
        self._boot_cfg = cfg                                             # configuração da partida (base do "requer reinício")
        self._emergency_norm = parse_combo(cfg.safety.emergency_hotkey).norm
        self._estop: EmergencyStop | None = None
        self._island = None                                              # IslandLink (processo filho da Ilha); None = desligada
        self._settings_opened_at = 0.0
        self._listen_open = cfg.safety.listen_mode == "open"

    # ================================================================ ciclo de vida
    def start(self) -> None:
        """Carrega tudo. Levanta StartupError (com todos os problemas) se algo essencial falhar; nada fica aberto nesse caso."""
        cfg = self.cfg
        dpi.ensure_per_monitor_v2()                                     # antes de qualquer captura/coordenada
        logsetup.setup(cfg.paths.logs, cfg.logs)
        log.info("iniciando o Jarvis (raiz %s)", cfg.paths.root)
        self._boot_cfg = cfg                                            # base para saber o que ainda exige reinício
        try:
            self._build(cfg)
        except StartupError:
            self._p = None                                              # o ExitStack de _build já fechou tudo que abriu
            self.shutdown()
            raise
        except Exception as exc:  # noqa: BLE001 - banco de versão nova, dispositivo ausente, etc.: mensagem clara, sem traceback
            log.exception("falha na partida")
            self._p = None
            self.shutdown()
            raise StartupError(f"não consegui iniciar: {exc}") from exc
        except BaseException:
            self._p = None
            self.shutdown()
            raise
        control.write_runtime(cfg.paths.data, control.Runtime(os.getpid(), self._started,
                                                              control.config_mtime(cfgmod.CONFIG_FILE), self._pending_restart))
        log.info("Jarvis pronto. %s para falar; %s para parar tudo.",
                 cfg.safety.talk_key.upper(), cfg.safety.emergency_hotkey.upper())
        if cfg.ui.island_enabled or cfg.ui.tray_enabled:
            self._start_island()

    def _start_island(self) -> None:
        """Lança a Ilha como processo filho (pipes JSON). Qualquer falha aqui só tira a Ilha; o Jarvis segue."""
        p = self._p
        if p is None:
            return
        try:
            from .ui.island.link import IslandLink                      # sem Qt: o núcleo não importa PySide6
            link = IslandLink(self.bus, root=cfgmod.ROOT, log_dir=self.cfg.paths.logs, on_command=self._on_island_command,
                              tts_rms=lambda: getattr(getattr(p.speaker, "_session", None), "_last_rms", 0.0),
                              speaking=lambda: self.state.speaking, yolo_remaining=YOLO.remaining_s,
                              permission_mode=lambda: self.cfg.safety.permission_mode, ui_config=self._island_config,
                              tray_only=not self.cfg.ui.island_enabled)
            link.start()
            self._island = link
        except Exception:  # noqa: BLE001
            log.exception("não consegui iniciar a Ilha (o Jarvis continua sem ela)")

    def _island_config(self) -> dict:
        """Aparência e comportamento da Ilha + atalhos REAIS (para as dicas nos botões); reenviado a cada config aplicada."""
        u, s = self.cfg.ui, self.cfg.safety
        return {"mode": u.island_mode, "float_gap_px": u.island_float_gap_px, "autohide": u.island_autohide,
                "hide_delay_s": u.island_hide_delay_s, "hover_reveal": u.island_hover_reveal,
                "listen_mode": "open" if self._listen_open else "push", "pinned": getattr(u, "island_pinned", False),
                "opacity": getattr(u, "island_opacity", 0.92), "side_y_pct": getattr(u, "island_side_y_pct", 50),
                "hotkeys": {"open_listen": s.open_listen_hotkey, "yes": s.confirm_yes_hotkey, "no": s.confirm_no_hotkey, "stop": s.emergency_hotkey,
                            "mute": s.mute_hotkey, "talk": s.talk_key, "yolo": s.yolo_hotkey}}

    def _on_island_command(self, cmd: str, msg: dict) -> None:
        """Botões da Ilha (thread de leitura do pipe). Mesmas rotas das teclas; a Ilha só pede, o núcleo decide."""
        p = self._p
        if p is None:
            return
        if cmd == "confirm":
            p.confirmer.answer(bool(msg.get("yes")), request_id=str(msg.get("id") or "") or None, via="island")
        elif cmd == "mute":
            if bool(msg.get("on")) != self._muted:
                self.toggle_mute()
        elif cmd == "stop":
            if self._estop is not None:
                self._estop.trigger("botão Parar da Ilha")
        elif cmd == "listen_mode":
            self.set_listen_mode("open" if msg.get("mode") == "open" else "push")
        elif cmd == "quit":
            log.info("encerrar pedido pela bandeja/Ilha")
            self.request_stop()
        elif cmd == "pin":
            self._persist({"ui.island_pinned": bool(msg.get("on"))})
        elif cmd == "ui_mode":
            if msg.get("mode") in ("docked", "floating", "dock_right", "dock_left"):
                self._persist({"ui.island_mode": msg["mode"]})
        elif cmd == "settings":
            now = time.monotonic()
            if now - self._settings_opened_at > 3.0:                    # cliques repetidos não abrem várias janelas
                self._settings_opened_at = now
                self.bus.publish("open_settings", section="permissions" if msg.get("section") == "permissions" else "general")

    def _persist(self, updates: dict) -> None:
        """Grava uma preferência da Ilha/bandeja no config.toml (em segundo plano; falha só vira aviso no log)."""
        def run() -> None:
            try:
                from .setup.config_io import save_values
                save_values(updates)
            except Exception:  # noqa: BLE001
                log.warning("não consegui salvar %s", ", ".join(updates), exc_info=True)
        threading.Thread(target=run, name="jarvis-persist", daemon=True).start()

    # ------------------------------------------------------------ escuta aberta
    @property
    def listen_open(self) -> bool:
        return self._listen_open

    def set_listen_mode(self, mode: str, persist: bool = True) -> None:
        """'open' = escuta aberta (ouve sozinho); 'push' = só pela tecla de falar. Vale na hora."""
        on = mode == "open"
        if on == self._listen_open:
            return
        self._listen_open = on
        log.info("escuta %s", "ABERTA" if on else "pela tecla")
        self.bus.publish("listen_mode", mode="open" if on else "push")
        if persist:
            self._persist({"safety.listen_mode": "open" if on else "push"})
        p = self._p
        if p is not None and not self._muted:
            p.voice.say("Escuta contínua ligada." if on else "Escuta contínua desligada.")

    def toggle_listen_mode(self) -> None:
        self.set_listen_mode("push" if self._listen_open else "open")

    def _open_listen_ready(self) -> bool:
        p = self._p
        if p is None or self._muted:
            return False
        if self.state.agent_state != State.IDLE or self.state.speaking or p.confirmer.has_pending():
            return False
        t = self._req_thread
        return not (t is not None and t.is_alive())

    def _on_open_listen(self) -> None:
        """Um passo da escuta aberta: espera até 1 s por uma fala (sem prender o laço principal) e, se vier, trata como o F9."""
        p = self._p
        assert p is not None
        idle_at = p.speaker.idle_since()
        if idle_at is None:
            return
        session = self._current_session()
        t_listen = time.monotonic()
        try:
            audio = p.mic.listen_utterance(session, max_wait_s=1.0, flush_backlog=False, not_before=idle_at + 0.7)   # 0,7 s: não ouve o eco da própria voz
        except Cancelled:
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("falha na escuta aberta")
            self.bus.publish("error", where="audio", text=str(exc))
            self._stop.wait(1.0)
            return
        if audio is None or session.cancelled:
            return
        if not self.state.go(State.LISTENING):
            return
        self._after_audio(audio, session, t_listen)

    def _after_audio(self, audio, session, t_listen) -> None:  # type: ignore[no-untyped-def]
        p = self._p
        assert p is not None
        try:
            self.state.go(State.TRANSCRIBING)
            heard = p.stt.transcribe(audio, session)
        except Cancelled:
            self.state.reset()
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("falha ao transcrever")
            self.bus.publish("error", where="audio", text=str(exc))
            self.state.reset()
            return
        text = heard.text.strip()
        log.info("fala %.1fs -> texto em %.2fs (escuta aberta)", heard.duration_s, heard.elapsed_s)
        self._watch_mic_signal(heard)
        self.bus.publish("transcript", text=text, final=True)
        if not text or session.cancelled:
            self.state.reset()
            return
        self._start_request(text, session, t_listen)

    def _build(self, cfg: Config) -> None:
        with ExitStack() as stack:                                      # se um construtor falhar, o que já abriu é fechado
            memory = Memory(cfg.paths.data / "jarvis.db", cfg.memory)
            stack.callback(memory.close)
            confirmer = ConfirmationBroker(self.bus, cfg.safety.confirm_timeout_s)
            registry = ToolRegistry(cfg, self.bus, confirmer)
            failed = catalog.register_everything(registry, cfg)
            if failed:
                log.error("módulos de ferramentas com falha: %s", ", ".join(failed))

            server = LlamaServer(cfg, on_event=lambda kind, text: self.bus.publish("notice", notice_kind=kind, text=text))
            stack.callback(server.stop)
            llm = LlmClient(cfg, api_key=lambda: server.api_key)
            from .tools import mouse_tools                              # a localização visual de clicar_em usa o mesmo modelo
            mouse_tools.set_grounder(llm)
            speaker = Speaker(cfg.audio, cfg.tts, self.bus)
            stack.callback(speaker.close)
            tts = Synthesizer(cfg.tts)
            stack.callback(tts.close)
            stt = Transcriber(cfg.stt)
            stt.set_idle_unload(cfg.llm.sleep_idle_s)                   # motor GPU: libera a VRAM junto com o modelo de linguagem
            stack.callback(stt.close)
            mic = Microphone(cfg.audio, self.bus, models_dir=cfg.paths.models)
            stack.callback(mic.close)
            voice = Voice(tts, speaker, self.state)
            stack.callback(voice.close)
            agent = Agent(cfg, llm, registry, memory, self.bus, self.state)
            hotkeys = HotkeyListener()
            stack.callback(hotkeys.stop)
            parts = _Parts(memory, registry, server, llm, mic, speaker, stt, tts, voice, agent, confirmer, hotkeys)
            self._p = parts

            confirmer.set_voice_listener(self._listen_for_answer, available=lambda: not self._muted)
            confirmer.set_speaker(lambda text, cancel: voice.say_and_wait(text, cancel))
            self.bus.subscribe(lambda ev: agent.request_compaction(), kind="compact_request")
            self.bus.subscribe(lambda ev: self._maybe_prewake(agent) if ev.data.get("state") == "listening" else None, kind="state")

            errors = self._load_models(server, stt, tts, mic)
            if errors:
                raise StartupError("não consegui iniciar:\n - " + "\n - ".join(errors))
            self._check_prompt_budget(agent, llm)
            threading.Thread(target=self._warmup, args=(agent,), name="jarvis-warmup", daemon=True).start()
            self._start_hotkeys()
            stack.pop_all()                                             # tudo certo: o shutdown() assume a limpeza

    def _maybe_prewake(self, agent: Agent) -> None:
        """Entrou em 'Ouvindo' (F9 ou palavra de ativação): acorda o modelo em segundo plano. No máximo 1× a cada 20 s."""
        now = time.monotonic()
        if now - getattr(self, "_last_prewake", 0.0) < 20.0:
            return
        self._last_prewake = now

        def run() -> None:
            try:
                if self._p is not None:
                    self._p.stt.preload()                               # a escuta na GPU também pode ter descarregado
                log.debug("pré-aquecimento do modelo: %.1f s", agent.prewake(CancelToken()))
            except Exception:  # noqa: BLE001 - só otimização
                log.debug("pré-aquecimento falhou (ignorado)", exc_info=True)
        threading.Thread(target=run, name="jarvis-prewake", daemon=True).start()

    def _warmup(self, agent: Agent) -> None:
        """Aquece o cache do servidor com o prompt fixo (o 1º pedido real não espera o processamento dele)."""
        try:
            log.info("aquecimento do prompt fixo: %.1f s", agent.warmup(CancelToken()))
        except Exception:  # noqa: BLE001 - só otimização
            log.warning("aquecimento do prompt falhou (ignorado)", exc_info=True)

    def _check_prompt_budget(self, agent: Agent, llm: LlmClient) -> None:
        """Mede (com o tokenizador do modelo) quanto do contexto o prompt FIXO ocupa: sistema + esquemas das ferramentas."""
        try:
            fixed, n_ctx = agent.fixed_prompt_tokens()
        except Exception:  # noqa: BLE001 - a medição é diagnóstico; não impede a partida
            log.exception("não consegui medir o prompt fixo")
            return
        pct = 100 * fixed / max(1, n_ctx)
        log.info("prompt fixo (sistema + ferramentas): %d tokens de %d de contexto (%.0f%%)", fixed, n_ctx, pct)
        room = n_ctx - self.cfg.llm.max_tokens - fixed
        if room < 600:
            raise StartupError(f"o prompt fixo (sistema + ferramentas) ocupa {fixed} dos {n_ctx} tokens de contexto, sobrando "
                               f"{max(room, 0)} para a conversa. Aumente llm.ctx (Configurações) ou desligue ferramentas que não usa.")
        if pct > 50:
            self.bus.publish("notice", notice_kind="context_tight", text=f"As ferramentas ocupam {pct:.0f}% do contexto; "
                             "considere aumentar llm.ctx ou desligar ferramentas.")

    def _load_models(self, server: LlamaServer, stt: Transcriber, tts: Synthesizer, mic: Microphone) -> list[str]:
        """Carrega LLM, STT, TTS e abre o microfone em paralelo; devolve as falhas. Com prazo total e cancelável."""
        errors: list[str] = []
        lock = threading.Lock()
        cancel = self._session.child()

        def job(name: str, fn) -> None:
            t0 = time.monotonic()
            try:
                fn()
                log.info("%s pronto em %.1f s", name, time.monotonic() - t0)
            except Exception as exc:  # noqa: BLE001
                log.error("%s falhou: %s", name, exc)
                with lock:
                    errors.append(f"{name}: {exc}")

        jobs = [("STT", stt.preload), ("TTS", tts.preload), ("microfone", mic.open),
                ("llama-server", lambda: server.start(cancel))]
        threads = [threading.Thread(target=job, args=j, name=f"load-{j[0]}", daemon=True) for j in jobs]
        for t in threads:
            t.start()
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        try:
            for t in threads:
                while t.is_alive():
                    if time.monotonic() > deadline:
                        cancel.cancel("tempo de carga esgotado")
                        with lock:
                            errors.append(f"{t.name}: não terminou em {LOAD_TIMEOUT_S:.0f}s")
                        break
                    t.join(0.25)
        except KeyboardInterrupt:
            cancel.cancel("interrompido")
            raise
        finally:
            cancel.release()
        return errors

    def _start_hotkeys(self) -> None:
        p, s = self._p, self.cfg.safety
        assert p is not None
        p.hotkeys.start()
        stop = EmergencyStop(self._emergency, win_input.release_all)
        self._estop = stop
        try:
            p.hotkeys.add(s.emergency_hotkey, lambda: stop.trigger("tecla de emergência"))
        except HotkeyError as exc:
            raise StartupError(f"tecla de emergência indisponível: {exc}") from exc    # sem ela o Jarvis NÃO controla o PC
        self.bus.subscribe(lambda ev: self._open_settings(ev.data.get("section", "permissions")), kind="open_settings")
        YOLO.on_change(lambda on, why: self.bus.publish("yolo", on=on, text=f"Modo YOLO {why}"))   # só reflete (Ilha, terminal)
        if s.yolo_hotkey.strip():
            try:
                p.hotkeys.add(s.yolo_hotkey, self._toggle_yolo)
            except HotkeyError as exc:
                log.warning("atalho do YOLO indisponível: %s", exc)
        for combo, cb, label in ((s.mute_hotkey, self.toggle_mute, "mudo"),
                                 *(((s.open_listen_hotkey, self.toggle_listen_mode, "escuta contínua"),) if s.open_listen_hotkey.strip() else ()),
                                 (s.confirm_yes_hotkey, lambda: p.confirmer.answer(True, via="key"), "confirmar SIM"),
                                 (s.confirm_no_hotkey, lambda: p.confirmer.answer(False, via="key"), "confirmar NÃO")):
            try:
                p.hotkeys.add(combo, cb)
            except HotkeyError as exc:
                log.warning("atalho de %s indisponível: %s", label, exc)

    def shutdown(self) -> None:
        """Encerra tudo e libera áudio, atalhos, servidor e banco. Idempotente. Ordem: parar o trabalho, esperar, fechar."""
        self._stop.set()
        island, self._island = self._island, None
        if island is not None:
            try:
                island.stop()
            except Exception:  # noqa: BLE001
                log.exception("erro ao encerrar a Ilha")
        self._session.cancel("encerrando")
        t = self._req_thread
        if t is not None and t.is_alive():
            t.join(5.0)                                   # o pedido termina ANTES de fecharmos memória/voz
        p, self._p = self._p, None
        if p is not None:
            for name, fn in (("voz", p.voice.close), ("alto-falante", p.speaker.close), ("microfone", p.mic.close),
                             ("atalhos", p.hotkeys.stop), ("STT", p.stt.close), ("TTS", p.tts.close),
                             ("llama-server", p.server.stop), ("memória", p.memory.close)):
                try:
                    fn()
                except Exception:  # noqa: BLE001 - encerrar o resto mesmo se um falhar
                    log.exception("erro ao encerrar %s", name)
        try:
            control.clear_runtime(self.cfg.paths.data)
        except Exception:  # noqa: BLE001
            log.exception("erro ao limpar runtime.json")
        self.bus.close()
        log.info("Jarvis encerrado")

    def request_stop(self, exit_code: int = 0) -> None:
        self._exit_code = exit_code
        self._stop.set()

    # ================================================================ entrada
    def submit_text(self, text: str) -> None:
        """Entrada por texto (modo --text). Se houver confirmação pendente, o texto responde Sim/Não."""
        self._text_q.put(text)

    def _open_settings(self, section: str) -> None:
        """Abre a tela de Configurações (outro processo) já na seção pedida."""
        import subprocess
        import sys
        now = time.monotonic()
        proc = getattr(self, "_settings_proc", None)
        if proc is not None and proc.poll() is None and now - getattr(self, "_settings_started", 0.0) < 20.0:
            return                                              # ainda abrindo (ou aberta): cliques repetidos não criam outra janela
        if now - getattr(self, "_settings_started", 0.0) < 1.5:
            return
        self._settings_started = now
        code = ("import sys; sys.path.insert(0, r'%s'); from jarvis.__main__ import main; raise SystemExit(main(sys.argv[1:]))"
                % str(cfgmod.ROOT / "src"))
        try:
            self._settings_proc = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", code, "settings", "--open", section],
                                                   cwd=str(cfgmod.ROOT), creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | 0x08000000)
        except OSError:
            log.exception("não consegui abrir as Configurações")

    def _toggle_yolo(self) -> None:
        """Atalho FÍSICO do Bruno. É o único caminho que liga o YOLO (o modelo só pode apertar atalhos da lista, e este é reservado)."""
        if YOLO.active():
            YOLO.deactivate("atalho")
            return
        YOLO.activate_manual(self.cfg.safety.yolo_minutes)
        p = self._p
        if p is not None:
            p.voice.say(f"Modo YOLO ligado por {self.cfg.safety.yolo_minutes} minutos.")

    def toggle_mute(self) -> None:
        p = self._p
        if p is None:
            return
        self._muted = not self._muted
        (p.mic.mute if self._muted else p.mic.unmute)()
        self.bus.publish("mute", muted=self._muted)
        log.info("microfone %s", "DESLIGADO" if self._muted else "ligado")

    def run(self) -> int:
        """Laço principal. Devolve o código de saída (0 normal; 75 = reiniciar pedido pelas Configurações)."""
        p = self._p
        if p is None:
            raise StartupError("chame start() antes de run()")
        talk = KeyHold(self.cfg.safety.talk_key)
        p.voice.say("Jarvis pronto.")
        next_supervise = next_control = time.monotonic()
        failures: list[float] = []
        try:
            while not self._stop.is_set():
                try:
                    now = time.monotonic()
                    if now >= next_supervise:
                        next_supervise = now + SUPERVISE_EVERY_S
                        self._supervise()
                    if now >= next_control:
                        next_control = now + CONTROL_EVERY_S
                        self._poll_control()
                    if self._drain_text():
                        continue
                    if not self._muted and talk():
                        self._on_talk_key(talk)
                        continue
                    if self._listen_open and self._open_listen_ready():
                        self._on_open_listen()
                        continue
                    self._stop.wait(0.02)
                except Exception as exc:  # noqa: BLE001 - uma falha numa tarefa periódica nunca derruba o Jarvis
                    log.exception("erro no laço principal")
                    self.bus.publish("error", where="loop", text=str(exc))
                    now = time.monotonic()
                    failures = [t for t in failures if now - t < 60.0] + [now]
                    if len(failures) >= 20:                                   # em laço de falhas: melhor parar com aviso do que girar
                        log.error("20 falhas em 60 s no laço principal; encerrando")
                        self.request_stop(1)
                    self._stop.wait(0.25)
        except KeyboardInterrupt:
            log.info("Ctrl+C: encerrando")
        return self._exit_code

    def _drain_text(self) -> bool:
        try:
            text = self._text_q.get_nowait()
        except queue.Empty:
            return False
        p = self._p
        assert p is not None
        if p.confirmer.has_pending():
            p.confirmer.answer_text(text)
            return True
        self._interrupt_request()
        self.bus.publish("user_text", text=text)                # a Ilha mostra o que foi digitado (como a fala reconhecida)
        self._start_request(text, self._current_session())
        return True

    def _on_talk_key(self, talk: KeyHold) -> None:
        p = self._p
        assert p is not None
        if p.confirmer.has_pending():
            time.sleep(0.05)                                    # a resposta é por voz/tecla de confirmação; não interromper
            return
        self._interrupt_request()                               # barge-in: falar por cima interrompe o Jarvis
        session = self._current_session()                       # CAPTURADO: a emergência cancela ESTE token
        if not self.state.go(State.LISTENING):
            log.warning("não consegui entrar em LISTENING (estado %s)", self.state.agent_state.value)
            return
        t_listen = time.monotonic()
        try:
            if self.cfg.safety.talk_mode == "toggle":
                while talk():                                   # espera soltar: o toggle é um aperto só
                    time.sleep(0.02)
                audio = p.mic.listen_utterance(session, max_wait_s=8.0)
            else:
                audio = p.mic.record_while(session, talk)
                while talk() and not session.cancelled:         # segurou além do limite: espera soltar (B-04)
                    time.sleep(0.02)
            if audio is None or session.cancelled:
                self.state.reset()
                return
            self.state.go(State.TRANSCRIBING)
            heard = p.stt.transcribe(audio, session)
        except Cancelled:
            self.state.reset()
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("falha ao ouvir/transcrever")
            self.bus.publish("error", where="audio", text=str(exc))
            self.state.reset()
            return
        text = heard.text.strip()
        log.info("fala %.1fs -> texto em %.2fs", heard.duration_s, heard.elapsed_s)
        self._watch_mic_signal(heard)
        log.debug("transcrição: %s", text)
        self.bus.publish("transcript", text=text, final=True)
        if not text or session.cancelled:                       # emergência no meio: o pedido NÃO nasce
            self.state.reset()
            return
        self._start_request(text, session, t_listen)

    def _watch_mic_signal(self, heard) -> None:  # type: ignore[no-untyped-def]
        """Fala detectada mas áudio sem sinal, várias vezes seguidas: reabre o microfone e avisa (o stream pode ter ficado preso
        depois de a máquina travar, ou outro app pegou o microfone em modo exclusivo)."""
        if not getattr(heard, "silent", False):
            self._silent_streak = 0
            return
        self._silent_streak = getattr(self, "_silent_streak", 0) + 1
        p = self._p
        if p is None:
            return
        if self._silent_streak == 2:
            log.warning("microfone sem sinal 2 vezes seguidas: reabrindo")
            self.bus.publish("notice", notice_kind="mic_reopen", text="O microfone parou de enviar som; estou reabrindo.")
            try:
                p.mic.close()
                p.mic.open()
            except Exception:  # noqa: BLE001
                log.exception("não consegui reabrir o microfone")
        elif self._silent_streak == 4:
            self.bus.publish("error", where="audio", text="O microfone continua sem sinal. Veja se ele está mudo no Windows, "
                                                        "desconectado ou em uso exclusivo por outro programa.")
            p.voice.say("Meu microfone está sem sinal. Veja se está mudo ou em uso por outro programa.")

    # ================================================================ pedido (agente)
    def _current_session(self) -> CancelToken:
        with self._session_lock:
            return self._session

    def _start_request(self, text: str, session: CancelToken, t0: float | None = None) -> None:
        if session.cancelled:
            return
        req = session.child()
        self._req_cancel = req
        self._req_thread = threading.Thread(target=self._request, args=(text, req, t0 or time.monotonic()),
                                            name="request", daemon=True)
        self._req_thread.start()

    def _request(self, text: str, cancel: CancelToken, t0: float) -> None:
        p = self._p
        if p is None:
            return
        first = threading.Event()

        def on_sentence(sentence: str) -> None:
            if cancel.cancelled:                                # B-03: nada fala depois de cancelar
                return
            if not first.is_set():
                first.set()
                log.info("latência até a 1ª frase: %.2f s", time.monotonic() - t0)
            p.voice.say(sentence)

        try:
            if p.agent.prepare_session():                       # inatividade: avisa por voz que abriu outra conversa
                on_sentence("Começando uma nova conversa.")
            result = p.agent.handle(text, cancel, on_sentence)
            p.voice.wait_done(cancel)
            log.info("pedido concluído em %.2f s (%d passos, ferramentas: %s)",
                     result.elapsed_s, result.steps, ", ".join(result.tools_used) or "nenhuma")
        except Cancelled as exc:
            log.info("pedido cancelado: %s", exc.reason)
            p.voice.interrupt()
        except Exception as exc:  # noqa: BLE001 - nada escapa da thread do pedido
            log.exception("pedido falhou")
            self.bus.publish("error", where="agent", text=str(exc))
            self.state.go(State.ERROR)
            p.voice.say("Tive um problema ao processar esse pedido. Pode tentar de novo?")   # nunca ficar mudo
        finally:
            cancel.release()
            self.state.reset()

    def _interrupt_request(self) -> None:
        """Cancela o pedido em andamento (e a fala) e espera a thread terminar."""
        p = self._p
        cancel, t = self._req_cancel, self._req_thread
        if p is not None and p.voice.speaking:
            p.voice.interrupt()
        if cancel is not None and t is not None and t.is_alive():
            cancel.cancel("interrompido pelo usuário")
            t.join(5.0)
            if t.is_alive():
                log.warning("a thread do pedido não terminou em 5 s")
        self._req_cancel = None

    # ================================================================ segurança e supervisão
    def _emergency(self, source: str) -> None:
        """Parada de emergência: cancela a sessão (e tudo que nasceu dela), para a fala e abre uma sessão nova."""
        with self._session_lock:
            old, self._session = self._session, CancelToken()
        old.cancel(source)                                      # PRIMEIRO: nada novo pode começar na sessão antiga
        YOLO.deactivate("parada de emergência")
        p = self._p
        if p is not None:
            p.voice.interrupt()
        self.state.reset()
        self.bus.publish("emergency", source=source)

    def _supervise(self) -> None:
        """Se a thread de atalhos morrer, tenta restaurá-la; sem a tecla de emergência o PC não é controlado."""
        p = self._p
        if p is None:
            return
        # "saudável" = a tecla de emergência está REALMENTE registrada no Windows (thread viva não basta)
        healthy = p.hotkeys.alive and self._emergency_norm in p.hotkeys.registered()
        if not healthy:
            p.hotkeys.ensure_alive()
            healthy = p.hotkeys.alive and self._emergency_norm in p.hotkeys.registered()
        if healthy:
            if not self._hotkeys_ok:
                self._hotkeys_ok = True
                p.registry.unblock_actions()
                p.voice.say("Atalhos restaurados.")
            return
        if self._hotkeys_ok:
            self._hotkeys_ok = False
            p.registry.block_actions("a tecla de emergência deixou de funcionar")
            self.bus.publish("error", where="hotkeys", text="a tecla de emergência deixou de funcionar")
            p.voice.say("A tecla de emergência parou de funcionar. Não vou mexer no computador até restaurar.")

    def _listen_for_answer(self, cancel: CancelToken, timeout_s: float, not_before: float) -> str | None:
        """Escuta uma resposta curta (Sim/Não) para o ConfirmationBroker, ignorando a fala do próprio Jarvis."""
        p = self._p
        if p is None or self._muted:
            return None
        while p.voice.speaking and not cancel.cancelled:        # nunca escutar enquanto o Jarvis fala
            cancel.wait(0.05)
        if cancel.cancelled:
            return None
        quiet_since = p.voice.idle_since() or time.monotonic()
        start_at = max(not_before, quiet_since) + 0.4           # margem para o eco da sala morrer
        audio = p.mic.listen_utterance(cancel, max_wait_s=timeout_s, not_before=start_at)
        if audio is None or cancel.cancelled:
            return None
        try:
            return p.stt.transcribe(audio, cancel, beam_size=1).text
        except Cancelled:
            return None

    # ================================================================ configuração em execução
    def _poll_control(self) -> None:
        for kind in sorted(control.consume(self.cfg.paths.data)):
            if kind == "restart":
                log.info("reinício pedido pelas Configurações")
                self.request_stop(RESTART_EXIT)
                return
            if kind == "reload":
                self.reload_config()
            if kind == "yolo_on":                                   # clique manual na tela de Configurações (pedido assinado)
                YOLO.activate_manual(self.cfg.safety.yolo_minutes)
                if self._p is not None:
                    self._p.voice.say(f"Modo YOLO ligado por {self.cfg.safety.yolo_minutes} minutos.")
            elif kind == "yolo_off":
                YOLO.deactivate("tela de Configurações")

    def reload_config(self) -> None:
        """Relê o config.toml e aplica o que dá sem reiniciar. Se o arquivo estiver inválido, mantém a configuração atual."""
        try:
            new = cfgmod.load()
        except ConfigError as exc:
            log.error("config.toml inválido; mantendo a configuração atual: %s", exc)
            self.bus.publish("error", where="config", text=str(exc))
            return
        self.apply_config(new)

    def apply_config(self, new: Config) -> None:
        p = self._p
        if p is None:
            return
        changes = self._settings.diff(self.cfg, new)
        if not changes.any:
            return
        old = self.cfg
        try:
            # aplica componente a componente; se algo falhar, volta TUDO para a configuração anterior (sem estado misto)
            self.cfg = new
            p.agent.reconfigure(new)
            p.llm.reconfigure(new)
            p.registry.reconfigure(new)
            p.confirmer.set_timeout(new.safety.confirm_timeout_s)
            p.memory.reconfigure(new.memory)
            logsetup.set_level(new.logs.level)
        except Exception as exc:  # noqa: BLE001
            log.exception("falha ao aplicar a configuração; voltando à anterior")
            self.cfg = old
            for comp in (p.agent, p.llm, p.registry):
                try:
                    comp.reconfigure(old)
                except Exception:  # noqa: BLE001
                    log.exception("falha ao reverter %s", type(comp).__name__)
            self.bus.publish("error", where="config", text=f"não consegui aplicar as configurações: {exc}")
            return
        # o que ainda exige reinício é calculado contra a configuração DO INÍCIO: desfazer a mudança limpa o aviso (N-25)
        pending = self._settings.diff(self._boot_cfg, new).restart
        self._pending_restart = pending
        try:
            control.write_runtime(new.paths.data, control.Runtime(os.getpid(), self._started,
                                                                  control.config_mtime(cfgmod.CONFIG_FILE), pending))
        except OSError:
            log.exception("não consegui atualizar runtime.json")
        log.info("configuração aplicada: %d na hora; aguardam reinício: %s", len(changes.live), ", ".join(pending) or "nenhuma")
        self.bus.publish("config_applied", live=list(changes.live), restart=list(pending))
