"""Central de confiança: a pergunta que o painel responde primeiro é "posso confiar no loop agora?".

Desenho tirado das práticas consolidadas (o estudo está no CHANGELOG 1.10.0):
- consciência situacional em três níveis (Endsley): PERCEBER o que está acontecendo agora, ENTENDER se está
  tudo seguro e PROJETAR o que vem a seguir;
- frescor do dado: cada verificação diz de quando é o dado (o horário da fonte, não o da tela) e fica velha sozinha;
  "ao vivo" só aparece quando é de verdade;
- supervisão humana de agentes: trilha da decisão (quem decidiu: regra, Jev ou LLM, e com que confiança), ações em
  tempo real, parada verificável (pausa confirmada pelo último giro) e portões visíveis;
- sinais de ouro (SRE): ritmo (giros), erros, duração e saturação (orçamento);
- calibrar a confiança: mostra a taxa de acerto real de cada neurônio, não só o "está tudo bem".

Cada verificação tem: grupo (agora = Perceber | seguranca = Entender | proximo = Projetar), estado (ok | atencao |
falha | info), o fato (valor), o significado (porquê), a projeção e `dado_em`, para o painel mostrar há quanto tempo o
dado foi produzido. O painel marca cada card como obsoleto quando a leitura passa de `obsoleto_s` (3 s).
"Por que a última ação" vem da trilha write-ahead (circulo/intencoes.py), não do push do painel.
"""
from __future__ import annotations

import json
import time

from . import intencoes, parada
from .state import Store
from .status import loop_status

GIRO_LONGO_S = 20 * 60      # uma etapa rodando há mais que isso merece atenção (o Claude Code tem limite de 30 min)


def _c(id_, grupo, titulo, estado, valor, porque="", dado_em=None, fresco_s=None, projecao="") -> dict:
    """Um card = fato (valor), significado (porque) e, quando há, projeção (o que tende a acontecer)."""
    return {"id": id_, "grupo": grupo, "titulo": titulo, "estado": estado, "valor": valor, "porque": porque,
            "dado_em": dado_em, "fresco_s": fresco_s, "projecao": projecao}


def p99(xs: list[float]) -> float | None:
    """Percentil 99 pelo posto mais próximo: a cauda que a média esconde."""
    if not xs:
        return None
    xs = sorted(xs)
    return xs[max(0, -(-99 * len(xs) // 100) - 1)]


def _ms(v: float) -> str:
    return f"{v / 1000:.1f} s" if v >= 1000 else f"{v:.0f} ms"


def _hora(ts: float | None) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "—"


def confianca(store: Store, now: float | None = None) -> dict:
    s, now = store, now or time.time()
    st = loop_status(s, now)
    ck: list[dict] = []
    b = s.get("batimento") or {}

    # ---------------------------------------------------------------- PERCEBER: o que está acontecendo agora
    if st["estado"] == "desligado":
        ck.append(_c("vivo", "agora", "Processo do loop", "falha", "desligado",
                     "sem batimento: nenhum giro está acontecendo", b.get("em") or st.get("visto_em")))
    elif st["estado"] == "pausado_humano":
        ultimo = s.one("SELECT MAX(created_at) m FROM metrics")["m"]
        pe = parada.estado(s)
        if pe["estado"] == "vazou":
            ck.append(_c("vivo", "agora", "Processo do loop", "falha", "pausado, mas agindo",
                         f"{pe['acoes_depois']} ação(ões) começaram depois que o loop confirmou a parada", b.get("em"), 15))
        elif pe["estado"] == "aguardando":
            ck.append(_c("vivo", "agora", "Processo do loop", "atencao", "parando…",
                         f"parada pedida às {_hora(pe['pedida_em'])}; esperando o loop confirmar no próximo giro", b.get("em"), 15,
                         "o giro em andamento termina e nenhum outro começa"))
        else:
            ck.append(_c("vivo", "agora", "Processo do loop", "info", "pausado por você",
                         f"pausa confirmada: o último giro terminou às {_hora(ultimo)} e nenhum outro começou"
                         + (" (nenhuma ação começou depois da confirmação)" if pe["verificada"] else ""),
                         b.get("em"), 15, "fica parado até você retomar"))
    else:
        idade = st.get("batimento_ha") or 0
        ck.append(_c("vivo", "agora", "Processo do loop", "ok" if idade <= 15 else "atencao", "vivo",
                     f"batimento a cada 5 s; o último foi há {idade:.0f} s", b.get("em"), 15))
    etapa = s.get("etapa") or {}
    if etapa:
        dur = now - float(etapa.get("em") or now)
        trabalhando = etapa.get("nome") not in ("descanso", "pausado")
        ck.append(_c("etapa", "agora", "Fazendo agora", "atencao" if trabalhando and dur > GIRO_LONGO_S else "info",
                     etapa.get("detalhe") or etapa.get("nome") or "—",
                     f"etapa “{etapa.get('nome')}” do giro {etapa.get('tick', s.tick)}, há {dur / 60:.0f} min"
                     if dur >= 60 else f"etapa “{etapa.get('nome')}” do giro {etapa.get('tick', s.tick)}, há {dur:.0f} s",
                     etapa.get("em")))
    d = s.one("SELECT question, value, confidence, source, created_at FROM decisions ORDER BY id DESC LIMIT 1")
    if d:
        quem = {"jev": "pelo Jev", "local": "pela regra", "llm": "pela LLM"}.get(d["source"], f"por {d['source']}")
        ck.append(_c("decisao", "agora", "Última decisão", "info", f"{d['question']} → {json.loads(d['value'])}",
                     f"decidida {quem} com confiança {float(d['confidence'] or 0):.0%}", d["created_at"]))
    dia = s.one("SELECT COUNT(*) n, SUM(source='jev') jev, SUM(source='local') regra, SUM(source='llm') llm "
                "FROM decisions WHERE created_at>=?", (now - 86400,))
    if dia["n"]:
        ck.append(_c("quem_decide", "agora", "Quem decide (24 h)", "info",
                     f"Jev {100 * (dia['jev'] or 0) / dia['n']:.0f}% · regra {100 * (dia['regra'] or 0) / dia['n']:.0f}% · "
                     f"LLM {100 * (dia['llm'] or 0) / dia['n']:.0f}%",
                     "a LLM só entra quando o Jev está em dúvida e o gasto vale a pena", now))

    # sinais de ouro do loop (SRE): latência, tráfego, erros e saturação; latência em percentil, porque a média esconde a cauda
    dur = [r["d"] for r in s.q("SELECT json_extract(body,'$.duracao_ms') d FROM metrics WHERE created_at>=? "
                               "AND json_extract(body,'$.duracao_ms') IS NOT NULL", (now - 86400,))]
    if dur:
        lat = p99(dur)
        ck.append(_c("latencia", "agora", "Latência do giro (p99, 24 h)", "atencao" if lat > GIRO_LONGO_S * 1000 else "ok",
                     f"p99 {_ms(lat)} · mediana {_ms(sorted(dur)[len(dur) // 2])}",
                     f"{len(dur)} giros medidos; giros com o Desenvolvedor podem levar minutos",
                     now, projecao="acima de 20 min no p99, um giro travado segura todo o resto"))
    hora = s.one("SELECT COUNT(*) n, MAX(created_at) em FROM metrics WHERE created_at>=?", (now - 3600,))
    acoes = s.one("SELECT COUNT(*) n FROM intencoes WHERE tipo='intencao' AND ator='loop' AND em>=?", (now - 3600,))["n"]
    ck.append(_c("trafego", "agora", "Tráfego (1 h)", "info", f"{hora['n']} giros · {acoes} ações",
                 "cada ação foi registrada na trilha antes de rodar", hora["em"] or now))
    ult = s.q("SELECT tick, body, created_at FROM metrics ORDER BY tick DESC LIMIT 50")
    erros = [(r["tick"], e) for r in ult for e in json.loads(r["body"]).get("errors", [])]
    ck.append(_c("erros", "agora", "Erros nos últimos giros", "ok" if not erros else "atencao", f"{len(erros)} em {len(ult)} giros",
                 "nenhum" if not erros else f"o mais recente (giro {erros[0][0]}): {str(erros[0][1])[:140]}",
                 ult[0]["created_at"] if ult else None,
                 projecao="" if not erros else "erro que se repete vira lição e a etapa pode ir para a quarentena"))
    bud = s.one("SELECT * FROM budget ORDER BY day DESC LIMIT 1")
    if bud:
        from .orcamento_dia import limite_hoje
        from .budget import modo_orcamento
        limite = limite_hoje(s)
        usado = int(bud["tokens"] or 0)
        frac = usado / limite
        if modo_orcamento(s) == "ilimitado":                     # sem limite: medindo, nada satura
            escolhido = (s.get("orcamento_limite") or {}).get("limite")
            ref = f" (referência escolhida: {int(escolhido):,})" if escolhido else ""
            ck.append(_c("orcamento", "agora", "Consumo de hoje (sem limite)", "ok", f"{usado:,} tokens{ref}".replace(",", "."),
                         "modo medindo: nada é cortado; o limite será definido com os dados", now,
                         projecao="ver Consumo de tokens para a sugestão de limite (p90)"))
        else:
            ck.append(_c("orcamento", "agora", "Saturação (orçamento de hoje)", "ok" if frac < .8 else "atencao" if frac < 1 else "falha",
                         f"{frac:.0%} ({usado:,} de {limite:,} tokens)".replace(",", "."),
                         f"{s.pending_count()} pedido(s) na fila", now,
                         projecao="no fim do orçamento o loop pausa sozinho até a meia-noite"))
    fr = [r["atraso_ms"] for r in s.q("SELECT atraso_ms FROM frescor WHERE em>=?", (now - 86400,))]
    if fr:
        f99 = p99(fr)
        ck.append(_c("frescor", "agora", "Frescor do painel (p99, 24 h)", "ok" if f99 <= FRESCOR_MAX_MS else "atencao",
                     f"p99 {_ms(f99)} (meta ≤ {_ms(FRESCOR_MAX_MS)})", f"{len(fr)} medições do atraso entre o dado e a sua tela",
                     now, projecao="" if f99 <= FRESCOR_MAX_MS else "acima da meta, o que você vê pode não ser o agora"))

    # ---------------------------------------------------------------- ENTENDER: por que agiu assim e está tudo seguro?
    acao = intencoes.ultima(s, ator="loop")
    if acao:
        res = acao["resultado"]
        ck.append(_c("acao", "seguranca", "Por que a última ação", "info" if not res or res["ok"] else "atencao",
                     f"{acao['acao']}: {acao['motivo']}",
                     f"decidida por: {acao['regra'] or 'regra fixa'}; registrada na trilha antes de rodar (#{acao['seq']})",
                     acao["em"], projecao="em andamento" if not res else "terminou bem" if res["ok"] else
                     f"falhou: {str(res.get('detalhe', ''))[:120]}"))
    cad, div = intencoes.verificar(s), intencoes.divergencia(s)
    ck.append(_c("trilha", "seguranca", "Trilha write-ahead", "ok" if cad["ok"] and not div else "falha",
                 "íntegra" if cad["ok"] and not div else ("cadeia quebrada" if not cad["ok"] else f"{div} ação(ões) sem registro"),
                 "cada ação é gravada antes de rodar, num log só de acréscimo encadeado por hash" if cad["ok"] and not div else
                 (f"o hash não confere a partir do registro #{cad['quebra']}" if not cad["ok"] else
                  "houve ação executada sem intenção gravada antes"),
                 now, projecao="" if cad["ok"] and not div else "a trilha deixou de ser prova: investigue antes de confiar"))
    pt = s.one("SELECT ok, created_at FROM verificacoes WHERE ponto='loop:parada' ORDER BY id DESC LIMIT 1")
    if pt:
        dias = (now - pt["created_at"]) / 86400
        ck.append(_c("parada", "seguranca", "Botão de parada testado",
                     "falha" if not pt["ok"] else "ok" if dias <= 8 else "atencao",
                     ("passou" if pt["ok"] else "falhou") + f" há {dias:.0f} dia(s)" if dias >= 1 else
                     ("passou" if pt["ok"] else "falhou") + " hoje",
                     "o loop apertou o próprio botão, parou no giro e nenhuma ação começou depois" if pt["ok"] else
                     "o teste da parada falhou: o botão pode não parar o loop", pt["created_at"],
                     projecao="o próximo teste roda em até 7 dias"))
    else:
        ck.append(_c("parada", "seguranca", "Botão de parada testado", "info", "ainda não testado",
                     "o loop testa a parada quando sobe e depois toda semana", now))
    corpo = s.get("corpo") or {}
    if corpo.get("estado"):
        e = corpo["estado"]
        ck.append(_c("corpo", "seguranca", "Código rodando", {"ok": "ok", "validando": "atencao", "revertido": "atencao"}.get(e, "info"),
                     str(corpo.get("sha", ""))[:7] or "—",
                     {"ok": "validado antes da troca (importação + testes) e evidenciado por 5 giros sem erro",
                      "validando": f"código novo em prova: {corpo.get('giros_ok', 0)} de 5 giros sem erro",
                      "revertido": "o código novo errou nos primeiros giros e o loop voltou para o anterior"}.get(e, e),
                     corpo.get("checado_em")))
    main = s.one("SELECT ok, sujeito, created_at FROM verificacoes WHERE ponto='gate:main' ORDER BY id DESC LIMIT 1")
    if main:
        ck.append(_c("main", "seguranca", "CI da main", "ok" if main["ok"] else "falha", "verde" if main["ok"] else "vermelho",
                     f"último CI da main ({main['sujeito'][:7]})" + ("" if main["ok"] else ": algo entrou quebrado; virou lição"),
                     main["created_at"]))
    lic = s.one("SELECT SUM(classe='estrutural' AND status IN ('aberta','em_correcao','reincidente')) abertas, "
                "COALESCE(SUM(reincidencias),0) reinc, COUNT(*) total, SUM(status='evidenciada') evid, MAX(updated_at) em FROM licoes")
    ck.append(_c("reincidencia", "seguranca", "Erros repetidos", "ok" if not lic["reinc"] else "falha",
                 f"{lic['reinc']} reincidência(s)",
                 "nenhum erro já corrigido voltou" if not lic["reinc"] else "um erro já corrigido voltou: prioridade máxima",
                 lic["em"] or now))
    ck.append(_c("licoes", "seguranca", "Erros de estrutura abertos", "ok" if not lic["abertas"] else "atencao",
                 f"{lic['abertas'] or 0} aberta(s) · {lic['evid'] or 0} aprendida(s) de {lic['total']}",
                 "com erro de estrutura aberto, o loop corrige antes de evoluir" if lic["abertas"] else "nada pendente de correção",
                 lic["em"] or now))
    v = s.one("SELECT COUNT(*) n, SUM(ok=0) f, MAX(created_at) em FROM verificacoes WHERE created_at>=?", (now - 86400,))
    barrou = s.one("SELECT COALESCE(SUM(bloqueios),0) b, COUNT(*) n FROM portoes WHERE ativo=1")
    if v["n"]:
        ck.append(_c("portoes", "seguranca", "Portões (24 h)", "info",
                     f"{v['n'] - (v['f'] or 0)} de {v['n']} verificações passaram",
                     f"{barrou['n']} portão(ões) aprendido(s) com erros; barraram {barrou['b']} vez(es) antes de chegar a um PR",
                     v["em"]))
    pg = s.get("progresso") or {}
    sem = int(pg.get("sem", 0))
    from .estagnacao import causa_provavel
    from .loop import ESTAGNADO
    ck.append(_c("progresso", "seguranca", "Avançando?", "ok" if sem < 3 else "atencao" if sem < ESTAGNADO else "falha",
                 "sim" if sem < 3 else f"{sem} giros sem avançar",
                 (f"último avanço {_hora(pg.get('ultimo_avanco_em'))}" if sem < 3 else
                  f"há trabalho esperando e nada avança; {causa_provavel(pg)}"),
                 pg.get("ultimo_avanco_em") or now))
    q = {k: x for k, x in (s.get("quarentena") or {}).items() if x.get("ate_tick", 0) > s.tick}
    if q:
        ck.append(_c("quarentena", "seguranca", "Etapas isoladas", "atencao", ", ".join(q),
                     "falharam em sequência e ficam fora por alguns giros; o resto segue", now))
    from . import finance
    viol = finance.check_invariants(s)
    ck.append(_c("dinheiro", "seguranca", "Invariantes do dinheiro", "ok" if not viol else "falha",
                 "íntegros" if not viol else f"{len(viol)} violado(s)",
                 "saldo, somas e categorias conferidos a cada giro" if not viol else "; ".join(viol)[:200], now))
    dev = s.get("self_dev_aberto") or {}
    espera = s.get("self_dev_espera") or {}
    if float(espera.get("ate", 0)) > now:
        ck.append(_c("developer", "seguranca", "Desenvolvedor", "atencao", f"esperando até {espera.get('hora')}",
                     espera.get("motivo", ""), now))
    elif dev.get("pr") and not dev.get("fechado"):
        m = s.one("SELECT reason, created_at FROM merges WHERE pr=? ORDER BY id DESC LIMIT 1", (dev["pr"],))
        ck.append(_c("developer", "seguranca", "Desenvolvedor", "info", f"PR #{dev['pr']} aberto",
                     f"gate: {m['reason']}" if m else "esperando o CI", m["created_at"] if m else dev.get("em")))

    # missões pausadas por você: o loop segue, elas não
    try:
        paradas = s.q("SELECT id, nome, pausada_em FROM projects WHERE COALESCE(pausada,0)=1 ORDER BY pausada_em")
    except Exception:  # noqa: BLE001
        paradas = []
    if paradas:
        from .pausa import em_ciclo
        parando = [p["nome"] for p in paradas if em_ciclo(s, p["id"])]
        ck.append(_c("missoes_pausadas", "agora", "Missões pausadas por você", "info", f"{len(paradas)} missão(ões)",
                     ", ".join(p["nome"] for p in paradas)[:200] + (f"; terminando o ciclo em curso: {', '.join(parando)}" if parando else
                                                                    "; nenhum ciclo delas rodando"), now))

    # rastreabilidade e SLOs (observabilidade.py): cada entrega tem o fio inteiro? os objetivos de serviço estão de pé?
    try:
        from .observabilidade import slos as _slos
        from .rastro import completude
        comp = completude(s, now=now)
        if comp["total"]:
            ck.append(_c("rastro", "seguranca", "Rastro de ponta a ponta",
                         "ok" if not comp["incompletos"] else "atencao", f"{comp['completos']} de {comp['total']} entregas",
                         "cada entrega ligada da origem (pedido, pergunta ou lição) até a evidência no código rodando"
                         if not comp["incompletos"] else "com lacuna: " + "; ".join(f"#{x['id']} {x['lacunas'][0]}" for x in comp["incompletos"][:3]),
                         now))
        lista = [x for x in _slos(s, now) if x["estado"] != "sem_dados"]
        if lista:
            ruins = [x for x in lista if x["estado"] == "violado"]
            risco = [x for x in lista if x["estado"] == "em_risco"]
            ck.append(_c("slos", "seguranca", "Objetivos de serviço (SLOs)", "atencao" if ruins or risco else "ok",
                         f"{len(lista) - len(ruins)} de {len(lista)} cumpridos",
                         "violado: " + ", ".join(x["nome"].lower() for x in ruins) if ruins else
                         "orçamento de erro acabando: " + ", ".join(x["nome"].lower() for x in risco) if risco else
                         "todos dentro do alvo, com orçamento de erro sobrando", now))
    except Exception:  # noqa: BLE001 — a central de confiança nunca cai por causa de um indicador
        pass

    # ---------------------------------------------------------------- PROJETAR: o que vem a seguir
    prox = b.get("proximo_giro_em")
    if prox and st["estado"] not in ("desligado", "pausado_humano"):
        ck.append(_c("proximo_giro", "proximo", "Próximo giro", "info", _hora(prox),
                     "ritmo adaptativo: 15 s com trabalho, 5 min sem", b.get("em")))
    alvo = s.one("SELECT id, titulo, origem FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 "
                 "AND evidencia NOT LIKE '%depende de você%' AND (origem='erro' OR estudo IS NOT NULL) "
                 "ORDER BY CASE origem WHEN 'erro' THEN 0 WHEN 'pedido_cassio' THEN 1 ELSE 2 END, ordem LIMIT 1")
    estudar = s.one("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND origem IN ('pedido_cassio','loop') "
                    "AND COALESCE(desativado,0)=0 AND estudo IS NULL AND evidencia NOT LIKE '%depende de você%'")["n"]
    if alvo:
        ck.append(_c("proximo_item", "proximo", "Próximo trabalho do Desenvolvedor", "info", f"#{alvo['id']} {alvo['titulo'][:90]}",
                     {"erro": "erro do próprio loop vem primeiro", "pedido_cassio": "seu pedido, já estudado"}.get(alvo["origem"],
                                                                                                                 "planejado pelo loop, já estudado"), now))
    if estudar:
        ck.append(_c("estudo", "proximo", "Esperando estudo", "info", f"{estudar} pedido(s)",
                     "antes de executar, o loop pesquisa em fontes confiáveis e decide adotar, adaptar ou contestar", now))
    ultima = s.one("SELECT persona, texto, status, item_id, created_at FROM perguntas ORDER BY id DESC LIMIT 1")
    if ultima:
        st_p = {"feita": "sendo respondida", "virou_item": f"virou o item #{ultima['item_id']}", "entregue": "entregue",
                "contestada": "contestada pelo estudo", "repetida": "já existia", "descartada": "sem item novo"}.get(ultima["status"], ultima["status"])
        ck.append(_c("conselho", "proximo", f"Última pergunta do conselho ({ultima['persona']})", "info", ultima["texto"][:140],
                     f"{st_p}; a evolução parte de perguntas, escolhidas por dor medida e custo, sem LLM", ultima["created_at"]))
    plan = s.get("planejador") or {}
    if plan.get("em") and not alvo and not estudar:
        ck.append(_c("planejador", "proximo", "Planejador", "info", f"próxima tentativa {_hora(float(plan['em']) + 1800)}",
                     "com o roteiro vazio, o loop planeja o próximo item a partir da própria evidência", plan["em"]))
    if corpo.get("checado_em"):
        ck.append(_c("corpo_prox", "proximo", "Próxima checagem do código", "info", _hora(float(corpo["checado_em"]) + 600),
                     "a main é checada a cada 10 min e logo depois de cada merge", corpo["checado_em"]))

    # risco do próximo passo: o que já está em falha ou em observação tende a pesar no que vem
    falhas = [c["titulo"].lower() for c in ck if c["estado"] == "falha"]
    obs = [c["titulo"].lower() for c in ck if c["estado"] == "atencao"]
    ck.append(_c("risco", "proximo", "Risco do próximo passo", "info",
                 "alto" if falhas else "médio" if obs else "baixo",
                 ("por causa de: " + ", ".join(falhas or obs)) if falhas or obs else "nada em falha ou em observação",
                 now, projecao="o loop corrige a falha antes de evoluir" if falhas else
                 "segue, de olho nos pontos em observação" if obs else "segue o roteiro"))

    estados = [c["estado"] for c in ck]
    if st["estado"] == "desligado":
        veredito, frase = "parado", "O loop está desligado: nada está sendo feito agora."
    elif "falha" in estados:
        veredito = "falha"
        frase = "Atenção: " + "; ".join(f"{c['titulo'].lower()} — {c['valor']}" for c in ck if c["estado"] == "falha")
    elif "atencao" in estados:
        veredito = "atencao"
        frase = "Tudo sob controle, com pontos em observação: " + \
                "; ".join(f"{c['titulo'].lower()} — {c['valor']}" for c in ck if c["estado"] == "atencao")
    else:
        veredito, frase = "confiavel", "Todas as verificações de segurança passaram e o loop está vivo."
    from .projects import kit_project_id
    return {"veredito": veredito, "frase": frase, "checks": ck, "gerado_em": now, "loop": st["estado"],
            "circulo_id": kit_project_id(s, "circulo"), "obsoleto_s": FRESCOR_MAX_MS / 1000, "parada": parada.estado(s)}


FRESCOR_MAX_MS = 3000       # SLO do painel: p99 do atraso dado → tela ≤ 3 s numa janela de 24 h


def versao_painel() -> str:
    """Versão da página do painel no ar: a página servida a carrega e a devolve em cada medição de frescor."""
    import hashlib
    from importlib import resources
    return hashlib.sha256(resources.files("circulo").joinpath("painel.html").read_bytes()).hexdigest()[:12]


def registrar_frescor(store: Store, atraso_ms: float, versao: str | None = None) -> bool:
    """Neurônio `painel:frescor`: o próprio painel informa o atraso entre o dado e a tela. Cada medição fica guardada
    e o SLO é o p99 das últimas 24 h, não a média nem a última leitura. A verificação roda no máximo 1 vez por
    minuto; p99 acima de FRESCOR_MAX_MS vira lição. Só a página no ar é julgada: amostra de aba com página antiga
    é descartada e a janela recomeça quando a página muda (um conserto não reabre a lição com dado velho)."""
    now = time.time()
    import math
    try:
        atraso_ms = float(atraso_ms)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(atraso_ms) or atraso_ms < 0 or atraso_ms > 600_000:
        return False                      # NaN/inf/negativo ou aba parada por mais de 10 min (Mac dormiu): não é medição do painel
    atual = versao_painel()
    if versao is not None and versao != atual:
        return False
    if store.get("frescor_versao") not in (None, atual):
        store.set("frescor_desde", now)
    store.set("frescor_versao", atual)
    sid = store.x("INSERT INTO frescor(atraso_ms, em) VALUES(?,?)", (atraso_ms, now))
    if sid % 500 == 0:
        store.x("DELETE FROM frescor WHERE em < ?", (now - 2 * 86400,))
    ultimo = store.get("painel_frescor_em") or 0
    if now - float(ultimo) < 60:
        return False
    store.set("painel_frescor_em", now)
    from .licoes import Licoes
    desde = max(now - 86400, float(store.get("frescor_desde") or 0))
    amostras = [r["atraso_ms"] for r in store.q("SELECT atraso_ms FROM frescor WHERE em>=?", (desde,))]
    if len(amostras) < 100:
        return False                      # com poucas amostras o p99 é o máximo: uma aba em segundo plano viraria lição
    f99 = p99(amostras) or 0
    ok = f99 <= FRESCOR_MAX_MS
    Licoes(store).verificar("painel:frescor", ok, sujeito=f"p99 24 h {f99:.0f} ms",
                            motivo="" if ok else f"painel atrasado: p99 {f99:.0f} ms em 24 h (meta {FRESCOR_MAX_MS} ms)",
                            assinatura=None if ok else "painel:frescor_atrasado", classe="ambiente")
    return True
