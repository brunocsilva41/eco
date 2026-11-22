"""Normalização do texto ANTES de falar (pt-BR): números, horas, datas, dinheiro, unidades, extensões e siglas viram palavras.

O Piper lê dígitos, "14:30", ".exe" e marcas em inglês de forma errada ou comendo palavras. Aqui tudo vira texto por extenso;
o texto mostrado na tela/transcrição NÃO muda. Pronúncias extras do Bruno: data/pronuncias.json ({"palavra": "como falar"}).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_UN = ("zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze",
       "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove")
_DEZ = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa")
_CEN = ("", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos")
_MESES = ("", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")


def _below_1000(n: int) -> str:
    if n < 20:
        return _UN[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _DEZ[d] + (f" e {_UN[u]}" if u else "")
    if n == 100:
        return "cem"
    c, r = divmod(n, 100)
    return _CEN[c] + (f" e {_below_1000(r)}" if r else "")


def number_to_words(n: int) -> str:
    if n < 0:
        return "menos " + number_to_words(-n)
    if n < 1000:
        return _below_1000(n)
    parts: list[tuple[int, str, str]] = [(10**9, "bilhão", "bilhões"), (10**6, "milhão", "milhões"), (1000, "mil", "mil")]
    if n >= 10**12:
        return " ".join(_UN[int(c)] for c in str(n))                     # absurdamente grande: soletra
    out: list[str] = []
    rest = n
    for size, one, many in parts:
        q, rest = divmod(rest, size)
        if q:
            out.append("mil" if size == 1000 and q == 1 else f"{_below_1000(q)} {one if q == 1 else many}")
    if rest:
        out.append(_below_1000(rest))
    if len(out) == 1:
        return out[0]
    last = out[-1]
    joiner = " e " if (rest and (rest < 100 or rest % 100 == 0)) else " "
    return ", ".join(out[:-1]).replace(", ", " ") + joiner + last if rest else " ".join(out)


def _fem(n: int) -> str:
    return {1: "uma", 2: "duas"}.get(n, number_to_words(n))


# ----------------------------------------------------------------------------- regras
_DATE_FULL = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DATE_SHORT = re.compile(r"\b(\d{1,2})/(\d{1,2})\b(?!/)")
_TIME = re.compile(r"\b(\d{1,2})\s?(?:h|:)\s?(\d{2})\b|\b(\d{1,2})\s?h\b(?!\w)")
_MONEY = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?\s+reais\b")
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")
_ORD = re.compile(r"\b(\d{1,2})[ºª°]")
_EXT_SPELL = {"exe": "é xis é", "pdf": "pê dê éfe", "txt": "tê xis tê", "png": "pê ene gê", "jpg": "jota pê gê", "jpeg": "jota pê gê",
              "mp4": "ême pê quatro", "mp3": "ême pê três", "docx": "doc xis", "xlsx": "éxel", "pptx": "pê pê tê xis", "zip": "zip",
              "gif": "guif", "csv": "cê ésse vê", "json": "jêi són", "py": "pê ípsilon", "md": "ême dê", "dll": "dê éle éle",
              "bat": "bát", "cmd": "cê ême dê", "ps1": "pê ésse um", "wav": "uêiv", "mkv": "ême cá vê", "iso": "í ésse ó"}
_EXT = re.compile(r"\.(" + "|".join(sorted(_EXT_SPELL, key=len, reverse=True)) + r")\b", re.I)

_PRON: dict[str, str] = {
    "jarvis": "Járvis", "windows": "Uíndous", "whatsapp": "Uótsape", "youtube": "Iutúbi", "spotify": "Espotifái",
    "photoshop": "Fótoshópi", "chrome": "Cróume", "discord": "Discórdi", "telegram": "Telegrã", "outlook": "Autlúque",
    "excel": "Équicel", "powerpoint": "Páuerpóint", "firefox": "Faiarfóx", "bluetooth": "Blutúfe", "wi-fi": "uai fai",
    "wifi": "uai fai", "usb": "u ésse bê", "cpu": "cê pê u", "gpu": "gê pê u", "ram": "rã", "ok": "ôquei", "ia": "í á",
    "pdf": "pê dê éfe", "url": "u érre éle", "hdmi": "agá dê ême í", "ssd": "ésse ésse dê", "pc": "pê cê", "sql": "ésse quê éle",
    "openbot": "Ópenbót", "gmail": "Gimeil", "google": "Gúgol", "instagram": "Instagrã", "facebook": "Feisbúque",
    "obs": "ó bê ésse", "vscode": "vi ésse côude", "github": "Guitráb", "linkedin": "Linkedín", "notepad": "Nótepéd",
}
_UNITS: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(p, re.I), r) for p, r in (
    (r"(?<=\d)\s?gb\b", " gigabytes"), (r"(?<=\d)\s?mb\b", " megabytes"), (r"(?<=\d)\s?kb\b", " quilobytes"),
    (r"(?<=\d)\s?tb\b", " terabytes"), (r"(?<=\d)\s?ghz\b", " gigahertz"), (r"(?<=\d)\s?mhz\b", " megahertz"),
    (r"(?<=\d)\s?kg\b", " quilos"), (r"(?<=\d)\s?cm\b", " centímetros"), (r"(?<=\d)\s?mm\b", " milímetros"),
    (r"(?<=\d)\s?fps\b", " quadros por segundo"), (r"(?<=\d)\s?ms\b", " milissegundos"), (r"(?<=\d)\s?min\b", " minutos"),
    (r"(?<=\d)\s?w\b", " watts"), (r"(?<=\d)\s?mah\b", " miliamperes-hora"),
))
_pron_cache: tuple[float, dict[str, str]] | None = None


def _user_pronunciations() -> dict[str, str]:
    global _pron_cache
    p = Path(__file__).resolve().parents[3] / "data" / "pronuncias.json"
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    if _pron_cache is None or _pron_cache[0] != mtime:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            _pron_cache = (mtime, {str(k).lower(): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {})
        except (OSError, ValueError):
            log.warning("data/pronuncias.json inválido; ignorando")
            _pron_cache = (mtime, {})
    return _pron_cache[1]


def _time_words(h: int, m: int) -> str:
    if h > 24 or m > 59:
        return f"{h} {m}"
    hh = _fem(h) if h <= 12 else number_to_words(h)
    if m == 0:
        return f"{hh} hora" + ("" if h == 1 else "s")
    return f"{hh} e {number_to_words(m)}"


def _decimal_words(txt: str) -> str:
    whole, _, frac = txt.replace(".", "").partition(",")
    out = number_to_words(int(whole))
    if frac:
        lead = len(frac) - len(frac.lstrip("0"))
        out += " vírgula " + " ".join(["zero"] * lead + ([number_to_words(int(frac))] if frac.strip("0") else []))
    return out


def normalize(text: str) -> str:
    s = text
    s = _DATE_FULL.sub(lambda m: f"{number_to_words(int(m[1]))} de {_MESES[int(m[2])]} de {number_to_words(int(m[3]))}"
                       if 1 <= int(m[2]) <= 12 else m[0], s)
    s = _DATE_SHORT.sub(lambda m: f"{number_to_words(int(m[1]))} de {_MESES[int(m[2])]}" if 1 <= int(m[2]) <= 12 and 1 <= int(m[1]) <= 31 else m[0], s)
    s = _TIME.sub(lambda m: _time_words(int(m[1]), int(m[2])) if m[1] else _time_words(int(m[3]), 0), s)

    def money(m: re.Match[str]) -> str:
        whole = int(m[1].replace(".", ""))
        cents = int(m[2].ljust(2, "0")) if m[2] else 0
        out = number_to_words(whole) + (" real" if whole == 1 else " reais")
        return out + (f" e {number_to_words(cents)} centavo{'s' if cents != 1 else ''}" if cents else "")
    s = _MONEY.sub(money, s)
    s = _ORD.sub(lambda m: number_to_words(int(m[1])), s)
    for pat, rep in _UNITS:
        s = pat.sub(rep, s)
    s = _EXT.sub(lambda m: " ponto " + _EXT_SPELL[m[1].lower()], s)
    s = _NUMBER.sub(lambda m: _decimal_words(m[0]), s)
    table = {**_PRON, **_user_pronunciations()}
    if table:
        pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(k) for k in sorted(table, key=len, reverse=True)) + r")(?![\w-])", re.I)
        s = pattern.sub(lambda m: table[m[1].lower()], s)
    return s
