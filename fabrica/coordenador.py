"""O coordenador: passa o cartão de estação em estação, um por vez, e fecha o círculo.

- Um cartão em voo de cada vez (confiança antes de paralelismo). O próximo só entra quando este termina ou bloqueia.
- Só evidência MEDIDA avança o cartão; estação que avança sem medir é bloqueada e vira achado.
- Devolução conta; na terceira seguida o cartão bloqueia e chama o humano, com o histórico à vista.
- Sem pedido humano, o Gerente de produto pega o achado mais frequente e faz dele um cartão: é assim que a fábrica
  trabalha em si mesma quando ninguém pede nada.
- Toda passagem vira evento (o painel assiste) e passo (o histórico do cartão).
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Callable

from .estado import Estado
from .modelo import ESTADOS, FINAIS, MAX_DEVOLUCOES, PAPEIS, Evidencia, Resultado, e_devolucao, transicao_valida
from .oficina import Executor, GitHub, Projeto, Simulado, executor_padrao, github_padrao
from .papeis import FUNCOES

TOM = {"planejado": "tarefa", "em_desenvolvimento": "tarefa", "verificando": "entrega", "em_revisao": "entrega", "liberando": "entrega",
       "concluido": "entrega", "bloqueado": "alerta", "cancelado": "alerta"}


class Fabrica:
    def __init__(self, projeto: Projeto, estado: Estado, executor: Executor | None = None, github: GitHub | None = None,
                 relogio: Callable[[], float] = time.time):
        self.projeto, self.estado = projeto, estado
        self.executor = executor or executor_padrao()
        self.github = github if github is not None else github_padrao(projeto)
        self.relogio = relogio

    # ---------- pedidos
    def pedir(self, texto: str, origem: str = "humano") -> int:
        titulo = texto.strip().splitlines()[0][:120] if texto.strip() else "pedido"
        return self.estado.novo_cartao(titulo, texto.strip(), origem)

    def pausar(self, sim: bool = True) -> None:
        self.estado.set("pausada", bool(sim))

    @property
    def pausada(self) -> bool:
        return bool(self.estado.get("pausada", False))

    # ---------- o círculo fecha: achado vira cartão
    def _cartao_de_achado(self) -> dict | None:
        for a in self.estado.achados_abertos():
            if a["assunto"].startswith(("protegido:", "github:", "implantacao:", "producao:")):
                continue                          # esses dependem do humano, não viram trabalho da fábrica
            if self.estado.um("SELECT 1 FROM cartoes WHERE origem='fabrica' AND pedido LIKE ? AND estado NOT IN ('concluido','cancelado')", (f"%[achado #{a['id']}]%",)):
                continue
            cid = self.estado.novo_cartao(f"Achado: {a['assunto']}", f"{a['texto']}\n\n[achado #{a['id']}] visto {a['vezes']}x pelo papel {a['papel']}.", "fabrica")
            self.estado.evento("mensagem", cid, "po", "po", f"Sem pedido na fila: o achado “{a['assunto']}” vira o cartão #{cid}.", {"tom": "tarefa"})
            return self.estado.cartao(cid)
        return None

    # ---------- um passo
    def passo(self) -> dict | None:
        if self.pausada:
            return None
        self.estado.set("batimento", {"em": self.relogio()})
        c = self.estado.em_andamento() or self.estado.proximo_novo() or self._cartao_de_achado()
        if c is None:
            return None
        papel = ESTADOS[c["estado"]]
        nome = PAPEIS[papel]["nome"]
        self.estado.evento("vez", c["id"], "coordenador", papel, f"{nome}, sua vez: cartão #{c['id']} ({c['estado'].replace('_', ' ')}).", {"estado": c["estado"]})
        t0 = self.relogio()
        try:
            r = FUNCOES[papel](self, c)
        except Exception as exc:  # noqa: BLE001 — a estação quebrou: isso é um achado, não o fim da fábrica
            r = Resultado("bloqueado", f"A estação {nome} quebrou: {exc}", [Evidencia("medido", "exceção na estação", traceback.format_exc()[-1500:])])
            self.estado.achado(papel, f"estacao_quebrou:{papel}", f"{nome} lançou {type(exc).__name__}: {str(exc)[:200]}", "medido", c["id"])
        dur = self.relogio() - t0
        de, para = c["estado"], r.para
        esperando = bool(r.dados.get("esperando"))
        if para != de and not transicao_valida(de, para):
            r = Resultado("bloqueado", f"{nome} tentou mover o cartão de {de} para {para}, que não existe no círculo.", r.evidencias + [Evidencia("medido", "transição inválida", (de, para))])
            para = "bloqueado"
        if para not in FINAIS and para != de and not e_devolucao(de, para) and not r.medida:
            self.estado.achado(papel, f"sem_medida:{papel}", f"{nome} avançou o cartão #{c['id']} sem evidência medida.", "medido", c["id"])
            r = Resultado("bloqueado", f"{nome} quis avançar sem nenhuma evidência medida; a fábrica não avança no escuro.", r.evidencias)
            para = "bloqueado"
        devolucao = (para == de and not esperando) or e_devolucao(de, para)
        if devolucao and c["devolucoes"] + 1 > MAX_DEVOLUCOES:
            self.estado.achado(papel, f"devolucoes:{papel}", f"O cartão #{c['id']} foi devolvido {c['devolucoes'] + 1}x; a última: {r.mensagem[:200]}", "medido", c["id"])
            r = Resultado("bloqueado", f"Devolvido {c['devolucoes'] + 1} vezes ({r.mensagem[:120]}). Fica para você, com o histórico.", r.evidencias, r.dados)
            para, devolucao = "bloqueado", False
        self.estado.passo(c["id"], papel, de, para, r.mensagem, r.evidencias, dur)
        self.estado.mover(c["id"], para, r.dados, devolucao)
        destino = ESTADOS.get(para) or ("humano" if para == "bloqueado" else "po")
        tom = "devolucao" if devolucao else ("status" if esperando else TOM.get(para, "status"))
        self.estado.evento("mensagem", c["id"], papel, destino, r.mensagem, {"tom": tom, "de_estado": de, "para_estado": para, "segundos": round(dur, 2),
                                                                            "evidencias": [e.__dict__ for e in r.evidencias][:6]})
        if para == "concluido":
            self.estado.evento("entrega", c["id"], "release", "po", f"Cartão #{c['id']} concluído: {c['titulo'][:100]}", {"tom": "entrega"})
        return {"cartao": c["id"], "papel": papel, "de": de, "para": para, "mensagem": r.mensagem, "segundos": round(dur, 2), "devolucao": devolucao}

    def rodar(self, intervalo: float = 2.0, max_passos: int | None = None, dormir: Callable[[float], None] = time.sleep) -> int:
        n = 0
        while max_passos is None or n < max_passos:
            r = self.passo()
            n += 1
            self.estado.set("batimento", {"em": self.relogio(), "ultimo": r})
            if r is None:
                dormir(intervalo * 3)
            elif r.get("para") == "liberando" and not r.get("devolucao"):
                dormir(intervalo * 5)      # esperando o CI: não martela o GitHub
            else:
                dormir(intervalo)
        return n


def abrir(raiz: str | Path, dados: str | Path | None = None, executor: Executor | None = None, github: GitHub | None = None) -> Fabrica:
    projeto = Projeto.abrir(raiz)
    pasta = Path(dados) if dados else projeto.raiz / ".fabrica"
    pasta.mkdir(parents=True, exist_ok=True)
    return Fabrica(projeto, Estado(pasta / "fabrica.db"), executor, github)


__all__ = ["Fabrica", "abrir", "Simulado"]
