"""Escalador: quem está sobrecarregado na equipe, e quem pode ganhar mais um trabalhador em paralelo.

Mede, por agente e na última hora: fila (quanto trabalho espera por ele), ocupação (quanto tempo ele passou ocupado,
pelas intenções registradas antes e depois de cada tarefa), espera (há quanto tempo o item mais antigo espera) e
vazão (tarefas concluídas). O gargalo é o agente com a maior carga: ocupação alta E fila que não baixa.

Escalar = mais trabalhadores do mesmo agente no mesmo giro. Só para quem não conflita na esteira de entrega:
- Arquiteto (`estudar_pedido`): cada estudo é um item, independente → N estudos ao mesmo tempo.
- Desenvolvedor (`corrigir_codigo`): até 2 itens, cada um no seu worktree e branch; o git do repositório principal
  fica sob trava; o Revisor já barra PRs que tocam os mesmos arquivos; o gate serializa os merges. Worktree só desloca o
  conflito para o merge, então a partição vem antes, aqui: com 3 ou mais itens na fila, sobe para 2 só se o par que o
  Developer pegaria (`SelfDeveloper.picks`) tem pegadas de arquivos disjuntas e fora dos pontos de convergência
  (registros, __init__, fila, lições); par sobreposto desce para 1 na hora, e os dois itens saem um de cada vez.
Nunca: QA/gate (merge serial na main), DevOps/corpo, Gerente de produto (fila com teto), PO, Redator.

A decisão de escalar passa pelo Jev (noul) com o estado medido; sobe um trabalhador por vez até MAX_PARALELO, e desce
quando a fila esvazia. Roda na thread do SRE, uma vez por minuto; o painel recebe pela mesma stream de eventos.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .nomes import nome
from .state import Store

KV = "capacidade"
ESCALAVEIS = {"estudar_pedido": "Arquiteto: estudos são independentes por item",
              "corrigir_codigo": "Desenvolvedor: 2 itens com pegadas de arquivos disjuntas, worktrees separados, git sob trava, Revisor barra arquivos em comum"}
NAO_ESCALAVEIS = {"revisar_prs": "merge serial na main", "atualizar_corpo": "uma versão em prova por vez", "planejar_roteiro": "fila com teto",
                  "indagar": "uma passagem basta", "documentar": "um PR de docs por vez"}
MAX_PARALELO = 3
JANELA = 3600
OCUPACAO_ALTA = 0.6        # fração da hora ocupado
FILA_ALTA = 3              # itens esperando
SOBE_A_CADA = 900          # 15 min entre escaladas do mesmo agente
MIN_ANTES_DE_DESCER = 600
MAX_DEV = 2                # Developers em paralelo
CONVERGENCIA = frozenset({"circulo/__init__.py", "circulo/cli.py", "circulo/nomes.py", "circulo/state.py",   # registros
                          "circulo/roadmap.py", "circulo/licoes.py", "CHANGELOG.md", "pyproject.toml"})     # fila e lições
_ARQUIVO = re.compile(r"\b((?:circulo|fabrica|tests|docs)/[\w/]+\.\w+|CHANGELOG\.md|pyproject\.toml)\b")


def pegada(item: dict) -> frozenset[str]:
    """Os arquivos que o item deve tocar: o módulo que o Planejador gravou, os caminhos citados no texto e o teste de cada
    módulo do pacote (é ali que o Developer acrescenta o teste novo)."""
    arqs = set(_ARQUIVO.findall(f"{item.get('modulo') or ''} {item.get('titulo') or ''} {item.get('detalhe') or ''}"))
    if item.get("modulo") and not _ARQUIVO.fullmatch(item["modulo"]):
        arqs.add(item["modulo"])
    arqs |= {f"tests/test_{m.group(1)}.py" for a in arqs if (m := re.fullmatch(r"(?:circulo|fabrica)/(\w+)\.py", a))}
    return frozenset(arqs)


def colisao(a: frozenset[str], b: frozenset[str]) -> list[str]:
    """Por que dois itens não podem ir em paralelo ([] = podem): arquivo em comum, ponto de convergência ou pegada vazia."""
    if not a or not b:
        return ["(pegada desconhecida)"]
    return sorted((a & b) | ((a | b) & CONVERGENCIA))


class _Fila:
    """O que `SelfDeveloper.picks` lê (store e PRs abertos): o Escalador simula o par que o Developer pegaria."""
    def __init__(self, store: Store):
        self.s = store

    def abertos(self) -> list[dict]:
        from .self_dev import SelfDeveloper
        return SelfDeveloper.abertos(self)


def par_do_developer(store: Store) -> tuple[list[dict], list[str]]:
    """(os itens que o Developer pegaria com 2 trabalhadores, a colisão entre eles); colisão [] = par disjunto."""
    from .self_dev import SelfDeveloper
    par = SelfDeveloper.picks(_Fila(store), MAX_DEV)
    if len(par) < MAX_DEV:
        return par, ["(fila sem par)"]
    return par, colisao(pegada(par[0]), pegada(par[1]))


def _n(store: Store, sql: str, args=()) -> int:
    r = store.one(sql, args)
    return int((r["n"] if r else 0) or 0)


def _ocupacao(store: Store, agora: float) -> dict[str, dict]:
    """Segundos ocupados e tarefas concluídas por ação na última hora, casando intenção → resultado."""
    rows = store.q("SELECT seq, tipo, ref, acao, em FROM intencoes WHERE em>=? ORDER BY seq", (agora - JANELA - 1800,))
    ini: dict[int, tuple[str, float]] = {}
    out: dict[str, dict] = {}
    for r in rows:
        if r["tipo"] == "intencao":
            ini[r["seq"]] = (r["acao"], float(r["em"]))
        elif r["tipo"] == "resultado" and r["ref"] in ini:
            acao, t0 = ini.pop(r["ref"])
            if float(r["em"]) >= agora - JANELA:
                o = out.setdefault(acao, {"ocupado_s": 0.0, "tarefas": 0, "max_s": 0.0})
                d = max(0.0, float(r["em"]) - t0)
                o["ocupado_s"] += d
                o["tarefas"] += 1
                o["max_s"] = max(o["max_s"], d)
    for _seq, (acao, t0) in ini.items():                      # ainda rodando: conta até agora
        if agora - t0 < 3 * 3600:
            o = out.setdefault(acao, {"ocupado_s": 0.0, "tarefas": 0, "max_s": 0.0})
            o["ocupado_s"] += agora - t0
            o["em_curso"] = True
    return out


def _fila(store: Store, agora: float) -> dict[str, dict]:
    """Quanto trabalho espera por cada agente, e há quanto tempo o mais antigo espera."""
    def mais_antigo(sql, args=()) -> float | None:
        r = store.one(sql, args)
        return float(r["t"]) if r and r["t"] else None
    pend_est = "SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND origem IN ('pedido_cassio','loop') AND COALESCE(desativado,0)=0 AND estudo IS NULL AND evidencia NOT LIKE '%depende de você%'"
    pend_dev = "SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND (origem='erro' OR estudo IS NOT NULL) AND evidencia NOT LIKE '%depende de você%'"
    return {
        "estudar_pedido": {"fila": _n(store, pend_est), "espera_s": (agora - (mais_antigo(pend_est.replace("COUNT(*) n", "MIN(updated_at) t")) or agora))},
        "corrigir_codigo": {"fila": _n(store, pend_dev), "espera_s": (agora - (mais_antigo(pend_dev.replace("COUNT(*) n", "MIN(updated_at) t")) or agora))},
        "revisar_prs": {"fila": _n(store, "SELECT COUNT(*) n FROM prs WHERE status='aberto'"), "espera_s": 0},
        "planejar_roteiro": {"fila": _n(store, "SELECT COUNT(*) n FROM perguntas WHERE status='valida'"), "espera_s": 0},
        "indagar": {"fila": 0, "espera_s": 0},
    }


def medir(store: Store, agora: float | None = None) -> list[dict]:
    """A carga de cada agente da esteira, do mais carregado ao menos."""
    agora = agora or time.time()
    oc, fi = _ocupacao(store, agora), _fila(store, agora)
    cap = store.get(KV) or {}
    out = []
    for ag in set(oc) | set(fi):
        o, f = oc.get(ag, {}), fi.get(ag, {"fila": 0, "espera_s": 0})
        ocup = min(1.0, float(o.get("ocupado_s", 0)) / JANELA)
        fila = int(f["fila"])
        carga = round(0.6 * ocup + 0.4 * min(1.0, fila / 10.0), 3)
        out.append({"agente": ag, "nome": nome(ag), "ocupacao": round(ocup, 3), "ocupado_s": int(o.get("ocupado_s", 0)), "tarefas_1h": int(o.get("tarefas", 0)),
                    "tarefa_max_s": int(o.get("max_s", 0)), "fila": fila, "espera_s": int(f["espera_s"]), "carga": carga,
                    "sobrecarregado": ocup >= OCUPACAO_ALTA and fila >= FILA_ALTA,
                    "escalavel": ag in ESCALAVEIS, "porque": ESCALAVEIS.get(ag) or NAO_ESCALAVEIS.get(ag, ""),
                    "trabalhadores": int((cap.get(ag) or {}).get("trabalhadores", 1))})
    out.sort(key=lambda x: -x["carga"])
    return out


def gargalo(medidas: list[dict]) -> dict | None:
    return next((m for m in medidas if m["sobrecarregado"]), None) or (medidas[0] if medidas and medidas[0]["carga"] >= 0.3 else None)


def trabalhadores(store: Store, agente: str) -> int:
    return int(((store.get(KV) or {}).get(agente) or {}).get("trabalhadores", 1))


def _definir(store: Store, agente: str, n: int, motivo: str, agora: float) -> None:
    cap = dict(store.get(KV) or {})
    antes = int((cap.get(agente) or {}).get("trabalhadores", 1))
    cap[agente] = {"trabalhadores": n, "desde": agora, "motivo": motivo, "antes": antes}
    store.set(KV, cap)
    hist = list(store.get(KV + "_hist") or [])[-29:]
    hist.append({"em": agora, "agente": agente, "de": antes, "para": n, "motivo": motivo})
    store.set(KV + "_hist", hist)


def decidir(store: Store, dl, medidas: list[dict], agora: float | None = None) -> dict:
    """Sobe um trabalhador do gargalo escalável (Jev decide) ou desce quando a fila esvaziou."""
    agora = agora or time.time()
    cap = store.get(KV) or {}
    acoes = []
    for m in medidas:
        ag, n = m["agente"], m["trabalhadores"]
        if ag not in ESCALAVEIS:
            continue
        desde = float((cap.get(ag) or {}).get("desde", 0))
        if n > 1 and m["fila"] == 0 and agora - desde >= MIN_ANTES_DE_DESCER:
            _definir(store, ag, n - 1, "fila vazia", agora)
            acoes.append({"agente": ag, "acao": "descer", "para": n - 1})
            continue
        if ag == "corrigir_codigo":
            par, choque = par_do_developer(store)
            ids = " e ".join(f"#{i['id']}" for i in par)
            if n > 1 and choque and m["fila"] > 0:          # o par se cruza: um de cada vez, já (esperar é abrir o conflito)
                _definir(store, ag, 1, f"pegadas se cruzam ({ids}): {', '.join(choque)[:200]}", agora)
                acoes.append({"agente": ag, "acao": "descer", "para": 1})
            elif n > MAX_DEV:
                _definir(store, ag, MAX_DEV, f"teto de {MAX_DEV} Developers em paralelo", agora)
                acoes.append({"agente": ag, "acao": "descer", "para": MAX_DEV})
            elif n < MAX_DEV and m["fila"] >= FILA_ALTA and not choque and agora - desde >= SOBE_A_CADA:
                _definir(store, ag, MAX_DEV, f"fila {m['fila']}, par {ids} com pegadas disjuntas (regra)", agora)
                acoes.append({"agente": ag, "acao": "subir", "para": MAX_DEV, "conf": 1.0})
            continue
        if m["sobrecarregado"] and n < MAX_PARALELO and agora - desde >= SOBE_A_CADA:
            if dl is None:
                sim, conf, fonte = True, 1.0, "regra"
            else:
                from .decision import SN, Question
                d = dl.ask("escalar_agente", Question(
                    "noul", "Vale colocar mais um trabalhador em paralelo no agente `agente` (hoje `trabalhadores`)?",
                    SN("`ocupacao` ≥ 0.6 e `fila` ≥ 3 e `espera_min` ≥ 10 e `escalavel` é true: o agente não dá conta sozinho e o trabalho dele não conflita",
                       "`ocupacao` < 0.6; ou `fila` < 3; ou `escalavel` é false; ou `trabalhadores` já é 3")),
                    {"agente": ag, "trabalhadores": n, "ocupacao": m["ocupacao"], "fila": m["fila"], "espera_min": int(m["espera_s"] / 60),
                     "tarefas_1h": m["tarefas_1h"], "escalavel": True, "porque": ESCALAVEIS[ag]})
                sim, conf, fonte = float(d.value) >= 0.5, float(d.confidence), d.source
            if sim:
                _definir(store, ag, n + 1, f"sobrecarga: ocupação {m['ocupacao']:.0%}, fila {m['fila']}, espera {int(m['espera_s'] / 60)} min (Jev {conf:.2f}, {fonte})", agora)
                acoes.append({"agente": ag, "acao": "subir", "para": n + 1, "conf": conf})
    return {"acoes": acoes}


def rodar(store: Store, dl=None, agora: float | None = None) -> dict:
    agora = agora or time.time()
    medidas = medir(store, agora)
    g = gargalo(medidas)
    dec = decidir(store, dl, medidas, agora)
    store.set(KV + "_ultima", {"em": agora, "gargalo": g["agente"] if g else None, "medidas": medidas, "acoes": dec["acoes"]})
    for a in dec["acoes"]:
        store.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('capacidade',?,?,0)",
                (f"Escalador: {nome(a['agente'])} {'ganhou' if a['acao'] == 'subir' else 'voltou a'} {a['para']} trabalhador(es) em paralelo.", agora))
    return {"gargalo": g, "acoes": dec["acoes"], "medidas": medidas}


def resumo(store: Store) -> dict[str, Any]:
    u = store.get(KV + "_ultima") or {}
    cap = store.get(KV) or {}
    return {"em": u.get("em"), "gargalo": u.get("gargalo"), "medidas": u.get("medidas") or medir(store),
            "paralelo": {ag: int(v.get("trabalhadores", 1)) for ag, v in cap.items() if int(v.get("trabalhadores", 1)) > 1},
            "historico": list(reversed(store.get(KV + "_hist") or []))[:10], "escalaveis": ESCALAVEIS, "nao_escalaveis": NAO_ESCALAVEIS, "max_paralelo": MAX_PARALELO}


__all__ = ["medir", "gargalo", "decidir", "rodar", "resumo", "trabalhadores", "pegada", "colisao", "par_do_developer",
           "ESCALAVEIS", "MAX_PARALELO", "MAX_DEV", "CONVERGENCIA"]
