"""Orquestrador do Jarvis: liga áudio, cérebro, agente, segurança e atalhos numa só aplicação.

Threads:
- principal: laço de entrada (tecla de falar, texto, mudo); captura e transcreve a fala;
- requisição: um pedido por vez (agente -> ferramentas -> fala), cancelável;
- voz: fila de frases (voice.py); atalhos: laço de mensagens do Windows (win/hotkeys.py).
A tecla de emergência cancela o token de sessão (tudo que estiver rodando) e solta mouse/teclado.
Apertar a tecla de falar durante uma resposta interrompe o Jarvis (barge-in por tecla).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from .agent import Agent
from .audio.capture import Microphone
from .audio.playback import Speaker
from .audio.stt import Transcriber
from .audio.tts import Synthesizer
from .config import Config
from .core import logsetup
from .core.cancel import CancelToken, Cancelled
from .core.events import EventBus, State
from .core.state import StateMachine
from .llm.client import LlmClient
from .llm.server import LlamaServer, ServerError
from .memory import Memory
from .safety import ConfirmationBroker, EmergencyStop, parse_yes_no
from .tools import builtin, notes
from .tools.registry import ToolRegistry
from .voice import Voice
from .win import input as win_input
from .win.hotkeys import HotkeyError, HotkeyListener, KeyHold

log = logging.getLogger(__name__)


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
        self._muted = False
        self._req_thread: threading.Thread | None = None
        self._req_cancel: CancelToken | None = None
        self._text_q: "queue.Queue[str]" = queue.Queue()
        self._p: _Parts | None = None

    # ================================================================ ciclo de vida
    def start(self) -> None:
        """Carrega tudo. Levanta StartupError (com todos os problemas) se algo essencial falhar."""
        cfg = self.cfg
        logsetup.setup(cfg.paths.logs, cfg.log_level)
        log.info("iniciando o Jarvis (raiz %s)", cfg.paths.root)

        memory = Memory(cfg.paths.data / "jarvis.db")
        confirmer = ConfirmationBroker(self.bus, cfg.safety.confirm_timeout_s)
        registry = ToolRegistry(cfg, self.bus, confirmer)
        builtin.register_all(registry, cfg)
        notes.register(registry, cfg)

        server = LlamaServer(cfg)
        llm = LlmClient(cfg)
        speaker = Speaker(cfg.audio, cfg.tts, self.bus)
        tts = Synthesizer(cfg.tts)
        stt = Transcriber(cfg.stt)
        mic = Microphone(cfg.audio, self.bus)
        voice = Voice(tts, speaker, self.state)
        agent = Agent(cfg, llm, registry, memory, self.bus, self.state)
        hotkeys = HotkeyListener()
        self._p = _Parts(memory, registry, server, llm, mic, speaker, stt, tts, voice, agent, confirmer, hotkeys)

        confirmer.set_voice_listener(self._listen_for_answer)

        errors = self._load_models(server, stt, tts, mic)
        if errors:
            self.shutdown()
            raise StartupError("não consegui iniciar:\n - " + "\n - ".join(errors))
        self._start_hotkeys()
        log.info("Jarvis pronto. Segure %s para falar; %s para parar tudo.",
                 cfg.safety.talk_key.upper(), cfg.safety.emergency_hotkey.upper())

    def _load_models(self, server: LlamaServer, stt: Transcriber, tts: Synthesizer, mic: Microphone) -> list[str]:
        """Carrega LLM, STT, TTS e abre o microfone em paralelo; devolve as falhas."""
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

        jobs = [("STT", stt.preload), ("TTS", tts.preload), ("microfone", mic.open)]
        if self.cfg.llm.autostart:
            jobs.append(("llama-server", lambda: server.start(cancel)))
        elif not server.is_running():
            errors.append("llama-server não está rodando e llm.autostart = false")
        threads = [threading.Thread(target=job, args=j, name=f"load-{j[0]}", daemon=True) for j in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        cancel.release()
        return errors

    def _start_hotkeys(self) -> None:
        p, s = self._p, self.cfg.safety
        assert p is not None
        p.hotkeys.start()
        stop = EmergencyStop(self._emergency, win_input.release_all)
        try:
            p.hotkeys.add(s.emergency_hotkey, lambda: stop.trigger("tecla de emergência"))
        except HotkeyError as exc:
            # sem a tecla de emergência o Jarvis NÃO controla o PC
            self.shutdown()
            raise StartupError(f"tecla de emergência indisponível: {exc}") from exc
        for combo, cb, label in ((s.mute_hotkey, self.toggle_mute, "mudo"),
                                 (s.confirm_yes_hotkey, lambda: p.confirmer.answer(True), "confirmar SIM"),
                                 (s.confirm_no_hotkey, lambda: p.confirmer.answer(False), "confirmar NÃO")):
            try:
                p.hotkeys.add(combo, cb)
            except HotkeyError as exc:
                log.warning("atalho de %s indisponível: %s", label, exc)
        # a confirmação por voz fala a pergunta pelo canal de voz
        p.confirmer.set_speaker(lambda text: p.voice.say_and_wait(text, self._current_session()))

    def shutdown(self) -> None:
        """Encerra tudo e libera áudio, atalhos, servidor e banco. Idempotente."""
        self._stop.set()
        self._session.cancel("encerrando")
        p, self._p = self._p, None
        if p is None:
            return
        for name, fn in (("voz", p.voice.close), ("alto-falante", p.speaker.close), ("microfone", p.mic.close),
                         ("atalhos", p.hotkeys.stop), ("STT", p.stt.close), ("TTS", p.tts.close),
                         ("llama-server", p.server.stop), ("memória", p.memory.close)):
            try:
                fn()
            except Exception:  # noqa: BLE001 - encerrar o resto mesmo se um falhar
                log.exception("erro ao encerrar %s", name)
        t = self._req_thread
        if t is not None and t.is_alive():
            t.join(3.0)
        log.info("Jarvis encerrado")

    def request_stop(self) -> None:
        self._stop.set()

    # ================================================================ entrada
    def submit_text(self, text: str) -> None:
        """Entrada por texto (modo --text). Se houver confirmação pendente, o texto responde Sim/Não."""
        self._text_q.put(text)

    def toggle_mute(self) -> None:
        p = self._p
        if p is None:
            return
        self._muted = not self._muted
        (p.mic.mute if self._muted else p.mic.unmute)()
        self.bus.publish("mute", muted=self._muted)
        log.info("microfone %s", "DESLIGADO" if self._muted else "ligado")

    def run(self) -> None:
        """Laço principal. Retorna ao receber request_stop() ou Ctrl+C."""
        p = self._p
        if p is None:
            raise StartupError("chame start() antes de run()")
        talk = KeyHold(self.cfg.safety.talk_key)
        p.voice.say("Jarvis pronto.")
        try:
            while not self._stop.is_set():
                if self._drain_text():
                    continue
                if not self._muted and talk():
                    self._on_talk_key(talk)
                    continue
                self._stop.wait(0.02)
        except KeyboardInterrupt:
            log.info("Ctrl+C: encerrando")

    def _drain_text(self) -> bool:
        try:
            text = self._text_q.get_nowait()
        except queue.Empty:
            return False
        p = self._p
        assert p is not None
        if p.confirmer.has_pending():
            verdict = parse_yes_no(text)
            if verdict is not None:
                p.confirmer.answer(verdict)
            return True
        self._interrupt_request()
        self._start_request(text)
        return True

    def _on_talk_key(self, talk: KeyHold) -> None:
        p = self._p
        assert p is not None
        if p.confirmer.has_pending():
            time.sleep(0.05)                                    # a resposta é por voz/tecla de confirmação; não interromper
            return
        self._interrupt_request()                               # barge-in: falar por cima interrompe o Jarvis
        session = self._current_session()
        self.state.go(State.LISTENING)
        t_listen = time.monotonic()
        try:
            audio = p.mic.record_while(session, talk)
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
        log.debug("transcrição: %s", text)
        self.bus.publish("transcript", text=text, final=True)
        if not text:
            self.state.reset()
            return
        self._start_request(text, t_listen)

    # ================================================================ pedido (agente)
    def _current_session(self) -> CancelToken:
        with self._session_lock:
            return self._session

    def _start_request(self, text: str, t0: float | None = None) -> None:
        p = self._p
        assert p is not None
        req = self._current_session().child()
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
            if not first.is_set():
                first.set()
                log.info("latência até a 1ª frase: %.2f s", time.monotonic() - t0)
            p.voice.say(sentence)

        try:
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

    # ================================================================ segurança
    def _emergency(self, source: str) -> None:
        """Parada de emergência: cancela sessão inteira, para a fala, volta ao repouso e abre nova sessão."""
        with self._session_lock:
            old, self._session = self._session, CancelToken()
        old.cancel(source)
        p = self._p
        if p is not None:
            p.voice.interrupt()
        self.state.reset()
        self.bus.publish("emergency", source=source)

    def _listen_for_answer(self, cancel: CancelToken, timeout_s: float) -> str | None:
        """Escuta uma resposta curta (Sim/Não) para o ConfirmationBroker."""
        p = self._p
        if p is None or self._muted:
            return None
        audio = p.mic.listen_utterance(cancel, max_wait_s=timeout_s)
        if audio is None or cancel.cancelled:
            return None
        try:
            return p.stt.transcribe(audio, cancel).text
        except Cancelled:
            return None
