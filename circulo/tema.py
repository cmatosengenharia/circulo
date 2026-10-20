"""Tema único das telas do loop: as cores, os botões, os chips e a legenda são os mesmos em todas as páginas.

Antes cada página tinha a sua cópia dos tokens, e no modo claro o texto verde (3,96:1) e âmbar (3,45:1) ficava abaixo
do mínimo de leitura (4,5:1), o "cinza de inativo" (1,9:1) sumia, a borda dos botões (1,3:1) não se via e os estados
eram só cor. Regras daqui em diante (WCAG 2.2 e o método do skill de visualização de dados):
- texto e ícone de status >= 4,5:1 sobre a superfície e sobre o fundo suave do próprio chip, nos dois modos;
- borda de botão/campo (limite de componente) e marcas >= 3:1 (`--border`, `--idle`); `--line` só divide, não delimita;
- cor nunca é a única pista: cada tom de chip tem glifo (✓ ✕ ! ◆), a legenda do fluxo usa formas, o botão tem estado
  de foco (anel de 3 px), pressionado e desativado visíveis;
- um só lugar define tudo: `aplicar()` escreve o mesmo bloco nas páginas e tests/test_tema.py barra divergência e
  confere os contrastes.
"""
from __future__ import annotations

import re
from pathlib import Path

CLARO = {
    "--bg": "#E9EDF1", "--surface": "#F7F9FB", "--line": "#D3DAE1", "--border": "#7B8794", "--hover": "#E1E7ED",
    "--ink": "#17212B", "--muted": "#556270",
    "--jev": "#4B3FD1", "--jev-soft": "#E3E0FB", "--llm": "#8A5608", "--llm-soft": "#F6E6CC",
    "--ok": "#146B53", "--ok-soft": "#D3EDE4", "--bad": "#B02A1C", "--bad-soft": "#F8DBD6",
    "--idle": "#76828F", "--gh": "#2B3440", "--node": "#FFFFFF", "--accent": "#4B3FD1", "--on-accent": "#FFFFFF",
}
ESCURO = {
    "--bg": "#10161D", "--surface": "#18212B", "--line": "#2A3542", "--border": "#617080", "--hover": "#233140",
    "--ink": "#E6ECF2", "--muted": "#9AA8B5",
    "--jev": "#8E84FF", "--jev-soft": "#262249", "--llm": "#E0A53F", "--llm-soft": "#3A2C14",
    "--ok": "#3FBF98", "--ok-soft": "#16352C", "--bad": "#F06A5B", "--bad-soft": "#3E1C19",
    "--idle": "#7F8C9B", "--gh": "#C9D3DD", "--node": "#1F2A36", "--accent": "#8E84FF", "--on-accent": "#10161D",
}
# pares (texto, fundo) que precisam de 4,5:1 e (marca/borda, fundo) que precisam de 3:1 — conferidos no teste
TEXTO = [("--ink", "--surface"), ("--ink", "--bg"), ("--muted", "--surface"), ("--muted", "--bg"), ("--jev", "--surface"), ("--jev", "--jev-soft"),
         ("--llm", "--surface"), ("--llm", "--llm-soft"), ("--ok", "--surface"), ("--ok", "--ok-soft"), ("--bad", "--surface"),
         ("--bad", "--bad-soft"), ("--on-accent", "--accent"), ("--surface", "--ink"), ("--surface", "--ok"), ("--surface", "--bad"), ("--surface", "--jev")]
MARCA = [("--border", "--surface"), ("--border", "--bg"), ("--idle", "--surface"), ("--jev", "--surface"), ("--llm", "--surface"),
         ("--ok", "--surface"), ("--bad", "--surface")]

INI, FIM = "/*TEMA:ini*/", "/*TEMA:fim*/"
NAV_INI, NAV_FIM = "<!--NAV:ini-->", "<!--NAV:fim-->"
# o menu de cima, igual em todas as telas (1.31): nomes dizem o que a tela é, não como foi feita
MENU = (("/", "Missões", "As missões suas e a do próprio loop"),
        ("/equipe", "Equipe ao vivo", "Os agentes como um time: quem faz o quê agora, a conversa e o quadro de entregas"),
        ("/loop", "Gestão do loop", "Saúde, decisões, evolução e segurança do loop"),
        ("/fluxo", "Bastidores do giro", "O giro passo a passo: raias, obras e cada verificação"),
        ("/rastros", "Rastros e SLOs", "Rastro de ponta a ponta de cada mudança, sinais de ouro e SLOs"),
        ("/integracoes", "Integrações", "Chaves do Jev, da LLM e do GitHub no cofre do sistema"),
        ("/aprovacoes", "Precisa de você", "Tudo o que está parado esperando uma decisão sua, com a ação do lado"))
SELO = '<span class="selo" id="seloAprov" hidden></span>'     # contagem do "Precisa de você", em toda tela
NAV = (f'{NAV_INI}<nav class="topo" id="navTopo" aria-label="Telas do círculo"><a class="marca" href="/">Círculo</a><div class="topo-links">'
       + "".join(f'<a href="{h}" title="{t}">{n}{SELO if h == "/aprovacoes" else ""}</a>' for h, n, t in MENU)
       + '</div><span class="topo-estado" id="topoEstado" aria-live="polite"></span></nav>'
       '<script>(function(){var p=location.pathname,e=/embed=1/.test(location.search),n=document.getElementById("navTopo");if(!n)return;if(e){n.hidden=true;return;}'
       'var atual=p==="/"?"/":p.startsWith("/missao/")||p==="/loop"?"/loop":"/"+p.split("/")[1];n.querySelectorAll("a[href]").forEach(function(a){if(a.getAttribute("href")===atual)a.setAttribute("aria-current","page");});'
       'function selo(){fetch("/api/aprovacoes?so=n").then(function(r){return r.json()}).then(function(j){var s=document.getElementById("seloAprov");if(!s)return;s.hidden=!j.total;s.textContent=j.total;s.dataset.u=j.urgentes>0?"1":"0";}).catch(function(){});}selo();setInterval(selo,15000);})();</script>'
       f'{NAV_FIM}\n')


def _vars(d: dict) -> str:
    return "".join(f"{k}:{v};" for k, v in d.items())


TOKENS = (f":root{{{_vars(CLARO)}}}\n"
          f"@media (prefers-color-scheme:dark){{:root{{{_vars(ESCURO)}}}}}")

# Componentes: vêm DEPOIS das regras da página para valerem sobre elas (mesma especificidade, última ganha).
COMPONENTES = """
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.topo{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:14px;padding:8px 16px;background:var(--surface);border-bottom:1.5px solid var(--line);margin:0 0 14px}
.topo .marca{font-weight:800;letter-spacing:.2px;color:var(--ink);text-decoration:none;font-size:17px;padding:6px 8px 6px 0}
.topo .marca::before{content:"";display:inline-block;width:12px;height:12px;border-radius:50%;border:3px solid var(--accent);margin-right:8px;vertical-align:-1px}
.topo-links{display:flex;flex-wrap:wrap;gap:2px}
.topo-links a{color:var(--muted);text-decoration:none;font-weight:600;font-size:14px;padding:7px 11px;border-radius:8px;border:1.5px solid transparent}
.topo-links a:hover{background:var(--hover);color:var(--ink)}
.topo-links a[aria-current=page]{color:var(--ink);background:var(--bg);border-color:var(--border)}
.topo-estado{margin-left:auto;font-size:13px;color:var(--muted);white-space:nowrap}
.topo-links .selo{display:inline-block;min-width:18px;padding:0 6px;margin-left:6px;border-radius:999px;background:var(--jev);color:var(--surface);font-size:11.5px;font-weight:800;text-align:center;vertical-align:1px}
.topo-links .selo[data-u="1"]{background:var(--bad)}
a.back{display:none !important}
@media (max-width:720px){.topo{gap:8px;padding:6px 12px}.topo-links{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch}.topo-links a{padding:6px 8px;font-size:13px;white-space:nowrap}.topo-estado{display:none}}
.btn,.abas button,.sugestoes button,.vel button,.giros button,.seg button{transition:background .12s,border-color .12s,color .12s}
.btn{border:1.5px solid var(--border);background:var(--surface);color:var(--ink);min-height:36px}
.btn:hover{background:var(--hover);border-color:var(--ink)}
.btn:active{transform:translateY(1px)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.btn.primary:hover{background:var(--accent);filter:brightness(1.08);border-color:var(--ink)}
.btn.perigo:hover{border-color:var(--bad);color:var(--bad);background:var(--bad-soft)}
.btn:disabled,.btn[aria-disabled=true]{opacity:1;background:var(--bg);color:var(--muted);border:1.5px dashed var(--border);cursor:not-allowed;filter:none}
.abas button,.vel button,.giros button,.seg button,.sugestoes button{border:1.5px solid var(--border);background:var(--surface);color:var(--ink)}
.abas button{color:var(--muted)}
.abas button:hover,.vel button:hover,.giros button:hover,.seg button:hover,.sugestoes button:hover{background:var(--hover);border-color:var(--ink);color:var(--ink)}
.abas button[aria-pressed=true],.vel button[aria-pressed=true],.giros button[aria-pressed=true],.seg button[aria-pressed=true]{background:var(--ink);border-color:var(--ink);color:var(--surface)}
.giros button.bad{border-color:var(--bad);color:var(--bad)}
.giros button.bad[aria-pressed=true]{background:var(--bad);color:var(--surface);border-color:var(--bad)}
input,select,textarea{border-color:var(--border)}
form.ask input,.orc-form input,.ligar select,.paralelo select,.linha input,.campos input,form.busca input{border:1.5px solid var(--border);background:var(--surface);color:var(--ink)}
form.ask input:focus,.orc-form input:focus,.ligar select:focus,.paralelo select:focus,.linha input:focus,.campos input:focus,form.busca input:focus{border-color:var(--accent);outline:3px solid var(--accent);outline-offset:0}
::placeholder{color:var(--muted);opacity:1}
.chip{border:1px solid transparent}
.legenda,.legend{color:var(--ink);font-size:13px;gap:8px 18px}
.legenda span,.legend span{display:inline-flex;align-items:center;gap:6px}
.lg{display:inline-block;width:12px;height:12px;flex:none}
.lg.c{border-radius:50%}.lg.d{transform:rotate(45deg) scale(.8)}.lg.q{border-radius:3px}.lg.a{width:0;height:0;border-left:7px solid transparent;border-right:7px solid transparent;border-bottom:12px solid currentColor}
.lg.o{border-radius:50%;border:2px solid currentColor;background:transparent}.lg.t{border-radius:50%;border:2px dashed currentColor;background:transparent}
"""

# tom do chip -> glifo (o glifo é a pista que sobra quando a cor não ajuda: daltonismo, impressão, tela fraca)
GLIFOS = {"ok": "✓", "bad": "✕", "llm": "!", "jev": "◆"}
_REGRA_CHIP = re.compile(r"((?:\.chip(?:\.[\w-]+)+,?)+)\{[^}]*?background:var\(--(ok|bad|llm|jev)-soft\)")


def glifos(css: str) -> str:
    """Um ::before por tom, só para os chips que a própria página declara (sem inventar classe)."""
    por_tom: dict[str, list[str]] = {}
    for m in _REGRA_CHIP.finditer(css):
        por_tom.setdefault(m.group(2), []).extend(s.strip() for s in m.group(1).split(",") if s.strip())
    out = []
    for tom, seletores in por_tom.items():
        sel = ",".join(f"{s}::before" for s in dict.fromkeys(seletores))
        out.append(f'{sel}{{content:"{GLIFOS[tom]}";margin-right:4px;font-weight:800}}')
    return "\n".join(out)


def aplicar(html: str) -> str:
    """Troca os tokens da página pelos canônicos, (re)escreve o bloco de componentes no fim do <style> e o menu de cima
    logo depois do <body>. Idempotente."""
    corpo = re.sub(re.escape(INI) + r".*?" + re.escape(FIM) + r"\n?", "", html, flags=re.S)
    corpo = re.sub(re.escape(NAV_INI) + r".*?" + re.escape(NAV_FIM) + r"\n?", "", corpo, flags=re.S)
    corpo = re.sub(r"(<body[^>]*>\n?)", lambda m: m.group(1) + NAV, corpo, count=1)
    # tokens: o primeiro :root{...} e o primeiro @media dark :root{...} da página (os da paleta antiga)
    antigo = re.search(r":root\{[^}]*--bg:[^}]*\}\s*@media \(prefers-color-scheme:dark\)\{:root\{[^}]*\}\}", corpo, flags=re.S)
    if antigo is None:
        raise ValueError("página sem o bloco de tokens esperado")
    extras = re.findall(r"(--r-lg:[^;}]*;|--r-sm:[^;}]*;)", antigo.group(0))
    tokens = TOKENS if not extras else TOKENS.replace(":root{", ":root{" + "".join(extras), 1)
    corpo = corpo[:antigo.start()] + tokens + corpo[antigo.end():]
    css = corpo.split("<style>", 1)[1].split("</style>", 1)[0]
    bloco = f"{INI}\n{COMPONENTES.strip()}\n{glifos(css)}\n{FIM}\n"
    return corpo.replace("</style>", bloco + "</style>", 1)


PAGINAS = ("painel.html", "home.html", "fluxo.html", "rastros.html", "integracoes.html", "equipe.html", "aprovacoes.html")


def reescrever(pasta: Path | None = None) -> list[str]:
    pasta = pasta or Path(__file__).parent
    mudou = []
    for nome in PAGINAS:
        p = pasta / nome
        antes = p.read_text(encoding="utf-8")
        depois = aplicar(antes)
        if depois != antes:
            p.write_text(depois, encoding="utf-8")
            mudou.append(nome)
    return mudou


def _lum(h: str) -> float:
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def contraste(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def conferir() -> list[str]:
    """Pares que não cumprem o mínimo, nos dois modos (vazio = tudo certo)."""
    falhas = []
    for modo, t in (("claro", CLARO), ("escuro", ESCURO)):
        for pares, minimo in ((TEXTO, 4.5), (MARCA, 3.0)):
            for fg, bg in pares:
                c = contraste(t[fg], t[bg])
                if c < minimo:
                    falhas.append(f"{modo}: {fg} em {bg} = {c:.2f} (mínimo {minimo})")
    return falhas


if __name__ == "__main__":
    print("reescritas:", reescrever() or "nenhuma (já estavam no tema)")
    print("contrastes:", conferir() or "todos cumprem")
