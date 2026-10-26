"""Pauta da daily às 8h, por assunto: o que fiz ontem (das notas), o que farei hoje (pendências) e o que me bloqueia."""
import os
import time

from circulo import daily

HOJE_8H = time.mktime((2026, 10, 26, 8, 5, 0, 0, 0, -1))
ONTEM = time.mktime((2026, 10, 25, 15, 0, 0, 0, 0, -1))
ANTEONTEM = time.mktime((2026, 10, 24, 15, 0, 0, 0, 0, -1))


def _nota(caminho, texto, mtime):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")
    os.utime(caminho, (mtime, mtime))


def _notas(tmp_path):
    n = tmp_path / "notas"
    _nota(n / "financas" / "a.md", "# Revisei o orçamento de outubro\n- [x] conciliei o cartão\n- [ ] pagar o IPTU\n", ONTEM)
    _nota(n / "financas" / "velha.md", "fechei setembro\n- [ ] renegociar o seguro\n", ANTEONTEM)
    _nota(n / "solta.md", "---\nassunto: connect\n---\nmapeei os fluxos da Blip\nbloqueio: falta acesso à conta AWS\n", ONTEM)
    _nota(n / "2026-10-24-circulo.md", "---\nassunto: circulo\n---\nli o painel\n- [ ] revisar o PR do Developer\n", ONTEM)
    return n


def test_pauta_por_assunto_com_ontem_hoje_e_bloqueio(tmp_path):
    _notas(tmp_path)
    linhas = daily.pauta(tmp_path, HOJE_8H)
    assert linhas[0].startswith("Daily 26/10")
    por = {ln.split(" — ")[0]: ln for ln in linhas[1:]}
    assert set(por) == {"circulo", "connect", "financas"}
    fin = por["financas"]
    assert "ontem: Revisei o orçamento de outubro; conciliei o cartão" in fin
    assert "fechei setembro" not in fin                                   # nota de anteontem não é "ontem"
    assert "hoje: pagar o IPTU; renegociar o seguro" in fin               # pendência aberta vale de qualquer nota
    assert "bloqueia: falta acesso à conta AWS" in por["connect"] and "ontem: mapeei os fluxos da Blip" in por["connect"]
    assert "ontem" not in por["circulo"] and "hoje: revisar o PR do Developer" in por["circulo"]   # a data do nome manda
    assert len(linhas) <= daily.MAX_LINHAS


def test_no_maximo_dez_linhas(tmp_path):
    for i in range(15):
        _nota(tmp_path / "notas" / f"assunto{i:02d}" / "n.md", "- [ ] " + "x" * 400 + "\n", ONTEM)
    linhas = daily.pauta(tmp_path, HOJE_8H)
    assert len(linhas) == daily.MAX_LINHAS and linhas[-1].startswith("+")
    assert all(len(ln) <= daily.MAX_CHARS for ln in linhas)


def test_sai_uma_vez_por_dia_a_partir_das_8h_no_console_e_no_mac(circle, tmp_path):
    _notas(tmp_path)
    s, avisos, notas = circle.store, [], []

    def reply(m, k="resposta"):
        avisos.append((m, k))

    def notificar(t, x):
        notas.append((t, x))
        return True

    cedo = time.mktime((2026, 10, 26, 7, 59, 0, 0, 0, -1))
    assert daily.checar(s, tmp_path, reply, cedo, notificar) is None and not avisos
    assert daily.checar(s, tmp_path, reply, HOJE_8H, notificar)
    assert len(avisos) == 1 and avisos[0][0].startswith("Daily 26/10") and avisos[0][1] == "resposta"
    assert len(notas) == 1 and "financas" in notas[0][1]
    assert daily.checar(s, tmp_path, reply, HOJE_8H + 3600, notificar) is None and len(avisos) == 1
    assert daily.checar(s, tmp_path, reply, HOJE_8H + 86400, notificar) and len(avisos) == 2


def test_sem_pasta_de_notas_nao_fala(circle, tmp_path):
    avisos = []
    assert daily.checar(circle.store, tmp_path, lambda m, k="": avisos.append(m), HOJE_8H, lambda t, x: True) is None
    assert not avisos
