"""Cérebros e neurônios: cada ponto do fluxo segue o mesmo contrato, e o loop cria portões novos a partir dos próprios erros.

Cérebros: o Cérebro do Loop (a estrutura do próprio loop), um cérebro por missão e o Cérebro Financeiro. Cada um
evolui sozinho, com os mesmos princípios.

Neurônio, o contrato de cada ponto do fluxo:
  estímulo → Jev primeiro (regra → Jev → LLM só se o Jev estiver em dúvida e valer o gasto) → ação
  → PORTÕES DE SAÍDA (todos precisam aprovar para a saída seguir adiante) → sinapse (`verificacoes`)
  → aprendizado (falha vira lição em `licoes`).

Portões:
- natos: escritos no código do neurônio (ex.: antes de abrir PR, o mesmo que o gate do merge exige);
- aprendidos (neurogênese): nascem de uma lição e ficam como DADO executável na tabela `portoes`, não como texto num
  prompt. Tipos:
  - comando: roda no worktree e precisa sair com 0. Allowlist: ruff e pytest;
  - proibido: regex que não pode aparecer nas linhas adicionadas;
  - obrigatorio: regex que precisa aparecer nas linhas adicionadas (ex.: o teste que prova a lição).
  O portão aprendido é o que impede o mesmo erro de estrutura de acontecer duas vezes: o neurônio passa a barrá-lo
  sozinho, antes de a saída seguir adiante.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ABRIR_PR = "developer:abrir_pr"
COMANDOS_PERMITIDOS = (("-m", "ruff"), ("-m", "pytest"))

CEREBROS = (  # prefixo do ponto → cérebro
    ("missao:", "missao"), ("financas:", "Cérebro Financeiro"), ("evolucao:", "Cérebro do Loop"),
    ("developer:", "Cérebro do Loop"), ("gate:", "Cérebro do Loop"), ("planejador:", "Cérebro do Loop"),
    ("execucao:", "Cérebro do Loop"), ("saude:", "Cérebro do Loop"), ("estudo:", "Cérebro do Loop"),
)


@dataclass
class Resultado:
    portao: str
    ok: bool
    motivo: str = ""
    aprendido: int | None = None     # id do portão aprendido (None = nato)


# ------------------------------------------------------------------ portões aprendidos (dados)

def criar_portao(store, neuronio: str, tipo: str, spec: dict, descricao: str, licao_id: int | None) -> int | None:
    """Neurogênese: um portão novo neste neurônio. Idempotente (mesmo neurônio+tipo+spec não duplica)."""
    if tipo not in ("comando", "proibido", "obrigatorio"):
        return None
    if tipo == "comando" and tuple(spec.get("argv", [])[:2]) not in COMANDOS_PERMITIDOS:
        return None
    sp = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    row = store.one("SELECT id FROM portoes WHERE neuronio=? AND tipo=? AND spec=?", (neuronio, tipo, sp))
    if row:
        return None
    agora = time.time()
    return store.x("INSERT INTO portoes(neuronio,tipo,spec,descricao,licao_id,ativo,avaliacoes,bloqueios,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,1,0,0,?,?)", (neuronio, tipo, sp, descricao[:300], licao_id, agora, agora))


def neurogenese(store, licao: dict) -> list[int]:
    """Deriva portões executáveis de uma lição. Só o que dá para checar mecanicamente vira portão."""
    sig, novos = licao["assinatura"], []
    m = re.search(r":lint:([A-Z0-9,]+)$", sig)
    if m:
        from .self_dev import LINT_CMD     # lição #72: o código que o CI ignora não vira portão
        ignorados = LINT_CMD[LINT_CMD.index("--ignore") + 1].split(",")
        codigos = ",".join(c for c in m.group(1).split(",") if c not in ignorados)
        if codigos:
            novos.append(criar_portao(store, ABRIR_PR, "comando",
                                      {"argv": ["-m", "ruff", "check", "circulo", "tests", "--select", codigos]},
                                      f"lint {codigos} (lição #{licao['id']})", licao["id"]))
    m = re.search(r":teste:(tests/[\w/]+\.py::\w+)$", sig)
    if m:
        novos.append(criar_portao(store, ABRIR_PR, "comando", {"argv": ["-m", "pytest", "-q", m.group(1)]},
                                  f"teste {m.group(1)} (lição #{licao['id']})", licao["id"]))
    if licao.get("item_id"):
        # a correção de uma lição de estrutura precisa trazer o teste que prova a lição: é ele que impede a volta
        novos.append(criar_portao(store, ABRIR_PR, "obrigatorio",
                                  {"regex": rf"(?i)li[cç][aã]o[ _#-]*{licao['id']}\b", "em": "teste", "item": licao["item_id"]},
                                  f"teste de regressão marcado com a lição #{licao['id']}", licao["id"]))
    return [n for n in novos if n]


def portoes(store, neuronio: str, item_id: int | None = None) -> list[dict]:
    out = []
    for r in store.q("SELECT * FROM portoes WHERE neuronio=? AND ativo=1 ORDER BY id", (neuronio,)):
        d = {**dict(r), "spec": json.loads(r["spec"])}
        if d["spec"].get("item") is not None and d["spec"]["item"] != item_id:
            continue            # portão de um item específico
        out.append(d)
    return out


def avaliar_aprendidos(store, neuronio: str, wt: Path, adicionadas: dict[str, list[str]], env: dict,
                       item_id: int | None = None) -> list[Resultado]:
    res = []
    for p in portoes(store, neuronio, item_id):
        spec, ok, motivo = p["spec"], True, ""
        if p["tipo"] == "comando":
            argv = list(spec["argv"])
            if argv[1] == "ruff":
                from .self_dev import LINT_CMD, garantir_ruff
                if not garantir_ruff():
                    res.append(Resultado(f"aprendido#{p['id']}: {p['descricao']}", True, "ruff indisponível aqui; o CI cobre", p["id"]))
                    continue
                alvos = [a for a in ("circulo", "tests") if (Path(wt) / a).exists()] or ["."]
                argv = [x for x in argv if x not in ("circulo", "tests")]
                argv[3:3] = alvos               # -m ruff check <alvos> --select ...
                argv += LINT_CMD[LINT_CMD.index("--ignore"):][:2]   # lição #78: nunca mais estrito que o CI
            # lições #26 e #27: o id (arquivo, classe, função) é conferido por ast antes de chamar o pytest (o exit 4 é
            # qualquer erro de uso, não só este); a recusa leva os test_* reais para o reparo não repetir o id inventado.
            # Lição #26: o que passa no ast ainda passa pela coleta do pytest antes de rodar
            from .developer import (ALVO_INEXISTENTE, CAUSA_ALVO, REPARO, alvo_coletado, alvo_pytest_existe,
                                    listar_testes)
            sumido = next((a for a in argv if "pytest" in argv and a.startswith("tests/") and not (
                alvo_pytest_existe(wt, a) and ("::" not in a or alvo_coletado(wt, a, env)))), None)
            cp = None if sumido else subprocess.run([sys.executable, *argv], cwd=wt, capture_output=True, text=True,
                                                    timeout=900, env=env)
            ok, motivo = (True, "") if cp is None else (cp.returncode == 0, (cp.stdout + cp.stderr)[-800:])
            if sumido or ("pytest" in argv and cp.returncode == 4 and "not found" in motivo):     # o teste citado já não existe: portão obsoleto
                store.x("UPDATE portoes SET ativo=0, updated_at=? WHERE id=?", (time.time(), p["id"]))
                if p.get("licao_id"):
                    store.x("UPDATE licoes SET status='obsoleta', prevencao=?, updated_at=? WHERE id=? AND status IN ('aberta','evidenciada','reincidente')",
                            (f"Obsoleta: o alvo do portão ({p['descricao']}) não existe mais", time.time(), p["licao_id"]))
                recusa = "" if not sumido else (
                    f"recusa alvo_inexistente: {sumido}, pytest não rodou; test_* reais do arquivo: "
                    f"{', '.join(listar_testes(wt, sumido.split('::')[0])) or 'nenhum (arquivo ausente)'}; ")
                if sumido:
                    from .licoes import Licoes
                    Licoes(store, repo=wt).verificar(REPARO, False, sujeito=p["descricao"], motivo=recusa,
                                                     assinatura=ALVO_INEXISTENTE, causa=CAUSA_ALVO)
                res.append(Resultado(f"aprendido#{p['id']}: {p['descricao']}", True, f"{recusa}alvo do pytest não existe mais: portão desativado (lição obsoleta)", p["id"]))
                continue
        else:
            from .merge_gate import tem_teste
            em = spec.get("em", "")
            linhas = [x for f, ls in adicionadas.items() if (tem_teste([f]) if em == "teste" else f.startswith(em)) for x in ls]
            achou = any(re.search(spec["regex"], x) for x in linhas)
            ok = (not achou) if p["tipo"] == "proibido" else achou
            motivo = "" if ok else (f"padrão proibido nas linhas novas: {spec['regex']}" if p["tipo"] == "proibido"
                                    else f"falta nas linhas novas de {'testes' if em == 'teste' else em or 'qualquer arquivo'}: {spec['regex']}")
        store.x("UPDATE portoes SET avaliacoes=avaliacoes+1, bloqueios=bloqueios+?, updated_at=? WHERE id=?",
                (0 if ok else 1, time.time(), p["id"]))
        res.append(Resultado(f"aprendido#{p['id']}: {p['descricao']}", ok, motivo, p["id"]))
    if neuronio == ABRIR_PR:
        from .criterio_aceite import conferir
        criterio = conferir(store, item_id, wt, adicionadas, env)        # o critério de aceite congelado do item
        res += [criterio] if criterio else []
    return res


# ------------------------------------------------------------------ o neurônio "abrir PR"

def diff_do_worktree(wt: Path, base: str, git) -> tuple[list[dict], dict[str, list[str]]]:
    """Arquivos mudados (numstat) e linhas adicionadas por arquivo, com tudo já no índice."""
    git(["add", "-A"], wt)
    arquivos = []
    for linha in git(["diff", "--cached", "--numstat", base], wt).splitlines():
        a, d, nome = (linha.split("\t") + ["", "", ""])[:3]
        arquivos.append({"filename": nome, "additions": int(a) if a.isdigit() else 0, "deletions": int(d) if d.isdigit() else 0})
    adicionadas: dict[str, list[str]] = {}
    atual = None
    for linha in git(["diff", "--cached", "-U0", base], wt).splitlines():
        if linha.startswith("+++ "):
            atual = linha[6:] if linha.startswith("+++ b/") else None
        elif linha.startswith("+") and atual:
            adicionadas.setdefault(atual, []).append(linha[1:])
    return arquivos, adicionadas


def portoes_natos_pr(arquivos: list[dict], adicionadas: dict[str, list[str]] | None = None) -> list[Resultado]:
    """O mesmo que o gate do merge exige, checado ANTES de o PR existir."""
    from .merge_gate import MAX_LINES, tem_teste, touches_constitution
    nomes = [a["filename"] for a in arquivos]
    marcas = sorted({f for f, ls in (adicionadas or {}).items() if any(re.match(r"^(<{7}|>{7})( |$)|^={7}$", x) for x in ls)})
    const = touches_constitution(nomes)
    linhas = sum(a["additions"] + a["deletions"] for a in arquivos)
    return [
        Resultado("constituição intacta", not const, f"altera a constituição: {', '.join(const)}" if const else ""),
        Resultado("tamanho", linhas <= MAX_LINES, f"{linhas} linhas > {MAX_LINES}: quebre em partes" if linhas > MAX_LINES else ""),
        Resultado("teste novo", tem_teste(nomes), "" if tem_teste(nomes) else "nenhum teste novo em tests/"),
        Resultado("sem marcador de conflito", not marcas, f"marcadores de conflito em: {', '.join(marcas)}" if marcas else ""),
    ]


def cita_constituicao(texto: str) -> list[str]:
    """Caminhos da constituição citados no texto, lidos da mesma lista do gate. O nome solto (`self_dev.py`) é
    ambíguo e conta como suspeito."""
    from .merge_gate import CONSTITUICAO, touches_constitution
    nomes = {p.rsplit("/", 1)[-1] for p in CONSTITUICAO if not p.endswith("/")}
    citados = []
    for c in re.findall(r"[\w./-]+", texto or ""):
        c = c.rstrip("./")
        if (touches_constitution([c]) or c == ".github" or c in nomes) and c not in citados:
            citados.append(c)
    return citados


def causa_da_falha(falhas: list[Resultado]) -> str:
    """A causa normalizada de uma falha de abrir PR: constituição | conflito_main | ci | outra (nessa prioridade)."""
    nomes = {f.portao for f in falhas}
    if "constituição intacta" in nomes:
        return "constituição"
    if "sem marcador de conflito" in nomes:
        return "conflito_main"
    if any(f.aprendido or f.portao.startswith("lint e testes") for f in falhas):
        return "ci"
    return "outra"


def registrar(ctx, neuronio: str, resultados: list[Resultado], sujeito: str = "") -> list[Resultado]:
    """Sinapse: cada portão avaliado fica no monitoramento. Portão aprendido que barra é prevenção funcionando."""
    from .licoes import registrar as monitorar
    for r in resultados:
        from .decision import norm
        monitorar(ctx, f"{neuronio}:{'aprendido' if r.aprendido else re.sub(r'[^a-z]+', '_', norm(r.portao)).strip('_')}",
                  r.ok, sujeito=sujeito, motivo=r.motivo, licao=False)
    return [r for r in resultados if not r.ok]


# ------------------------------------------------------------------ painel: cérebros

def cerebro_de(ponto: str, sujeito: str = "") -> str:
    for prefixo, nome in CEREBROS:
        if ponto.startswith(prefixo):
            return f"Cérebro da missão {sujeito}".strip() if nome == "missao" else nome
    return "Cérebro do Loop"


def cerebros(store, horas: int = 24) -> list[dict]:
    desde = time.time() - horas * 3600
    grupos: dict[str, dict] = {}
    for r in store.q("SELECT ponto, sujeito, COUNT(*) n, SUM(ok=0) falhas FROM verificacoes WHERE created_at>=? "
                     "GROUP BY ponto, CASE WHEN ponto LIKE 'missao:%' THEN sujeito ELSE '' END", (desde,)):
        nome = cerebro_de(r["ponto"], r["sujeito"] or "")
        g = grupos.setdefault(nome, {"cerebro": nome, "neuronios": [], "disparos": 0, "falhas": 0})
        g["neuronios"].append({"neuronio": r["ponto"], "disparos": r["n"], "falhas": r["falhas"] or 0})
        g["disparos"] += r["n"]
        g["falhas"] += r["falhas"] or 0
    aprendidos = store.q("SELECT neuronio, COUNT(*) n, SUM(bloqueios) b FROM portoes WHERE ativo=1 GROUP BY neuronio")
    for a in aprendidos:
        g = grupos.setdefault(cerebro_de(a["neuronio"]), {"cerebro": cerebro_de(a["neuronio"]), "neuronios": [], "disparos": 0, "falhas": 0})
        g.setdefault("portoes_aprendidos", []).append({"neuronio": a["neuronio"], "portoes": a["n"], "bloqueios": a["b"] or 0})
    return sorted(grupos.values(), key=lambda g: (g["cerebro"] != "Cérebro do Loop", g["cerebro"]))
