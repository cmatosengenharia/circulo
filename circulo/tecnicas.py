"""Técnicas absorvidas das skills externas (1.75), como PORTÕES MEDIDOS — nunca só texto no prompt.

Cássio (1/11): "não copie cegamente: extraia as técnicas (plano e teste antes do código, mudanças cirúrgicas,
simplicidade, respostas diretas, revisão cruzada) e incorpore no ecossistema do loop e do Jev onde fizer sentido";
"crie validação automática que prove que cada técnica está ativa". Fontes e o que ficou de fora: docs/adr/0010-0013.

Cada técnica tem uma medida determinística sobre a evidência que o Developer/Fabricante deixa (os passos do Claude
Code, o diff, a resposta final) e grava `tecnica:<nome>` em `verificacoes` (ok/falha, motivo) a cada entrega. Isso é
o que prova que a técnica está ATIVA: `relatorio(store)` (e `circulo tecnicas`) mostra as últimas medições por
técnica; `tests/test_tecnicas.py` prova cada medida. As que barram (cirúrgica, simplicidade) entram no neurônio
"abrir PR" como portões natos: barrou, o Developer corrige no mesmo worktree. As demais são evidência (a ordem dos
passos já aconteceu; o que se faz é medir e deixar a taxa visível para o Médico e para as lições).

| técnica          | fonte                                   | medida                                                               | barra |
| plano_antes      | superpowers writing-plans, karpathy §4  | o 1º passo do agente é planejar (TodoWrite/plano) antes de editar     | não   |
| teste_antes      | superpowers TDD, karpathy §4            | a 1ª edição é em tests/ (antes de qualquer edição em código)          | não   |
| cirurgica        | karpathy §3                             | arquivos de código fora do escopo do item ≤ MAX_FORA_DO_ESCOPO        | sim   |
| simplicidade     | karpathy §2                             | sem dependência nova não pedida; sem def/class novo que ninguém usa   | sim   |
| resposta_direta  | i-have-adhd (regras 1, 3, 10)           | resposta final ≤ MAX_LINHAS_RESPOSTA linhas, sem preâmbulo            | não   |
| revisao_cruzada  | superpowers requesting-code-review, octopus | o Validador usa modelo/olhos diferentes do Developer              | não*  |
(* a revisão cruzada reprova por problema concreto, em validador.py; aqui mede-se que ela aconteceu com olhos distintos.)
"""
from __future__ import annotations

import re
from pathlib import Path

PREFIXO = "tecnica:"
NOMES = ("plano_antes", "teste_antes", "cirurgica", "simplicidade", "resposta_direta", "revisao_cruzada")
MAX_FORA_DO_ESCOPO = 2          # arquivos de código mudados que o item não cita (além dos de teste/docs)
MAX_LINHAS_RESPOSTA = 12
JANELA = 30                     # últimas medições por técnica no relatório
PREAMBULO = re.compile(r"(?i)^\s*(great|ótima|otima|boa pergunta|let me|vou (começar|analisar|dar uma olhada)|sure|claro[,!]|perfeito[,!]|certainly|i'll|"
                       r"looking at|primeiro,? (vou|deixa)|antes de (mais nada|tudo))")
PASSO_EDICAO = re.compile(r"^Claude Code: (escrevendo|editando) (.+)$")
PASSO_PLANO = re.compile(r"^Claude Code: (TodoWrite|TaskCreate|EnterPlanMode|ExitPlanMode)$|plano", re.I)
SEMPRE_NO_ESCOPO = re.compile(r"^(tests?/|docs/|CHANGELOG|README|pyproject\.toml$|\.claude/|.*\.md$|.*\.html$|.*\.json$|.*\.toml$|.*\.yml$|.*\.yaml$|.*\.txt$)")
CODIGO = re.compile(r"\.(py|cs|ts|tsx|js|go|rs|java|kt|rb|php)$")
DEF_NOVO = re.compile(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)")
DEPENDENCIA = re.compile(r'^\s*(?:"([A-Za-z0-9_.\-]+)[<>=!~ ;\[\]"]|<PackageReference\s+Include="([^"]+)")')

PROMPT = """Técnicas do time (portões medidos a cada entrega — `circulo tecnicas` mostra a taxa; fontes em docs/adr/0010-0013):
- PLANO ANTES DO CÓDIGO: antes de qualquer edição, registre o plano em passos verificáveis (TodoWrite, ou a primeira
  mensagem: "1. <passo> → verificar: <comando/resultado>"). Afirme as suposições; se houver duas leituras do pedido,
  escolha a mais simples e diga qual.
- TESTE ANTES DO CÓDIGO: a primeira edição é o teste (tests/) que falha; só depois o código que o faz passar. Se não
  viu o teste falhar, não sabe se ele testa a coisa certa.
- MUDANÇA CIRÚRGICA: toque só o que o item pede. Nada de "melhorar" código vizinho, formatação ou comentários; estilo
  igual ao existente mesmo que fizesse diferente; remova apenas os órfãos que a SUA mudança criou. Toda linha mudada
  tem que rastrear até o pedido (o portão conta arquivos de código fora do escopo).
- SIMPLICIDADE: o mínimo que resolve. Nenhuma dependência nova sem o item pedir; nenhuma abstração, flag ou
  configurabilidade para uso único; nada especulativo. Se 200 linhas podiam ser 50, reescreva (o portão barra
  função/classe nova que ninguém chama).
- RESPOSTA DIRETA: a mensagem final tem no máximo 12 linhas, sem preâmbulo nem despedida: o que mudou (arquivos), como
  foi verificado (comando e resultado) e UM próximo passo se houver algo em aberto. Erro é dito como causa e correção.
"""


# ------------------------------------------------------------------ medidas (puras)

def _arquivo_do_passo(p: str) -> str | None:
    m = PASSO_EDICAO.match(p or "")
    return m.group(2).strip() if m else None


def plano_antes(passos: list[str]) -> tuple[bool, str]:
    """O agente planejou (TodoWrite/plano) antes da primeira edição. Sem edição alguma não há o que medir: ok."""
    for p in passos or []:
        if PASSO_PLANO.search(p or ""):
            return True, ""
        if _arquivo_do_passo(p):
            return False, f"editou {_arquivo_do_passo(p)} sem plano registrado antes (TodoWrite ou mensagem numerada)"
    return True, ""


def teste_antes(passos: list[str]) -> tuple[bool, str]:
    """A primeira edição em arquivo de código é precedida por uma edição em tests/. Só docs/config: ok."""
    for p in passos or []:
        arq = _arquivo_do_passo(p)
        if not arq:
            continue
        if _e_teste(arq):
            return True, ""
        if CODIGO.search(arq):
            return False, f"primeira edição foi em código ({arq}), não no teste"
    return True, ""


def _e_teste(arq: str) -> bool:
    nome = arq.rsplit("/", 1)[-1]
    return arq.startswith("tests/") or "/tests/" in arq or nome.startswith("test_") or nome.endswith(("_test.py", "Tests.cs", "Test.cs", ".test.ts", ".spec.ts"))


def escopo_do_item(item: dict) -> set[str]:
    """Os arquivos que o item cita (circulo/x.py, src/A/B.cs, caminhos com barra) e os módulos por nome."""
    texto = f"{item.get('titulo', '')}\n{item.get('detalhe', '') or ''}"
    return {m.strip("`'\"") for m in re.findall(r"[\w./-]+\.(?:py|cs|ts|tsx|js|go|rs|java|kt|rb|php|html|json|toml|yml|yaml|md)", texto)}


def cirurgica(item: dict, arquivos: list[str]) -> tuple[bool, str]:
    """Arquivos de CÓDIGO mudados que o item não cita, nem são teste/docs/config, ≤ MAX_FORA_DO_ESCOPO.
    Item sem arquivo citado não tem escopo mensurável: só o teto absoluto (2 × o máximo) vale."""
    escopo = escopo_do_item(item)
    nomes_escopo = {Path(e).name for e in escopo} | {Path(e).stem for e in escopo}
    fora = [a for a in arquivos if CODIGO.search(a) and not _e_teste(a) and not SEMPRE_NO_ESCOPO.match(a)
            and a not in escopo and Path(a).name not in nomes_escopo and Path(a).stem not in nomes_escopo
            and not any(e.endswith(a) or a.endswith(e) for e in escopo)]
    teto = MAX_FORA_DO_ESCOPO if escopo else 2 * MAX_FORA_DO_ESCOPO
    if len(fora) > teto:
        return False, f"{len(fora)} arquivos de código fora do escopo do item (> {teto}): {', '.join(fora[:6])} — reverta o que o pedido não exige"
    return True, ""


def _definicoes_novas(adicionadas: dict[str, list[str]]) -> list[tuple[str, str]]:
    out = []
    for arq, linhas in (adicionadas or {}).items():
        if not arq.endswith(".py") or _e_teste(arq):
            continue
        for linha in linhas:
            m = DEF_NOVO.match(linha)
            if m and not m.group(1).startswith("_") and m.group(1) not in ("main",):
                out.append((arq, m.group(1)))
    return out


def _usado(raiz: Path, arq: str, nome: str) -> bool:
    padrao = re.compile(rf"(?<![\w.]){re.escape(nome)}\b|\.{re.escape(nome)}\b|__all__.*\b{re.escape(nome)}\b")
    for p in Path(raiz).rglob("*"):
        if not p.is_file() or p.suffix not in (".py", ".html", ".md", ".toml", ".yml", ".yaml") or ".git" in p.parts:
            continue
        try:
            texto = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for linha in texto.splitlines():
            if DEF_NOVO.match(linha) and DEF_NOVO.match(linha).group(1) == nome:
                continue                                    # a própria definição não conta
            if padrao.search(linha):
                return True
    return False


def dependencias_novas(adicionadas: dict[str, list[str]]) -> list[str]:
    out = []
    for arq, linhas in (adicionadas or {}).items():
        if not (arq.endswith(("pyproject.toml", "requirements.txt", ".csproj", "package.json", "Directory.Packages.props"))):
            continue
        for linha in linhas:
            m = DEPENDENCIA.match(linha)
            if m:
                out.append(m.group(1) or m.group(2))
    return out


def simplicidade(item: dict, adicionadas: dict[str, list[str]], raiz: Path | None) -> tuple[bool, str]:
    """Sem dependência nova que o item não cite; sem def/class público novo (em .py fora de tests/) que ninguém usa."""
    texto = f"{item.get('titulo', '')} {item.get('detalhe', '') or ''}".lower()
    deps = [d for d in dependencias_novas(adicionadas) if d.lower().split("[")[0] not in texto]
    if deps:
        return False, f"dependência nova que o item não pede: {', '.join(deps)} — resolva sem ela ou justifique no item"
    if raiz is not None:
        mortos = [f"{nome} ({arq})" for arq, nome in _definicoes_novas(adicionadas) if not _usado(Path(raiz), arq, nome)]
        if mortos:
            return False, f"definição nova que nada usa (abstração especulativa): {', '.join(mortos[:5])} — remova ou use"
    return True, ""


def resposta_direta(resposta: str) -> tuple[bool, str]:
    """Resposta final curta (≤ MAX_LINHAS_RESPOSTA linhas não vazias) e sem preâmbulo. Vazia: não há o que medir (ok)."""
    linhas = [x for x in (resposta or "").strip().splitlines() if x.strip()]
    if not linhas:
        return True, ""
    if PREAMBULO.search(linhas[0]):
        return False, f"começa com preâmbulo: {linhas[0][:80]!r}"
    if len(linhas) > MAX_LINHAS_RESPOSTA:
        return False, f"{len(linhas)} linhas (> {MAX_LINHAS_RESPOSTA}): diga o que mudou, como verificou e o próximo passo"
    return True, ""


def revisao_cruzada(modelo_developer: str, modelo_validador: str, fonte: str) -> tuple[bool, str]:
    """Olhos distintos: o Validador respondeu (fonte llm/externo) com modelo diferente do Developer."""
    if fonte not in ("llm", "externo"):
        return False, f"o Validador não revisou (fonte {fonte})"
    a, b = (modelo_developer or "").lower(), (modelo_validador or "").lower()
    if a and b and a == b:
        return False, f"mesmo modelo nos dois papéis ({a}); a revisão não é cruzada"
    return True, ""


# ------------------------------------------------------------------ portões do neurônio "abrir PR" e evidência

def medir(ctx, item: dict, passos: list[str], resposta: str, arquivos: list[str], adicionadas: dict[str, list[str]],
          raiz: Path | None) -> list:
    """Mede todas as técnicas sobre a entrega, grava `tecnica:<nome>` e devolve os Resultados dos portões que BARRAM
    (cirurgica, simplicidade) para o neurônio "abrir PR" registrar. As outras ficam só como evidência."""
    from .neuronios import Resultado
    medidas = {"plano_antes": plano_antes(passos), "teste_antes": teste_antes(passos), "cirurgica": cirurgica(item, arquivos),
               "simplicidade": simplicidade(item, adicionadas, raiz), "resposta_direta": resposta_direta(resposta)}
    sujeito = f"roteiro #{item.get('id')}" if item.get("id") else str(item.get("titulo", ""))[:120]
    for nome, (ok, motivo) in medidas.items():
        registrar(ctx, nome, ok, sujeito, motivo)
    return [Resultado(f"técnica {n}", *medidas[n]) for n in ("cirurgica", "simplicidade")]


def registrar(ctx, nome: str, ok: bool, sujeito: str = "", motivo: str = "") -> None:
    from .licoes import registrar as monitorar
    monitorar(ctx, f"{PREFIXO}{nome}", ok, sujeito=sujeito, motivo=motivo, licao=False)


def relatorio(store, janela: int = JANELA) -> list[dict]:
    """Por técnica: medições na janela, taxa de ok, última medição e último motivo de falha. Técnica sem medição = inativa."""
    out = []
    for nome in NOMES:
        rows = store.q("SELECT ok, motivo, created_at FROM verificacoes WHERE ponto=? ORDER BY id DESC LIMIT ?", (f"{PREFIXO}{nome}", janela))
        oks = sum(int(r["ok"]) for r in rows)
        falha = next((r["motivo"] for r in rows if not r["ok"]), "")
        out.append({"tecnica": nome, "medicoes": len(rows), "ok": oks, "taxa": round(oks / len(rows), 2) if rows else None,
                    "ativa": bool(rows), "ultima_em": rows[0]["created_at"] if rows else None, "ultima_falha": (falha or "")[:200]})
    return out


def texto_relatorio(store) -> str:
    linhas = ["Técnicas absorvidas (medidas em cada entrega; fonte: verificacoes tecnica:*)"]
    for r in relatorio(store):
        estado = "sem medição ainda" if not r["ativa"] else f"{r['ok']}/{r['medicoes']} ok ({r['taxa']:.0%})"
        linhas.append(f"- {r['tecnica']:<16} {estado}" + (f" — última falha: {r['ultima_falha']}" if r["ultima_falha"] else ""))
    return "\n".join(linhas)


__all__ = ["NOMES", "PROMPT", "PREFIXO", "plano_antes", "teste_antes", "cirurgica", "simplicidade", "resposta_direta",
           "revisao_cruzada", "medir", "registrar", "relatorio", "texto_relatorio", "escopo_do_item", "dependencias_novas"]
