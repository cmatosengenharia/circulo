"""Saída do agente classificada por regra: a falha de configuração (lições #18, #42 e #69, PRs #73/#75/#85 abandonados)
abre o disjuntor na 1ª ocorrência; o Developer não tenta de novo até a configuração mudar."""
from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, git, repo  # noqa: F401 — fixture do repositório

from circulo import falhas
from circulo.reparo import TETO_RAIZ

# caudas reais gravadas nas lições #18 e #42 (as mesmas de tests/test_causa_do_agente.py)
CAUDA_18 = ('s","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,'
            '"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0')
CAUDA_42 = ('d_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,'
            '"unset":0},"started_in_background":0}')
# a linha `result` sem causa nomeada, como a lição #69 reincidiu: só o metadado do SDK, nada que explique a falha
SAIDA_69 = ('{"type":"result","subtype":"success","is_error":true,"num_turns":1,"result":"","permission_denials":[],'
            '"terminal_reason":"completed","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required",'
            '"subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0}}')
# a saída inteira do PR #73 (commit 0db082e): o mesmo metadado, mas a causa é o máximo de passos (lição #59)
MAX_TURNS = ('{"type":"result","subtype":"error_max_turns","is_error":true,"num_turns":31,"permission_denials":[],'
             '"fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,'
             '"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0}}')
TRANSITORIA = ('{"type":"result","subtype":"success","is_error":true,"result":"API Error: 529 {\\"type\\":\\"error\\",'
               '\\"error\\":{\\"type\\":\\"overloaded_error\\",\\"message\\":\\"Overloaded\\"}}","terminal_reason":"api_error",'
               '"fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0}}')


def test_licao_18_42_69_sdk_opt_in_required_e_configuracao():
    for saida in (CAUDA_18, CAUDA_42, SAIDA_69):
        assert falhas.classificar_saida_agente(saida) == falhas.CONFIGURACAO, saida


def test_metadado_do_sdk_nao_vence_a_causa_nomeada_nem_a_falha_transitoria():
    assert falhas.classificar_saida_agente(TRANSITORIA) == falhas.TRANSITORIA
    assert falhas.classificar_saida_agente("Error: ECONNRESET while streaming") == falhas.TRANSITORIA
    assert falhas.classificar_saida_agente(MAX_TURNS) == falhas.FALHA          # vai para o fatiador, não para o disjuntor
    assert falhas.classificar_saida_agente('"subagent_stats":{"spawned":2}, sdk_opt_in_required') == falhas.FALHA
    assert falhas.classificar_saida_agente("") == falhas.FALHA


def test_impressao_digital_muda_com_as_chaves_e_nao_guarda_o_valor():
    a = falhas.digital_configuracao({"ANTHROPIC_API_KEY": "sk-1"})
    assert a == falhas.digital_configuracao({"ANTHROPIC_API_KEY": "sk-1", "OUTRA": "x"})
    assert a != falhas.digital_configuracao({"ANTHROPIC_API_KEY": "sk-2"}) and "sk-1" not in a


class ConfigAgent(ZipAgent):
    """O agente cai sempre com a saída de configuração da lição #69."""

    def run(self, task, workdir):
        self.tasks.append(task)
        return {"ok": False, "tokens": 0, "log": SAIDA_69}


def test_licao_69_configuracao_abre_o_disjuntor_na_1a_e_so_fecha_quando_a_configuracao_muda(circle, repo, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-velha")
    erro_recorrente(circle)
    agent = ConfigAgent()
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert r.status == falhas.PAUSA and len(agent.tasks) == 1
    assert (circle.store.get(TETO_RAIZ) or {})[falhas.CONFIGURACAO]["digital"] == falhas.digital_configuracao()
    for _ in range(3):                                   # 0 novas tentativas, nenhum PR, nenhuma lição nova
        assert dev.run_once().status == falhas.PAUSA
    assert len(agent.tasks) == 1 and gh.prs == []
    assert circle.store.one("SELECT COUNT(*) n FROM licoes WHERE ponto='developer:agente'")["n"] == 1
    for b in git(repo, "branch", "--list", "circulo/*", "--format=%(refname:short)").splitlines():
        git(repo, "branch", "-D", b)        # o nome da branch leva o segundo: dois giros no mesmo segundo colidem
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-nova")   # `circulo configurar` mudou a chave: o disjuntor fecha
    dev.run_once()
    assert len(agent.tasks) == 2
