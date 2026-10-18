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

Cada verificação tem: grupo (agora | seguranca | proximo), estado (ok | atencao | falha | info), o valor, o porquê e
`dado_em`, para o painel mostrar há quanto tempo o dado foi produzido.
"""
from __future__ import annotations

import json
import time

from .state import Store
from .status import loop_status

GIRO_LONGO_S = 20 * 60      # uma etapa rodando há mais que isso merece atenção (o Claude Code tem limite de 30 min)


def _c(id_, grupo, titulo, estado, valor, porque="", dado_em=None, fresco_s=None) -> dict:
    return {"id": id_, "grupo": grupo, "titulo": titulo, "estado": estado, "valor": valor, "porque": porque,
            "dado_em": dado_em, "fresco_s": fresco_s}


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
        ck.append(_c("vivo", "agora", "Processo do loop", "info", "pausado por você",
                     f"pausa confirmada: o último giro terminou às {_hora(ultimo)} e nenhum outro começou",
                     b.get("em"), 15))
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

    # ---------------------------------------------------------------- ENTENDER: está tudo seguro?
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
    rec = pg.get("recusas") or {}
    causa = ", ".join(f"{t} recusado {n}x pelo porteiro do gasto" for t, n in sorted(rec.items(), key=lambda kv: -kv[1])[:3])
    from .loop import ESTAGNADO
    ck.append(_c("progresso", "seguranca", "Avançando?", "ok" if sem < 3 else "atencao" if sem < ESTAGNADO else "falha",
                 "sim" if sem < 3 else f"{sem} giros sem avançar",
                 (f"último avanço {_hora(pg.get('ultimo_avanco_em'))}" if sem < 3 else
                  f"há trabalho esperando e nada avança; {causa or 'causa ainda não identificada'}"),
                 pg.get("ultimo_avanco_em") or now))
    ult = s.q("SELECT tick, body, created_at FROM metrics ORDER BY tick DESC LIMIT 50")
    erros = [(r["tick"], e) for r in ult for e in json.loads(r["body"]).get("errors", [])]
    ck.append(_c("erros", "seguranca", "Erros nos últimos giros", "ok" if not erros else "atencao", f"{len(erros)} em {len(ult)} giros",
                 "nenhum" if not erros else f"o mais recente (giro {erros[0][0]}): {str(erros[0][1])[:140]}",
                 ult[0]["created_at"] if ult else None))
    q = {k: x for k, x in (s.get("quarentena") or {}).items() if x.get("ate_tick", 0) > s.tick}
    if q:
        ck.append(_c("quarentena", "seguranca", "Etapas isoladas", "atencao", ", ".join(q),
                     "falharam em sequência e ficam fora por alguns giros; o resto segue", now))
    bud = s.one("SELECT * FROM budget ORDER BY day DESC LIMIT 1")
    pol = s.one("SELECT body FROM policy_versions WHERE status='active' ORDER BY version DESC LIMIT 1")
    if bud and pol:
        limite = int(json.loads(pol["body"])["budget"]["daily_token_limit"]) or 1
        usado = int(bud["tokens"] or 0)
        frac = usado / limite
        ck.append(_c("orcamento", "seguranca", "Orçamento de hoje", "ok" if frac < .8 else "atencao" if frac < 1 else "falha",
                     f"{frac:.0%} ({usado:,} de {limite:,} tokens)".replace(",", "."),
                     "no fim do orçamento o loop pausa sozinho até a meia-noite", now))
    from . import finance
    viol = finance.check_invariants(s)
    ck.append(_c("dinheiro", "seguranca", "Invariantes do dinheiro", "ok" if not viol else "falha",
                 "íntegros" if not viol else f"{len(viol)} violado(s)",
                 "saldo, somas e categorias conferidos a cada giro" if not viol else "; ".join(viol)[:200], now))
    dev = s.get("self_dev_aberto") or {}
    espera = s.get("self_dev_espera") or {}
    if float(espera.get("ate", 0)) > now:
        ck.append(_c("developer", "seguranca", "Developer", "atencao", f"esperando até {espera.get('hora')}",
                     espera.get("motivo", ""), now))
    elif dev.get("pr") and not dev.get("fechado"):
        m = s.one("SELECT reason, created_at FROM merges WHERE pr=? ORDER BY id DESC LIMIT 1", (dev["pr"],))
        ck.append(_c("developer", "seguranca", "Developer", "info", f"PR #{dev['pr']} aberto",
                     f"gate: {m['reason']}" if m else "esperando o CI", m["created_at"] if m else dev.get("em")))

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
        ck.append(_c("proximo_item", "proximo", "Próximo trabalho do Developer", "info", f"#{alvo['id']} {alvo['titulo'][:90]}",
                     {"erro": "erro do próprio loop vem primeiro", "pedido_cassio": "seu pedido, já estudado"}.get(alvo["origem"],
                                                                                                                 "planejado pelo loop, já estudado"), now))
    if estudar:
        ck.append(_c("estudo", "proximo", "Esperando estudo", "info", f"{estudar} pedido(s)",
                     "antes de executar, o loop pesquisa em fontes confiáveis e decide adotar, adaptar ou contestar", now))
    plan = s.get("planejador") or {}
    if plan.get("em") and not alvo and not estudar:
        ck.append(_c("planejador", "proximo", "Planejador", "info", f"próxima tentativa {_hora(float(plan['em']) + 1800)}",
                     "com o roteiro vazio, o loop planeja o próximo item a partir da própria evidência", plan["em"]))
    if corpo.get("checado_em"):
        ck.append(_c("corpo_prox", "proximo", "Próxima checagem do código", "info", _hora(float(corpo["checado_em"]) + 600),
                     "a main é checada a cada 10 min e logo depois de cada merge", corpo["checado_em"]))

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
            "circulo_id": kit_project_id(s, "circulo")}


FRESCOR_MAX_MS = 3000


def registrar_frescor(store: Store, atraso_ms: float) -> bool:
    """Neurônio `painel:frescor`: o próprio painel informa o atraso entre o dado e a tela. Monitorado como qualquer
    ponto do loop (no máximo 1 registro por minuto); acima de FRESCOR_MAX_MS vira lição."""
    ultimo = store.get("painel_frescor_em") or 0
    if time.time() - float(ultimo) < 60:
        return False
    store.set("painel_frescor_em", time.time())
    from .licoes import Licoes
    ok = 0 <= atraso_ms <= FRESCOR_MAX_MS
    Licoes(store).verificar("painel:frescor", ok, sujeito="painel", motivo="" if ok else f"painel atrasado {atraso_ms:.0f} ms",
                            assinatura=None if ok else "painel:frescor_atrasado", classe="estrutural")
    return True
