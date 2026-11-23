"""Etapa 'varredura de privacidade': segredos, e-mails pessoais e autores do historico. So biblioteca padrao.

Uso:
    python -I tools/ci/scan_repo.py [--history] [--root .]

Regras (arquivos rastreados pelo git; texto):
  FALHA  token/chave privada conhecidos (ghp_, github_pat_, sk-, AKIA, AIza, xox*, '-----BEGIN ... PRIVATE KEY-----')
  FALHA  atribuicao suspeita: (api_key|secret|password|token) = "valor longo"   (valores obviamente falsos sao ignorados)
  FALHA  e-mail que nao esteja na lista permitida (noreply do GitHub, example.*, dominios de documentacao)
  AVISO  caminho pessoal 'C:\\Users\\<nome>' (aparece no relatorio, nao reprova)
Com --history: tambem varre o diff de TODOS os commits e FALHA se algum autor/committer nao usar o e-mail noreply do GitHub.
Excecoes pontuais ficam em tools/ci/scan-allow.txt (uma por linha: caminho-glob|regra), nunca valores de segredo.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SECRET_PATTERNS = {
    "github-token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    "openai-like-key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |)PRIVATE KEY-----"),
    "assigned-secret": re.compile(
        r"""(?i)\b(?:api[_-]?key|secret|passw(?:or)?d|token)\b\s*[:=]\s*["'](?P<v>[A-Za-z0-9_\-/+=]{20,})["']"""),
}
FAKE_VALUE = re.compile(r"(?i)(x{4,}|\*{3,}|example|exemplo|dummy|fake|test|teste|placeholder|changeme|your|seu_|<.*>)")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
EMAIL_OK = re.compile(
    r"(?i)(@users\.noreply\.github\.com|@example\.(com|org|net)|@exemplo\.(com|org|net|com\.br)|^noreply@|^no-reply@|"
    r"@anthropic\.com$|@localhost$|\.(dll|exe|sys|lib|so|dylib|py|js|ts|json|md|txt|png|svg)$)")
USER_PATH = re.compile(r"[A-Za-z]:\\Users\\(?!<|%|\{|\$|Public|Default|All Users|usuario|user\b|seu|you\b|NOME|name\b)[A-Za-z][\w .-]{1,30}")
NOREPLY = re.compile(r"(?i)^(\d+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com$|^noreply@github\.com$")
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".exe", ".dll", ".zip", ".onnx", ".gguf", ".pyc", ".woff", ".woff2", ".wav", ".mp3", ".pdf"}


def load_allow(root: Path) -> list[tuple[str, str]]:
    f = root / "tools" / "ci" / "scan-allow.txt"
    out = []
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "|" in ln:
                g, r = ln.split("|", 1)
                out.append((g.strip(), r.strip()))
    return out


def allowed(allow, path: str, rule: str) -> bool:
    return any(fnmatch.fnmatch(path, g) and r in (rule, "*") for g, r in allow)


def scan_text(text: str, path: str, allow) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:
            continue
        for rule, rx in SECRET_PATTERNS.items():
            m = rx.search(line)
            if not m:
                continue
            if rule == "assigned-secret" and FAKE_VALUE.search(m.group("v")):
                continue
            if not allowed(allow, path, rule):
                fails.append(f"{path}:{n}: [{rule}] (valor omitido)")
        for m in EMAIL.finditer(line):
            e = m.group(0)
            if EMAIL_OK.search(e):
                continue
            if not allowed(allow, path, "email"):
                local, _, dom = e.partition("@")
                fails.append(f"{path}:{n}: [email] {local[:2]}***@{dom}")
        if USER_PATH.search(line) and not allowed(allow, path, "user-path"):
            warns.append(f"{path}:{n}: [caminho-pessoal]")
    return fails, warns


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--history", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)
    allow = load_allow(root)
    fails: list[str] = []
    warns: list[str] = []

    files = [p for p in git(root, "ls-files", "-z").split("\0") if p]
    scanned = 0
    for rel in files:
        p = root / rel
        if p.suffix.lower() in SKIP_EXT or not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        f, w = scan_text(text, rel.replace("\\", "/"), allow)
        fails += f
        warns += w

    if a.history:
        ids = git(root, "log", "--all", "--format=%an <%ae>%n%cn <%ce>").splitlines()
        bad = sorted({ln for ln in ids if ln.strip() and not NOREPLY.match(ln.split("<")[-1].rstrip(">").strip())})
        for ln in bad:
            local, _, dom = ln.split("<")[-1].rstrip(">").partition("@")
            fails.append(f"historico: autor/committer com e-mail nao-noreply: {local[:2]}***@{dom}")
        diff = git(root, "log", "--all", "-p", "--no-color", "--format=COMMIT %h", "--diff-filter=AM")
        cur, path = "", ""
        for ln in diff.splitlines():
            if ln.startswith("COMMIT "):
                cur = ln.split()[1]
            elif ln.startswith("+++ b/"):
                path = ln[6:]
            elif ln.startswith("+") and not ln.startswith("+++"):
                f, _ = scan_text(ln[1:], f"{path}@{cur}", allow)
                fails += [x for x in f if "[email]" not in x]  # e-mails antigos em diffs: tratados pela regra de autores
        print(f"historico: {len(ids) // 2} commits verificados")

    for w in warns[:25]:
        print("AVISO", w)
    if len(warns) > 25:
        print(f"AVISO ... e mais {len(warns) - 25} caminhos pessoais")
    if fails:
        for f in sorted(set(fails)):
            print("ERRO", f)
        print(f"FALHOU: {len(set(fails))} achado(s) em {scanned} arquivos")
        return 1
    print(f"OK: {scanned} arquivos rastreados sem segredos nem e-mails pessoais ({len(warns)} aviso(s) de caminho)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
