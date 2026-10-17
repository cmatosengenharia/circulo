"""circulo run [--painel] | painel | demo | tick [-n N] | add "38,90 ifood almoço" | status | resumo | respostas"""
from __future__ import annotations

import argparse
import json
import os

from .loop import Circle


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="circulo")
    ap.add_argument("--data", default=os.environ.get("CIRCULO_DATA", "data"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="loop infinito (pausa só por orçamento ou por você)")
    r.add_argument("--painel", action="store_true", help="serve o painel local junto com o loop")
    r.add_argument("--porta", type=int, default=8765)
    pn = sub.add_parser("painel", help="só o painel local (o loop roda em outro processo)")
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
    args = ap.parse_args(argv)

    if args.cmd == "painel":
        from .painel import serve
        print(f"painel em http://127.0.0.1:{args.porta}")
        serve(os.path.join(args.data, "circulo.db"), args.porta)
        return
    if args.cmd == "demo":
        from .demo import run_demo
        run_demo(args.data + "-demo", args.porta)
        return

    c = Circle(args.data)
    if args.cmd == "run":
        if args.painel:
            from .painel import serve
            serve(c.store.path, args.porta, background=True)
            print(f"painel em http://127.0.0.1:{args.porta}")
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
