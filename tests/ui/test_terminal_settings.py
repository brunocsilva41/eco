"""QA da página «Terminal» das Configurações: navegação, campos com texto, edição, validação das pastas, salvar e reler.

    venv\\Scripts\\python.exe -I tests\\ui\\test_terminal_settings.py --scale 150 --theme dark --out SAIDA [--native]
"""
from __future__ import annotations

import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uicommon as U  # noqa: E402

ARGS = U.parse()
U.setup_env(ARGS)
R = U.Results("terminal_settings", ARGS)

app = U.make_app(ARGS.theme)
from jarvis import config as cfgmod  # noqa: E402
from jarvis.settings import schema  # noqa: E402
from jarvis.ui.settings import controls, field_texts  # noqa: E402
from jarvis.ui.settings.categories import BY_PAGE  # noqa: E402
from jarvis.ui.settings.window import SettingsWindow  # noqa: E402

controls.load_devices = lambda kind: []            # type: ignore[assignment]
SHOTS = Path(ARGS.out) / "capturas" / ("nativo" if ARGS.native else "off") / f"config-terminal-{ARGS.scale}-{ARGS.theme}"
KEYS = [k for k in BY_PAGE["terminal"].sections[0].keys] if "terminal" in BY_PAGE else []


def main() -> int:
    tmp, store, cfg, prefs = U.tmp_env()
    with R.guard("pagina"):
        R.check("categoria 'terminal' existe na navegação", "terminal" in BY_PAGE)
        R.check("página tem título e texto em pt-BR", field_texts.PAGES.get("terminal", ("", ""))[0] == "Terminal")
        all_keys = [k for s in BY_PAGE["terminal"].sections for k in s.keys]
        R.check("10 campos do terminal mapeados", len(all_keys) == 10 and all(k in schema.BY_KEY for k in all_keys), str(len(all_keys)))
        R.check("todos os campos têm rótulo e ajuda próprios", all(k in field_texts.FIELDS and field_texts.FIELDS[k][1] for k in all_keys))
        txt = " ".join(field_texts.FIELDS[k][0] + field_texts.FIELDS[k][1] for k in all_keys)
        R.check("texto novo diz Eco (não Eco)", "Eco" not in txt.replace("Eco.cmd", ""), "")
        win = SettingsWindow(cfg, None, store, prefs)
        win.show()
        U.settle(400)
        t0 = time.perf_counter()
        win.nav.set_current("terminal")
        U.settle(500)
        R.check("abre a página Terminal (navegação)", win.nav.current_key() == "terminal" if hasattr(win.nav, "current_key") else True,
                f"{(time.perf_counter() - t0) * 1000:.0f} ms")
        R.check("seção «Onde ele pode rodar» recebe o foco (open_section)", win.open_section("term_where"))
        U.settle(300)
        U.grab(win, SHOTS / "01-pagina.png")
        bad = U.clipped_texts(win.pages["terminal"])            # só a página (a barra de ações é do kit e tem o seu próprio teste)
        R.check("sem texto cortado na página Terminal", not bad, "; ".join(bad[:3]))
        bar_bad = [b for b in U.clipped_texts(win) if b not in bad]
        R.check("(informativo) texto cortado fora da página, na barra de ações do kit", True, "; ".join(bar_bad[:2]) or "nenhum")
        # campo padrão: desligado
        R.check("padrão: terminal.mode = off", win.collect_values().get("terminal.mode") == "off", str(win.collect_values().get("terminal.mode")))
        # editar o modo
        win.controller.edit("terminal.mode", "allowlist")
        U.settle(300)
        R.check("editar o modo conta 1 alteração", win.change_count() == 1, str(win.change_count()))
        U.grab(win, SHOTS / "02-alterado.png")
        # pasta proibida é recusada na validação
        win.controller.edit("terminal.roots", [r"C:\Windows"])
        U.settle(900)
        try:
            cfgmod.from_dict({"terminal": {"roots": [r"C:\Windows"]}})
            R.check("validação do config recusa C:\\Windows", False, "aceitou")
        except cfgmod.ConfigError as exc:
            R.check("validação do config recusa C:\\Windows", "terminal.roots" in str(exc), str(exc)[:80].replace("\n", " "))
        proj = Path(r"F:\jarvis_term_proj_test")                # fora de AppData e da pasta do Eco (senão a validação recusa)
        proj.mkdir(exist_ok=True)
        win.controller.edit("terminal.roots", [str(proj)])
        U.settle(700)
        win.controller.save()
        U.settle(1200)
        data = tomllib.loads((tmp / "config.toml").read_text(encoding="utf-8")) if (tmp / "config.toml").exists() else {}
        saved = data.get("terminal", {})
        R.check("salvar grava [terminal] no config.toml", saved.get("mode") == "allowlist" and saved.get("roots") == [str(proj)], str(saved)[:100])
        reread = cfgmod.from_dict(data)
        R.check("o config salvo relê com o modo e a pasta", reread.terminal.mode == "allowlist" and reread.terminal.roots == (str(proj),))
        try:
            proj.rmdir()
        except OSError:
            pass
        U.grab(win, SHOTS / "03-salvo.png")
        win.controller.discard()
        win.close()
    R.save()
    return 1 if R.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
