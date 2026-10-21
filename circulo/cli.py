"""circulo run [--painel] | painel | demo | tick [-n N] | add "38,90 ifood almoço" | status | resumo | respostas"""
from __future__ import annotations

import argparse
import json
import os

from .configuracao import carregar_env


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="circulo")
    ap.add_argument("--data", default=os.environ.get("CIRCULO_DATA", "data"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="loop infinito (pausa só por orçamento ou por você)")
    r.add_argument("--painel", action="store_true", help="serve o painel local junto com o loop")
    r.add_argument("--porta", type=int, default=8765)
    r.add_argument("--metricas-porta", type=int, default=None,
                   help="expõe /metrics (prometheus_client) nesta porta; desligado por padrão (ou CIRCULO_METRICS_PORT)")
    pn =sub.add_parser("painel", help="só o painel local (o loop roda em outro processo)")
    pn.add_argument("--porta", type=int, default=8765)
    d = sub.add_parser("demo", help="loop acelerado com pedidos simulados + painel, em dados separados")
    d.add_argument("--porta", type=int, default=8765)
    t = sub.add_parser("tick", help="roda N giros e sai")
    t.add_argument("-n", type=int, default=1)
    a = sub.add_parser("add", help="enfileira uma mensagem")
    a.add_argument("texto", nargs="+")
    sub.add_parser("status")
    sub.add_parser("resumo")
    sub.add_parser("respostas", help="mostra respostas ainda não lidas")
    sub.add_parser("snapshot", help="faz um backup consistente do banco agora")
    sub.add_parser("configurar", help="cria o arquivo de configuração única (chaves) com permissão 600")
    ini = sub.add_parser("init", help="prepara QUALQUER repositório para o loop cuidar dele (kit: constituição, testes, CI, pedido)")
    ini.add_argument("pasta", help="clone local do repositório (com remoto no GitHub)")
    ini.add_argument("--pedido", default=None, help="o pedido inicial do loop para esse repositório")
    ini.add_argument("--nome", default=None)
    ini.add_argument("--sem-ci", action="store_true", help="não escreve o workflow de CI no repositório")
    ini.add_argument("--json", action="store_true")
    dg = sub.add_parser("diagnostico", help="mostra o que está ligado, o que está parado e por quê")
    dg.add_argument("--testar", action="store_true", help="chama as APIs de verdade (gasta um pouquinho)")
    dg.add_argument("--json", action="store_true")
    ins = sub.add_parser("instalar", help="registra o loop para rodar 24/7 (launchd/systemd) com o painel")
    ins.add_argument("--porta", type=int, default=8765)
    ins.add_argument("--so-arquivo", action="store_true", help="só escreve o arquivo do serviço, sem ligar")
    sub.add_parser("desinstalar", help="desliga o serviço 24/7 (o arquivo fica guardado, não é apagado)")
    dv = sub.add_parser("dev", help="pede ao Developer para corrigir um item do roteiro agora")
    dv.add_argument("--item", type=int, default=None)
    sub.add_parser("verificar", help="verificação de ponta a ponta do painel pelo mapa de funcionalidades")
    rs = sub.add_parser("restaurar", help="restaura um snapshot (o banco atual é guardado antes)")
    rs.add_argument("arquivo")
    args = ap.parse_args(argv)
    carregar_env()                        # configuração única: o loop lê as chaves sozinho
    from . import configuracao as cfg
    try:                                  # e as que você cadastrou no painel, do cofre do sistema (Keychain)
        from .cofre import Cadastro
        from .state import Store
        Cadastro(Store(os.path.join(args.data, "circulo.db")), cfg.ENV_FILE).carregar_no_ambiente()
    except Exception:  # noqa: BLE001 — sem cofre, segue com o arquivo
        pass
    from .loop import Circle

    if args.cmd == "verificar":
        from .verificacao import main as verificar_main
        raise SystemExit(verificar_main())
    if args.cmd == "configurar":
        path = cfg.configurar()
        print(f"Arquivo criado: {path}\nAbra, preencha as chaves e salve. Depois: circulo diagnostico && circulo instalar")
        return
    if args.cmd == "init":
        from . import kit
        r = kit.init(args.pasta, pedido=args.pedido, nome=args.nome, escrever_ci=not args.sem_ci)
        if args.json:
            print(kit.resumo_json(r))
        else:
            k = r["kit"]
            print(f"Kit: {k['nome']} ({k['repo'] or 'sem remoto'}) em {k['pasta']}")
            print(f"  constituição: {', '.join(k['protegidos'])}\n  testes: {k['testes']}\n  checks do gate: {', '.join(k['checks'])}")
            for a in r["arquivos"]:
                print(f"  escrito no repositório: {a}")
            for a in k["avisos"]:
                print(f"  aviso: {a}")
            print("Próximos passos:\n  " + "\n  ".join(r["proximos"]))
        return
    if args.cmd == "diagnostico":
        pecas = cfg.diagnostico(testar_conexoes=args.testar)
        print(cfg.resumo_json(pecas) if args.json else cfg.imprimir(pecas))
        return
    if args.cmd == "instalar":
        dest, feitos = cfg.instalar(os.path.abspath(args.data), args.porta, aplicar=not args.so_arquivo)
        print(f"Serviço: {dest}")
        for c in feitos:
            print(f"  $ {c}")
        print(f"O loop sobe sozinho com o computador e se reinicia se cair. Painel: http://127.0.0.1:{args.porta}")
        return
    if args.cmd == "desinstalar":
        arq = cfg.desinstalar()
        print(f"Serviço desligado. Arquivo guardado em {arq}" if arq else "Nenhum serviço instalado.")
        return

    if args.cmd == "painel":
        from .painel import serve
        print(f"painel em http://127.0.0.1:{args.porta}")
        serve(os.path.join(args.data, "circulo.db"), args.porta)
        return
    if args.cmd == "demo":
        from .demo import run_demo
        run_demo(args.data + "-demo", args.porta)
        return

    if args.cmd == "restaurar":
        from .guardrails import restore
        safety = restore(os.path.join(args.data, "circulo.db"), args.arquivo)
        print(f"restaurado. O banco anterior ficou guardado em {safety}")
        return

    c = Circle(args.data)
    if args.cmd == "dev":
        if c.self_dev is None:
            print("Developer indisponível: defina CIRCULO_REPO_DIR (clone do repo) e instale o Claude Code (comando `claude`).")
            return
        print(c.self_dev.run_once(args.item))
        return
    if args.cmd == "snapshot":
        from .guardrails import snapshot
        print(snapshot(c.store, c.data_dir, "manual"))
        return
    if args.cmd == "run":
        # Ao subir (inclusive depois de você salvar as chaves), o loop testa as conexões de verdade e registra
        # o resultado: chave errada aparece no painel na hora, não no primeiro ciclo que precisar dela.
        testar = os.environ.get("CIRCULO_TESTAR_AO_SUBIR", "1") == "1"
        cfg.registrar(c.store, cfg.diagnostico(testar_conexoes=testar))
        if args.painel:
            from . import controle
            if controle.separado():
                c.controle = controle.Supervisor(c.data_dir, args.porta, c.store, c.ctx.reply)
                c.controle.iniciar()
                print(f"plano de controle (painel + SRE) em processo próprio: http://127.0.0.1:{args.porta}")
            else:
                from .painel import serve
                serve(c.store.path, args.porta, background=True)
                print(f"painel em http://127.0.0.1:{args.porta}")
        from . import metrics
        porta = metrics.porta_configurada(args.metricas_porta)
        if porta:
            endereco = os.environ.get("CIRCULO_METRICS_ADDR", "127.0.0.1")
            try:
                c.metricas.servir(porta, endereco)
                print(f"métricas em http://{endereco}:{porta}/metrics")
            except (RuntimeError, OSError) as exc:   # sem o pacote ou porta ocupada: o loop roda sem /metrics
                print(f"métricas desligadas: {exc}")
        print(f"círculo rodando (decisor: {c.ctx.dl.jev.source}). Ctrl+C para parar; o estado fica salvo.")
        c.run_forever()
    elif args.cmd == "tick":
        for _ in range(args.n):
            r = c.tick()
            print(json.dumps({"tick": r.tick, "pausado": r.paused, "evento": r.handled_event, "idle": r.idle_task,
                              "evolucoes": r.evolutions, "shadow": r.shadow, "erros": r.errors}, ensure_ascii=False))
    elif args.cmd == "add":
        print(f"enfileirado #{c.submit(' '.join(args.texto))}")
    elif args.cmd == "status":
        print(json.dumps(c.status(), ensure_ascii=False, indent=2))
    elif args.cmd == "resumo":
        print(c.write_summary().read_text(encoding="utf-8"))
    elif args.cmd == "respostas":
        rows = c.store.q("SELECT id, message FROM alerts WHERE kind='resposta' AND delivered=0 ORDER BY id")
        for r in rows:
            print(r["message"])
        c.store.x("UPDATE alerts SET delivered=1 WHERE kind='resposta' AND delivered=0")


if __name__ == "__main__":
    main()
