"""Sandbox de caminhos: tudo que o agente toca em disco passa por aqui.

Regras (todas recusam com `SandboxError`, mensagem em pt-BR):
  - o caminho resolvido precisa estar DENTRO de uma raiz de `cfg.files.roots` (comparação por componentes,
    sem diferenciar maiúsculas); relativo vale a partir da PRIMEIRA raiz;
  - nenhum componente `..` (mesmo que ficasse dentro), nada de `C:pasta` (unidade relativa), `\\pasta` (sem unidade),
    UNC, `\\?\\`, `\\.\\` ou fluxos alternativos NTFS (`arq.txt:fluxo`);
  - nenhum componente abaixo da raiz pode ser link simbólico, junção ou outro reparse point (exceto os marcadores
    benignos de nuvem/compressão, ex.: arquivos "somente online" do OneDrive);
  - nomes reservados do Windows (CON, NUL, COM1..9, LPT1..9, ... com ou sem extensão), componentes terminados em
    ponto/espaço, caracteres inválidos, de controle e de formatação Unicode (anti-spoofing);
  - nunca dentro (nem acima) de %SystemRoot%, Program Files, pasta do projeto, data, logs e config.toml;
  - caminho final de no máximo 259 caracteres;
  - criar/editar arquivos executáveis ou scripts é recusado (`check_write_extension`); `.html/.svg/...` podem ser
    criados, mas a ferramenta pede confirmação FORTE (`strong_confirm_extension`);
  - raízes proibidas (ignoradas com aviso): o perfil do usuário inteiro ou acima dele, AppData, ProgramData, pastas
    Inicializar, .ssh, .aws, .gnupg e qualquer pasta que as contenha;
  - nomes típicos de segredo (.env, id_rsa, *.kdbx, *.pem, *.pfx, *.key, Cookies, Login Data, credentials.json,
    .npmrc, .netrc...) não são lidos nem escritos (`is_sensitive_name`).
O caminho devolvido é o REAL (realpath), conferido contra a raiz também depois de resolvido.
Limitações: hardlinks e nomes 8.3 não são detectados como tal (8.3 é recusado por divergir do nome longo).
"""
from __future__ import annotations

import logging
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from ..config import Config

log = logging.getLogger(__name__)

MAX_PATH_CHARS = 259                 # 260 com o NUL final
_MAX_INPUT_CHARS = 520
_MAX_COMPONENT = 255
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_BENIGN_REPARSE_TAGS = frozenset({0x80000017})      # WOF (compressão do sistema)
_CLOUD_TAG_BASE = 0x9000001A                         # IO_REPARSE_TAG_CLOUD e variantes (OneDrive etc.)
_BAD_CHARS = frozenset('<>"|?*')
_DRIVE_RE = re.compile(r"^([A-Za-z]):(.*)$", re.S)

_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$", "clock$"}
    | {f"com{i}" for i in range(10)} | {f"lpt{i}" for i in range(10)}
    | {f"{p}{s}" for p in ("com", "lpt") for s in ("\u00b9", "\u00b2", "\u00b3")}
)

BLOCKED_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".sys", ".msi", ".msp", ".mst", ".pif", ".cpl", ".ocx", ".drv",
    ".ps1", ".psm1", ".psd1", ".ps1xml", ".vbs", ".vbe", ".vb", ".js", ".jse", ".mjs", ".wsf", ".wsh", ".hta",
    ".lnk", ".url", ".scf", ".reg", ".inf", ".jar", ".jnlp", ".msc", ".gadget", ".application", ".appref-ms",
    ".appx", ".msix", ".appxbundle", ".msixbundle", ".chm", ".library-ms", ".searchconnector-ms",
    ".py", ".pyw", ".pyc", ".pyz", ".sh", ".bash", ".pl", ".rb", ".php", ".lua",
    ".docm", ".xlsm", ".pptm", ".dotm", ".xlam", ".ppam", ".iso", ".vhd", ".vhdx",
    ".wsc", ".sct", ".ws", ".psc1", ".settingcontent-ms", ".xll", ".diagcab", ".rdp", ".theme", ".themepack",
    ".vba", ".bas", ".hlp", ".shs", ".mde", ".ade", ".cab",
})

# Criar NÃO é bloqueado, mas executa script no navegador: exige confirmação FORTE (ver `strong_confirm_extension`).
STRONG_CONFIRM_EXTENSIONS: frozenset[str] = frozenset({
    ".html", ".htm", ".svg", ".xhtml", ".xht", ".mht", ".mhtml", ".xml-stylesheet",
})

# Nomes sensíveis (senhas, chaves, cookies): nem lê nem escreve, em qualquer pasta liberada.
_SENSITIVE_NAMES: frozenset[str] = frozenset({
    ".env", "credentials.json", ".npmrc", ".netrc", ".pgpass", "cookies", "login data", "web data",
})
_SENSITIVE_STEMS: frozenset[str] = frozenset({"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"})   # com ou sem extensão (.pub, .bak)
_SENSITIVE_SUFFIXES: tuple[str, ...] = (".kdbx", ".pem", ".pfx", ".key", ".p12", ".ppk")
_SENSITIVE_DIRS: frozenset[str] = frozenset({".ssh", ".aws", ".gnupg"})


def is_sensitive_name(component: str) -> bool:
    """True se o nome (arquivo ou pasta) é típico de segredo: .env, chaves privadas, cofres, cookies, credenciais."""
    low = component.casefold().rstrip(" .")
    if low in _SENSITIVE_NAMES or low in _SENSITIVE_DIRS or low.startswith(".env."):
        return True
    return low.split(".", 1)[0] in _SENSITIVE_STEMS or low.endswith(_SENSITIVE_SUFFIXES)


class SandboxError(Exception):
    """Caminho recusado. A mensagem já é curta e pode ser falada."""


def _cf_parts(path: str | os.PathLike[str]) -> tuple[str, ...]:
    return tuple(p.casefold() for p in PureWindowsPath(os.fspath(path)).parts)


def _is_prefix(prefix: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    return len(prefix) <= len(parts) and parts[:len(prefix)] == prefix


def is_reparse(st: os.stat_result) -> bool:
    """True para link simbólico, junção ou qualquer reparse point que não seja marcador benigno de nuvem/compressão."""
    attrs = getattr(st, "st_file_attributes", 0)
    if stat.S_ISLNK(st.st_mode):
        return True
    if not attrs & _FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(st, "st_reparse_tag", 0)
    if tag in _BENIGN_REPARSE_TAGS or (tag & 0xFFFF0FFF) == _CLOUD_TAG_BASE:
        return False
    return True


def is_reserved_name(component: str) -> bool:
    stem = component.split(".", 1)[0].rstrip(" ").casefold()
    return stem in _RESERVED


def _extension_of(name: str) -> str | None:
    low = name.casefold().rstrip(" .")
    dot = low.rfind(".")
    return low[dot:] if dot >= 0 else None


def blocked_extension(name: str) -> str | None:
    """Extensão bloqueada do nome (ex.: '.exe') ou None."""
    ext = _extension_of(name)
    return ext if ext in BLOCKED_EXTENSIONS else None


def strong_confirm_extension(name: str) -> str | None:
    """Extensão que exige confirmação FORTE para criar (ex.: '.html', '.svg') ou None."""
    ext = _extension_of(name)
    return ext if ext in STRONG_CONFIRM_EXTENSIONS else None


def _forbidden_root_paths() -> list[tuple[str, str]]:
    """(rótulo, caminho) de pastas que NUNCA podem ser raiz, nem estar dentro de uma raiz, nem ser contidas por ela."""
    env = os.environ
    home = env.get("USERPROFILE") or str(Path.home())
    out: list[tuple[str, str]] = [("AppData", str(Path(home) / "AppData")),
                                  (".ssh", str(Path(home) / ".ssh")), (".aws", str(Path(home) / ".aws")),
                                  (".gnupg", str(Path(home) / ".gnupg"))]
    for label, var in (("AppData", "APPDATA"), ("AppData", "LOCALAPPDATA"), ("ProgramData", "ProgramData"),
                       ("ProgramData", "ALLUSERSPROFILE")):
        if env.get(var):
            out.append((label, env[var]))
    out.append(("ProgramData", r"C:\ProgramData"))
    for label, base in (("a pasta Inicializar", env.get("APPDATA")), ("a pasta Inicializar", env.get("ProgramData"))):
        if base:
            for leaf in ("Startup", "Inicializar"):
                out.append((label, str(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / leaf)))
    return out


@dataclass(frozen=True)
class _Root:
    real: str                         # realpath da raiz
    real_cf: tuple[str, ...]
    cfg_cf: tuple[str, ...]           # forma configurada (pode divergir do real se a raiz passa por junção)


class Sandbox:
    def __init__(self, cfg: Config) -> None:
        self._configured = tuple(cfg.files.roots)
        p = cfg.paths
        env = os.environ
        raw: list[tuple[str, str]] = [("a pasta do projeto", str(p.root)), ("a pasta de dados", str(p.data)),
                                      ("a pasta de logs", str(p.logs)), ("o config.toml", str(p.root / "config.toml")),
                                      ("a pasta do Windows", env.get("SystemRoot") or env.get("windir") or r"C:\Windows")]
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            if env.get(var):
                raw.append(("Program Files", env[var]))
        self._protected: list[tuple[str, tuple[str, ...]]] = []
        for label, text in raw:
            try:
                self._protected.append((label, _cf_parts(os.path.realpath(text))))
                lex = _cf_parts(os.path.abspath(text))
                if lex != self._protected[-1][1]:
                    self._protected.append((label, lex))
            except (OSError, ValueError):
                log.warning("sandbox: não consegui resolver a pasta protegida %r", text)
        # Raízes proibidas: o perfil inteiro (ou qualquer pasta que o contenha) e pastas sensíveis (AppData, ProgramData,
        # Inicializar, .ssh, .aws, .gnupg), tanto dentro delas quanto contendo-as. Uma raiz precisa estar ESTRITAMENTE
        # dentro de uma subpasta do perfil (ex.: Documents\Jarvis).
        home = env.get("USERPROFILE") or str(Path.home())
        self._home_parts: list[tuple[str, ...]] = []
        self._sensitive_roots: list[tuple[str, tuple[str, ...]]] = []
        for text in {home, str(Path.home())}:
            self._home_parts.extend(self._both_forms(text))
        for label, text in _forbidden_root_paths():
            self._sensitive_roots.extend((label, parts) for parts in self._both_forms(text))
        self._warned: set[str] = set()

    @staticmethod
    def _both_forms(text: str) -> list[tuple[str, ...]]:
        """Forma léxica e forma real (realpath) de um caminho, em partes casefold, sem repetir."""
        forms: list[tuple[str, ...]] = []
        for fn in (os.path.abspath, os.path.realpath):
            try:
                parts = _cf_parts(fn(text))
            except (OSError, ValueError):
                continue
            if parts not in forms:
                forms.append(parts)
        return forms

    def _forbidden_root_reason(self, parts: tuple[str, ...]) -> str | None:
        """Motivo pelo qual `parts` (casefold) não pode ser raiz de arquivos, ou None."""
        for home in self._home_parts:
            if _is_prefix(parts, home):                        # é o perfil ou uma pasta que o contém (ex.: C:\Users)
                return "o perfil do usuário inteiro (use uma subpasta, como Documents\\Jarvis)"
        for label, prot in self._sensitive_roots:
            if _is_prefix(prot, parts) or _is_prefix(parts, prot):
                return f"{label} (sensível)"
        if any(p in _SENSITIVE_DIRS for p in parts):
            return "uma pasta de chaves (.ssh, .aws, .gnupg)"
        for i in range(len(parts) - 1):
            if parts[i] == "programs" and parts[i + 1] in ("startup", "inicializar"):
                return "a pasta Inicializar"
        return None

    # ------------------------------------------------------------ raízes
    def _roots(self) -> list[_Root]:
        out: list[_Root] = []
        for text in self._configured:
            try:
                absolute = os.path.abspath(text)
                real = os.path.realpath(absolute)
            except (OSError, ValueError):
                self._warn(text, "não consegui resolver")
                continue
            if real.startswith("\\\\") or not _DRIVE_RE.match(real):
                self._warn(text, "caminho de rede/UNC não é permitido")
                continue
            parts = _cf_parts(real)
            if len(parts) <= 1:
                self._warn(text, "raiz de disco não é permitida")
                continue
            if self._protected_label(parts, ancestor=False):
                self._warn(text, "é uma pasta protegida")
                continue
            forbidden = self._forbidden_root_reason(parts) or self._forbidden_root_reason(_cf_parts(absolute))
            if forbidden:
                self._warn(text, f"raiz proibida: {forbidden}")
                continue
            out.append(_Root(real, parts, _cf_parts(absolute)))
        return out

    def _warn(self, text: str, why: str) -> None:
        if text not in self._warned:
            self._warned.add(text)
            log.warning("sandbox: raiz ignorada %r: %s", text, why)

    @property
    def roots(self) -> tuple[Path, ...]:
        return tuple(Path(r.real) for r in self._roots())

    def default_root(self) -> Path:
        roots = self._roots()
        if not roots:
            raise SandboxError("Não há nenhuma pasta liberada para mexer em arquivos. Configure files.roots.")
        return Path(roots[0].real)

    def is_root(self, path: Path) -> bool:
        parts = _cf_parts(path)
        return any(parts == r.real_cf for r in self._roots())

    def _protected_label(self, parts: tuple[str, ...], *, ancestor: bool = True) -> str | None:
        for label, prot in self._protected:
            if _is_prefix(prot, parts) or (ancestor and _is_prefix(parts, prot)):
                return label
        return None

    # ------------------------------------------------------------ extensões
    def check_write_extension(self, path: Path | str, *, source: Path | str | None = None) -> None:
        """Recusa criar/editar executáveis e scripts. Mover/renomear mantendo a mesma extensão bloqueada é permitido
        (`source` informado): é só mudar de lugar, não criar programa."""
        name = Path(path).name
        ext = blocked_extension(name)
        if ext is None:
            return
        if source is not None and blocked_extension(Path(source).name) == ext:
            return
        raise SandboxError(f"Não crio nem edito arquivos {ext}: são programas ou scripts.")

    # ------------------------------------------------------------ resolução
    def _parse(self, text: object) -> tuple[str | None, list[str]]:
        if not isinstance(text, str):
            raise SandboxError("O caminho precisa ser um texto.")
        s = text.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        if not s:
            raise SandboxError("O caminho está vazio.")
        if len(s) > _MAX_INPUT_CHARS:
            raise SandboxError("O caminho é longo demais.")
        for ch in s:
            cat = unicodedata.category(ch)
            if cat in ("Cc", "Cs") or cat == "Cf":
                raise SandboxError("O caminho tem caracteres invisíveis ou de controle.")
            if ch in _BAD_CHARS:
                raise SandboxError(f"O caminho tem o caractere inválido {ch!r}.")
        s = s.replace("/", "\\")
        if s.startswith("\\\\"):
            raise SandboxError("Caminhos de rede (UNC) ou com prefixo especial não são permitidos.")
        drive: str | None = None
        m = _DRIVE_RE.match(s)
        if m:
            rest = m.group(2)
            if not rest.startswith("\\"):
                raise SandboxError("Use o caminho completo com a barra depois da unidade (ex.: C:\\pasta).")
            drive = m.group(1).upper() + ":"
            s = rest
        if ":" in s:
            raise SandboxError("Fluxos alternativos do NTFS (nome:fluxo) não são permitidos.")
        if drive is None and s.startswith("\\"):
            raise SandboxError("Informe o caminho completo com a unidade ou um caminho relativo à pasta liberada.")
        comps: list[str] = []
        for c in s.split("\\"):
            if c in ("", "."):
                continue
            if c == "..":
                raise SandboxError("Não aceito '..' em caminhos.")
            if c != c.rstrip(" .") or len(c) > _MAX_COMPONENT:
                raise SandboxError(f"Nome inválido no caminho: {c[:40]!r} (termina em ponto/espaço ou é longo demais).")
            comps.append(c)
        return drive, comps

    def resolve(self, path_text: str, must_exist: bool = False) -> Path:
        """Valida e resolve `path_text` para o caminho REAL dentro de uma raiz. Levanta SandboxError."""
        drive, comps = self._parse(path_text)
        roots = self._roots()
        if not roots:
            raise SandboxError("Não há nenhuma pasta liberada para mexer em arquivos. Configure files.roots.")

        if drive is None:
            root, rel = roots[0], comps
        else:
            abs_cf = (drive.casefold() + "\\",) + tuple(c.casefold() for c in comps)
            best: tuple[int, _Root, int] | None = None
            for r in roots:
                for prefix in (r.real_cf, r.cfg_cf):
                    if _is_prefix(prefix, abs_cf) and (best is None or len(prefix) > best[0]):
                        best = (len(prefix), r, len(prefix))
            if best is None:
                raise SandboxError("Esse caminho está fora das pastas liberadas.")
            root, rel = best[1], comps[best[2] - 1:]

        for c in rel:
            if is_reserved_name(c):
                raise SandboxError(f"O nome {c!r} é reservado do Windows.")
            if is_sensitive_name(c):
                raise SandboxError(f"O nome {c[:40]!r} é típico de segredo (senha, chave, cookie); não leio nem escrevo.")

        cur = root.real
        exists = True
        for i, c in enumerate(rel):
            nxt = os.path.join(cur, c)
            try:
                st = os.lstat(nxt)
            except FileNotFoundError:
                exists = False
                break
            except OSError as exc:
                raise SandboxError(f"Não consegui acessar {c!r}: {exc.strerror or type(exc).__name__}.") from exc
            if is_reparse(st):
                raise SandboxError(f"{c!r} é um atalho/link; não sigo links por segurança.")
            if i < len(rel) - 1 and not stat.S_ISDIR(st.st_mode):
                raise SandboxError(f"{c!r} não é uma pasta.")
            cur = nxt
        full = os.path.join(root.real, *rel) if rel else root.real
        try:
            final = os.path.realpath(full)
        except (OSError, ValueError) as exc:
            raise SandboxError("Não consegui resolver o caminho.") from exc
        if final.startswith("\\\\?\\") and not final.startswith("\\\\?\\UNC"):
            final = final[4:]
        final_cf = _cf_parts(final)
        expected = root.real_cf + tuple(c.casefold() for c in rel)
        if final_cf != expected:
            raise SandboxError("O caminho passa por link ou nome abreviado e não bate com a pasta liberada.")
        label = self._protected_label(final_cf)
        if label:
            raise SandboxError(f"Esse caminho envolve {label}, que é protegido.")
        if len(final) > MAX_PATH_CHARS:
            raise SandboxError("O caminho é longo demais (limite de 259 caracteres).")
        if must_exist and not exists:
            raise SandboxError("Esse arquivo ou pasta não existe.")
        return Path(final)

    def relative_to_root(self, path: Path) -> str:
        """Caminho curto (relativo à raiz que o contém) para mensagens; se não achar, o nome."""
        parts = _cf_parts(path)
        for r in self._roots():
            if _is_prefix(r.real_cf, parts):
                rest = Path(path).parts[len(r.real_cf):]
                return "\\".join(rest) or "."
        return Path(path).name
