"""GateGuard (ADR 0001, ECC-5): no worktree do Developer, a primeira edição de um arquivo existente só passa depois que
o transcript mostra quem o importa (um grep pelo nome do módulo)."""
import io
import json
import subprocess
import sys
from pathlib import Path

from circulo import gateguard

RAIZ = Path(__file__).resolve().parents[1]


def _transcript(tmp_path, *ferramentas):
    linhas = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": i}]}}
              for n, i in ferramentas]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in linhas))
    return str(p)


def _decidir(tmp_path, transcript, arquivo="circulo/loop.py", wt=".circulo-wt-7", tool="Edit"):
    cwd = tmp_path / wt
    (cwd / "circulo").mkdir(parents=True, exist_ok=True)
    (cwd / "circulo" / "loop.py").write_text("x = 1\n")
    return gateguard.decidir({"tool_name": tool, "tool_input": {"file_path": str(cwd / arquivo)},
                              "transcript_path": transcript, "cwd": str(cwd)})


def test_primeira_edicao_sem_grep_dos_importadores_e_negada(tmp_path):
    t = _transcript(tmp_path, ("Read", {"file_path": "circulo/loop.py"}))
    motivo = _decidir(tmp_path, t)
    assert motivo and "loop" in motivo and "grep" in motivo


def test_grep_do_modulo_no_transcript_libera(tmp_path):
    assert _decidir(tmp_path, _transcript(tmp_path, ("Grep", {"pattern": "from .loop import|circulo.loop"}))) is None
    assert _decidir(tmp_path, _transcript(tmp_path, ("Bash", {"command": "grep -rn 'import loop' circulo"}))) is None


def test_arquivo_novo_e_sessao_fora_do_worktree_passam(tmp_path):
    t = _transcript(tmp_path)
    assert _decidir(tmp_path, t, arquivo="tests/test_novo.py", tool="Write") is None
    assert _decidir(tmp_path, t, wt="repo") is None


def test_hook_nega_pelo_protocolo_do_claude_code(tmp_path, monkeypatch, capsys):
    cwd = tmp_path / ".circulo-wt-7"
    cwd.mkdir()
    (cwd / "a.py").write_text("")
    entrada = {"tool_name": "Edit", "tool_input": {"file_path": str(cwd / "a.py")}, "cwd": str(cwd),
               "transcript_path": _transcript(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entrada)))
    gateguard.main()
    saida = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert saida["hookEventName"] == "PreToolUse" and saida["permissionDecision"] == "deny"


def test_modulo_roda_como_hook_e_entrada_vazia_libera():
    r = subprocess.run([sys.executable, "-m", "circulo.gateguard"], cwd=RAIZ, input="{}", capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""
