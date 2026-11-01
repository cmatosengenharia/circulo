"""Experimento universal: todo item do Planejador carrega hipótese, métrica, baseline, alvo, margem de não
inferioridade, janela e n_min de eventos; ao fim da janela o Vigia mede e grava o veredito.

- `Experimento.de` é a única forma de criar um: campo faltando, métrica fora de METRICAS (o Vigia não saberia medir),
  alvo que não melhora a métrica, margem ≤ 0 ou métrica em descanso levantam ExperimentoIncompleto (o Planejador recusa);
- o baseline é o medido no momento da gravação, quando a métrica tem medida (o número do LLM é só o palpite);
- a janela abre quando o item vira 'feito'; ao fim dela, com n ≥ n_min, `veredito` compara com o baseline usando a
  margem (Spotify Confidence: sem margem não há critério objetivo de "piorou"); sem amostra, `inconclusivo` e a janela
  estende uma vez; na segunda, `inconclusivo` é final;
- `piorou` numa métrica de GUARDA abre o item de reversão (Developer → PR → CI → revisor); fora da guarda o humano decide;
- `neutro` põe a métrica em descanso por DESCANSO_S: o Planejador não abre outro experimento sobre ela.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import norte
from .jardineiro import INDICADORES

H = 3600.0
DESCANSO = "experimentos_descanso"      # kv: {métrica: até quando descansa}
DESCANSO_S = 7 * 86400.0
INCONCLUSIVO = "inconclusivo"
METRICAS: dict[str, tuple[str, str, bool]] = {          # métrica → (fonte, sentido bom, é guarda)
    **{k: ("norte", sentido, k == "merge_sem_conserto") for k, _d, _m, sentido in norte.RESULTADOS},
    **{k: ("jardim", "menor", True) for k in INDICADORES},
}

class ExperimentoIncompleto(ValueError):
    """Item sem hipótese, métrica mensurável, margem ou janela: o Planejador não o grava."""


def _num(d: dict, k: str) -> float:
    try:
        return float(str(d[k]).replace(",", "."))
    except (KeyError, ValueError) as exc:
        raise ExperimentoIncompleto(f"experimento sem {k} numérico") from exc


@dataclass(frozen=True)
class Experimento:
    hipotese: str
    metrica: str
    baseline: float
    alvo: float
    margem: float
    janela_s: float
    n_min: int

    @classmethod
    def de(cls, d, store=None, agora: float | None = None) -> Experimento:
        if not isinstance(d, dict):
            raise ExperimentoIncompleto("item sem experimento (hipótese, métrica, baseline, alvo, margem, janela_h, n_min)")
        hipotese, metrica = str(d.get("hipotese") or "").strip(), str(d.get("metrica") or "").strip()
        if not hipotese:
            raise ExperimentoIncompleto("experimento sem hipótese")
        if metrica not in METRICAS:
            raise ExperimentoIncompleto(f"métrica {metrica!r} fora do catálogo que o Vigia mede ({', '.join(METRICAS)})")
        n_min = _num(d, "n_min")
        exp = cls(hipotese, metrica, _num(d, "baseline"), _num(d, "alvo"), _num(d, "margem"), _num(d, "janela_h") * H, int(n_min))
        if exp.margem <= 0 or exp.janela_s <= 0 or exp.n_min < 1 or exp.n_min != n_min:
            raise ExperimentoIncompleto("margem e janela precisam ser > 0 e n_min um inteiro ≥ 1")
        if veredito(METRICAS[metrica][1], exp.baseline, exp.alvo, 0) != "melhorou":
            raise ExperimentoIncompleto(f"alvo {exp.alvo:g} não melhora {metrica} ({METRICAS[metrica][1]} é melhor) "
                                        f"a partir de {exp.baseline:g}")
        if store is not None and float((store.get(DESCANSO) or {}).get(metrica, 0)) > (agora or time.time()):
            raise ExperimentoIncompleto(f"{metrica} está em descanso: o último experimento sobre ela deu neutro")
        return exp


def veredito(sentido: str, baseline: float, medido: float, margem: float) -> str:
    """melhorou/piorou só além da margem, no sentido bom da métrica; dentro dela, neutro."""
    ganho = (medido - baseline) * (1 if sentido == "maior" else -1)
    return "melhorou" if ganho > margem else "piorou" if ganho < -margem else "neutro"


def medir(store, metrica: str, desde: float, ate: float) -> tuple[float | None, int]:
    """(valor em `ate`, eventos em (desde, ate]): PRs mergeados para o Norte, medições do jardineiro para o jardim."""
    if METRICAS[metrica][0] == "norte":
        n = store.one("SELECT COUNT(*) n FROM prs WHERE status='mergeado' AND updated_at>? AND updated_at<=?", (desde, ate))["n"]
        return norte.medir(store, ate)[metrica]["valor"], int(n)
    hist = [h for h in (store.get("jardim") or {}).get("historico", []) if desde < float(h["em"]) <= ate]
    return (float(hist[-1]["total"][metrica]) if hist else None), len(hist)


def gravar(store, item_id: int, exp: Experimento, agora: float | None = None) -> int:
    agora = agora or time.time()
    medido, _n = medir(store, exp.metrica, 0, agora)
    return store.x("INSERT INTO experimentos(item_id,hipotese,metrica,guarda,baseline,alvo,margem_nao_inferioridade,janela_s,"
                   "n_min,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (item_id, exp.hipotese, exp.metrica, int(METRICAS[exp.metrica][2]),
                    exp.baseline if medido is None else medido, exp.alvo, exp.margem, exp.janela_s, exp.n_min, agora))


def _reverter(store, e: dict) -> int:
    from .roadmap import gravar_medido
    pr = store.one("SELECT number FROM prs WHERE item_id=? AND status='mergeado' ORDER BY updated_at DESC LIMIT 1", (e["item_id"],))
    alvo = f"o PR #{pr['number']}" if pr else f"a mudança do item #{e['item_id']}"
    medida = (f"{e['metrica']} (guarda) foi de {e['baseline']:g} para {e['medido']:g}, além da margem de não inferioridade "
              f"{e['margem_nao_inferioridade']:g}, com {e['n']} eventos na janela")
    return gravar_medido(store, "vigia", f"experimento:{e['id']}:reverter", f"Reverter item #{e['item_id']}: {e['metrica']} piorou",
                         f"Reverter {alvo} (git revert): {medida}.\nSucesso: {e['metrica']} volta a {e['baseline']:g} ± "
                         f"{e['margem_nao_inferioridade']:g}.", f"experimento #{e['id']}: {medida}")


def avaliar(store, reply=None, agora: float | None = None) -> list[dict]:
    """Uma passagem do Vigia: abre a janela dos itens feitos e decide as que venceram. Devolve os decididos agora."""
    agora = agora or time.time()
    store.x("UPDATE experimentos SET inicio=?, fim=?+janela_s WHERE inicio IS NULL AND item_id IN "
            "(SELECT id FROM roadmap WHERE status='feito')", (agora, agora))
    out = []
    for r in store.q("SELECT * FROM experimentos WHERE decidido_em IS NULL AND fim<=?", (agora,)):
        e = dict(r)
        medido, n = medir(store, e["metrica"], e["inicio"], e["fim"])
        e.update(medido=medido, n=n)
        if medido is None or n < e["n_min"]:
            e["veredito"] = INCONCLUSIVO
            if not e["estendida"]:
                store.x("UPDATE experimentos SET veredito=?, medido=?, n=?, estendida=1, fim=fim+janela_s WHERE id=?",
                        (INCONCLUSIVO, medido, n, e["id"]))
                continue
        else:
            e["veredito"] = veredito(METRICAS[e["metrica"]][1], e["baseline"], medido, e["margem_nao_inferioridade"])
        if e["veredito"] == "piorou" and e["guarda"]:
            e["reversao_item"] = _reverter(store, e)
        elif e["veredito"] == "neutro":
            store.set(DESCANSO, {**(store.get(DESCANSO) or {}), e["metrica"]: agora + DESCANSO_S})
        store.x("UPDATE experimentos SET veredito=?, medido=?, n=?, decidido_em=?, reversao_item=? WHERE id=?",
                (e["veredito"], medido, n, agora, e.get("reversao_item"), e["id"]))
        if callable(reply):
            acao = (f" Abri o item #{e['reversao_item']} de reversão." if e.get("reversao_item") else
                    " Fora da guarda: reverter fica com você." if e["veredito"] == "piorou" else "")
            reply(f"Vigia: experimento do item #{e['item_id']} ({e['metrica']}): {e['veredito']} "
                  f"({e['baseline']:g} → {medido if medido is None else f'{medido:g}'}, n={n}).{acao}", "roteiro")
        out.append(e)
    return out
