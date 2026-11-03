"""Skills reutilizadas: catálogo de skills prontas em repositórios públicos, instalação por PR em `.claude/skills/`
e a escolha, pelo Jev, de qual skill cada tarefa do Developer deve usar.

Cássio (31/10): "pegar vários repos que já possuem skills preparadas (frontend profissional, vídeo para Instagram e
YouTube, economia de tokens, arquitetura, segurança) e implementar no ecossistema do loop". O Developer é o Claude
Code em modo headless: ele carrega as skills que estiverem em `.claude/skills/<nome>/SKILL.md` do repositório em que
trabalha. Então "implementar" é: (1) item de origem `referencia` por skill do catálogo, para o Developer copiar a
pasta da skill (SKILL.md e scripts) por PR, respeitando a licença; (2) a cada tarefa, o Jev escolhe entre as skills
instaladas as que servem (`skills_para_tarefa`, regra local: sobreposição de palavras entre a tarefa e a descrição da
skill) e o prompt da tarefa diz quais usar. O catálogo é dado (kv `skills_catalogo` sobrescreve); nada aqui chama LLM.

Fontes do catálogo (31/10): anthropics/skills (Apache-2.0; os 4 de documentos são source-available), obra/superpowers,
trailofbits/skills, remotion-dev/skills, google-labs-code, microsoft, cloudflare, vercel-labs, testmu-ai; expo/skills (MIT,
área `mobile`, ADR 0006: pedidas só quando um produto pendente fala de app, iOS, Android ou Expo). A licença de
cada uma é conferida pelo Developer no PR (o item diz isso); "desconhecida" significa que o catálogo não a afirma.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .decision import Decision, Question
from .memoria import termos

PASTA = Path(".claude") / "skills"
MAX_POR_TAREFA = 2
MAX_ITENS_POR_DIA = 3
KV_PEDIDOS = "skills_pedidas"       # {nome: {"item", "em"}}
PERGUNTA = "skills_para_tarefa"

# (nome, repositório, caminho dentro do repositório, área, para que serve, licença conhecida)
CATALOGO = (
    # documentos e artefatos
    ("docx", "https://github.com/anthropics/skills", "skills/docx", "documentos", "criar e editar Word (.docx)", "source-available"),
    ("pdf", "https://github.com/anthropics/skills", "skills/pdf", "documentos", "ler, criar, preencher e unir PDF", "source-available"),
    ("pptx", "https://github.com/anthropics/skills", "skills/pptx", "documentos", "apresentações PowerPoint", "source-available"),
    ("xlsx", "https://github.com/anthropics/skills", "skills/xlsx", "documentos", "planilhas com fórmulas", "source-available"),
    # frontend e design
    ("frontend-design", "https://github.com/anthropics/skills", "skills/frontend-design", "frontend", "interfaces com direção visual, tipografia e layout fora do padrão genérico", "Apache-2.0"),
    ("web-artifacts-builder", "https://github.com/anthropics/skills", "skills/web-artifacts-builder", "frontend", "páginas e artefatos web completos (React, Tailwind, shadcn)", "Apache-2.0"),
    ("canvas-design", "https://github.com/anthropics/skills", "skills/canvas-design", "frontend", "mockups, pôsteres e diagramas em canvas", "Apache-2.0"),
    ("theme-factory", "https://github.com/anthropics/skills", "skills/theme-factory", "frontend", "temas e paletas consistentes", "Apache-2.0"),
    ("shadcn-ui", "https://github.com/google-labs-code/stitch-skills", "plugins/stitch-build/skills/shadcn-ui", "frontend", "componentes shadcn/ui bem usados", "Apache-2.0"),
    ("frontend-design-review", "https://github.com/microsoft/skills", ".github/skills/frontend-design-review", "frontend", "revisão de design de frontend", "MIT"),
    ("web-perf", "https://github.com/cloudflare/skills", "skills/web-perf", "frontend", "auditoria de Core Web Vitals", "desconhecida"),
    # testes e qualidade
    ("webapp-testing", "https://github.com/anthropics/skills", "skills/webapp-testing", "testes", "testes de interface com Playwright", "Apache-2.0"),
    ("test-driven-development", "https://github.com/obra/superpowers", "skills/test-driven-development", "testes", "RED-GREEN-REFACTOR disciplinado", "desconhecida"),
    ("pytest-skill", "https://github.com/LambdaTest/agent-skills", "pytest-skill", "testes", "pytest: fixtures, parametrização, isolamento", "MIT"),
    ("playwright-skill", "https://github.com/testmu-ai/skills", "skills/playwright-skill", "testes", "Playwright de ponta a ponta", "desconhecida"),
    # arquitetura e método
    ("brainstorming", "https://github.com/obra/superpowers", "skills/brainstorming", "arquitetura", "decisões de arquitetura e API antes de codar", "desconhecida"),
    ("writing-plans", "https://github.com/obra/superpowers", "skills/writing-plans", "arquitetura", "plano de implementação por etapas verificáveis", "desconhecida"),
    ("systematic-debugging", "https://github.com/obra/superpowers", "skills/systematic-debugging", "arquitetura", "depuração por causa raiz, não por sintoma", "desconhecida"),
    ("verification-before-completion", "https://github.com/obra/superpowers", "skills/verification-before-completion", "arquitetura", "provar antes de declarar pronto", "desconhecida"),
    ("using-git-worktrees", "https://github.com/obra/superpowers", "skills/using-git-worktrees", "arquitetura", "trabalho isolado por worktree (contexto menor)", "desconhecida"),
    ("subagent-driven-development", "https://github.com/obra/superpowers", "skills/subagent-driven-development", "contexto", "subagentes com contexto próprio: economia de tokens no agente principal", "desconhecida"),
    ("cloud-solution-architect", "https://github.com/microsoft/skills", "skills/cloud-solution-architect", "arquitetura", "arquitetura de soluções em nuvem", "desconhecida"),
    ("next-best-practices", "https://github.com/vercel-labs/skills", "skills/next-best-practices", "arquitetura", "Next.js como a Vercel recomenda", "desconhecida"),
    ("postgres-best-practices", "https://github.com/supabase/agent-skills", "skills/supabase-postgres-best-practices", "arquitetura", "Postgres: esquema, índices, consultas", "MIT"),
    # segurança
    ("differential-review", "https://github.com/trailofbits/skills", "skills/differential-review", "seguranca", "revisão de segurança de PR e diff, com relatório", "desconhecida"),
    ("insecure-defaults", "https://github.com/trailofbits/skills", "skills/insecure-defaults", "seguranca", "detecta padrões fail-open: segredo fraco, configuração permissiva", "desconhecida"),
    ("semgrep", "https://github.com/trailofbits/skills", "skills/semgrep", "seguranca", "varredura Semgrep com triagem", "desconhecida"),
    ("supply-chain-risk-auditor", "https://github.com/trailofbits/skills", "skills/supply-chain-risk-auditor", "seguranca", "risco de cadeia de dependências", "desconhecida"),
    ("sharp-edges", "https://github.com/trailofbits/skills", "skills/sharp-edges", "seguranca", "uso errado de API e padrões perigosos", "desconhecida"),
    ("agentic-actions-auditor", "https://github.com/trailofbits/skills", "skills/agentic-actions-auditor", "seguranca", "audita workflows do GitHub Actions que chamam agentes de IA", "desconhecida"),
    ("security-audit-skill", "https://github.com/cloudflare/skills", "skills/security-audit-skill", "seguranca", "auditoria de segurança de aplicação", "desconhecida"),
    # vídeo e mídia
    ("remotion-best-practices", "https://github.com/remotion-dev/skills", "remotion-best-practices", "video", "vídeo programático em React: guia geral", "desconhecida"),
    ("remotion-create", "https://github.com/remotion-dev/skills", "remotion-create", "video", "criar projeto e composição de vídeo", "desconhecida"),
    ("remotion-captions", "https://github.com/remotion-dev/skills", "remotion-captions", "video", "legendas e subtítulos (reels, shorts)", "desconhecida"),
    ("remotion-render", "https://github.com/remotion-dev/skills", "remotion-render", "video", "renderizar vídeo ou still", "desconhecida"),
    ("slack-gif-creator", "https://github.com/anthropics/skills", "skills/slack-gif-creator", "video", "GIFs animados curtos", "Apache-2.0"),
    # app móvel (EXPO-1, ADR 0006): só pedidas quando um produto pendente fala de app, iOS, Android ou Expo
    ("expo-overview", "https://github.com/expo/skills", "skills/expo-overview", "mobile", "app Expo (React Native): visão geral, iOS e Android", "MIT"),
    ("expo-router", "https://github.com/expo/skills", "skills/expo-router", "mobile", "navegação por arquivos em app Expo", "MIT"),
    ("expo-ui", "https://github.com/expo/skills", "skills/expo-ui", "mobile", "componentes nativos de iOS e Android em app Expo", "MIT"),
    ("expo-data-fetching", "https://github.com/expo/skills", "skills/expo-data-fetching", "mobile", "busca de dados e cache em app Expo", "MIT"),
    ("expo-web-to-native", "https://github.com/expo/skills", "skills/expo-web-to-native", "mobile", "levar telas web para app Expo nativo", "MIT"),
    # MCP e meta
    ("mcp-builder", "https://github.com/anthropics/skills", "skills/mcp-builder", "mcp", "construir servidores MCP", "Apache-2.0"),
    ("skill-creator", "https://github.com/anthropics/skills", "skills/skill-creator", "meta", "criar e avaliar skills novas", "Apache-2.0"),
)
AREAS = {"documentos": "documentos", "frontend": "frontend", "testes": "testes", "arquitetura": "arquitetura", "contexto": "contexto",
         "seguranca": "segurança", "video": "vídeo", "mobile": "app móvel", "mcp": "MCP", "meta": "meta"}
_FRONT = re.compile(r"(?i)\.html|painel|tela|css|frontend|console|card|layout|tema\.py")
_MOBILE = re.compile(r"(?i)\b(app|ios|android|expo)\b")
REGRA_APP = ("Regra do app da esteira: strangler fig — começar pela casca nativa (Expo) e trocar as telas web por nativas "
             "uma a uma, nunca reescrever tudo de uma vez.")


def catalogo(store) -> list[dict]:
    lista = store.get("skills_catalogo") or [dict(zip(("nome", "repo", "caminho", "area", "para", "licenca"), c, strict=True)) for c in CATALOGO]
    return [c for c in lista if c.get("nome") and c.get("repo")]


def instaladas(repo_dir: Path | str) -> list[dict]:
    """As skills presentes em `.claude/skills/*/SKILL.md` do repositório: nome e descrição do cabeçalho."""
    out = []
    pasta = Path(repo_dir) / PASTA
    if not pasta.is_dir():
        return out
    for arq in sorted(pasta.glob("*/SKILL.md")):
        try:
            cab = arq.read_text(encoding="utf-8")[:2000]
        except (OSError, UnicodeDecodeError):
            continue
        m = re.search(r"^description:[ \t]*(.*)$", cab, re.M)
        desc = m.group(1).strip().strip('"') if m else ""
        if m and desc[:1] in ("", ">", "|"):                                # bloco YAML (dobrado ou na linha seguinte): as linhas indentadas que seguem
            desc = " ".join(lin.strip() for lin in re.findall(r"^[ \t]+(.+)$", re.match(r"(?:[ \t]+.*\n?)*", cab[m.end() + 1:]).group(0), re.M))
        out.append({"nome": arq.parent.name, "descricao": desc[:300]})
    return out


def pedir_instalacao(store, repo_dir: Path | str, agora: float | None = None, maximo: int = MAX_ITENS_POR_DIA) -> list[int]:
    """Item de origem `referencia` por skill do catálogo ainda não instalada nem pedida, até `maximo` por passagem (1×/dia)."""
    agora = agora or time.time()
    pedidas = store.get(KV_PEDIDOS) or {}
    ja = {s["nome"] for s in instaladas(repo_dir)} | set(pedidas)
    produto_mobile = any(_MOBILE.search(f"{r['titulo']}\n{r['detalhe'] or ''}") for r in store.q(
        "SELECT titulo, detalhe FROM roadmap WHERE status IN ('pendente','em_andamento') AND origem!='referencia'"))
    ids = []
    for c in catalogo(store):
        if c["nome"] in ja or (c.get("area") == "mobile" and not produto_mobile):
            continue
        titulo = f"Instalar a skill {c['nome']} ({AREAS.get(c['area'], c['area'])}) em .claude/skills a partir de {c['repo'].split('github.com/')[-1]}"
        detalhe = (f"Copiar a pasta `{c['caminho']}` de {c['repo']} para `.claude/skills/{c['nome']}/` (SKILL.md e os scripts que ele cita), "
                   f"sem alterar o conteúdo. Para que serve: {c['para']}. Licença conhecida: {c['licenca']} — confira a licença no repositório; "
                   "source-available ou sem licença: traga só o SKILL.md com a atribuição e a URL, e registre no PR. "
                   "Sucesso: `circulo/skills.instaladas(repo)` lista a skill com a descrição do cabeçalho; nenhum teste quebra.")
        ordem = (store.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
        iid = store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (titulo[:160], detalhe, "referencia", "pendente", f"skill do catálogo: {c['repo']}/{c['caminho']}", ordem,
                       f"catálogo de skills (31/10); fonte: {c['repo']}", agora, agora))
        pedidas[c["nome"]] = {"item": iid, "em": agora}
        ids.append(iid)
        if len(ids) >= maximo:
            break
    store.set(KV_PEDIDOS, pedidas)
    return ids


def regra(jev, qid: str, q: Question, state) -> Decision:
    """Regra local: a skill cuja descrição mais divide palavras com a tarefa; tela/painel/html puxa a de frontend;
    skill de app móvel só entra quando a tarefa fala de app, iOS, Android ou Expo (EXPO-1)."""
    tarefa = set(termos(str(state.get("tarefa", "")), 40))
    front = bool(_FRONT.search(str(state.get("tarefa", ""))))
    mobile = bool(_MOBILE.search(str(state.get("tarefa", ""))))
    pontos = {}
    for op, desc in (q.criteria or {}).items():
        if op == "nenhuma":
            continue
        p = len(tarefa & set(termos(desc, 40)))
        if front and re.search(r"(?i)frontend|design|interface|web", desc):
            p += 2
        if _MOBILE.search(desc):
            p = p + 2 if mobile else 0
        pontos[op] = p
    melhor = max(pontos.values(), default=0)
    if melhor <= 0:
        return Decision(qid, "choice", "nenhuma", 0.6, jev.source)
    return Decision(qid, "choice", max(pontos, key=pontos.get), 0.6, jev.source)


def para_tarefa(dl, item: dict, repo_dir: Path | str) -> list[dict]:
    """As skills instaladas que o Jev escolhe para esta tarefa (até MAX_POR_TAREFA; a regra local escolhe uma)."""
    from .escudo import auditar
    fora = set(auditar(repo_dir)["bloqueadas"])                      # achado crítico no SKILL.md: nunca entra no prompt (ECC-1)
    inst = [s for s in instaladas(repo_dir) if s["nome"] not in fora]
    if not inst or dl is None:
        return []
    opcoes = {s["nome"]: f"{s['nome']}: {s['descricao']}" for s in inst}
    opcoes["nenhuma"] = "nenhuma skill serve para esta tarefa"
    tarefa = f"{item.get('titulo', '')}\n{str(item.get('detalhe', ''))[:600]}"
    d = dl.ask(PERGUNTA, Question("choice", "Which installed skill should the coding agent use for this `tarefa`? Pick the one whose "
                                            "description matches the work; `nenhuma` when none fits.", opcoes), {"tarefa": tarefa, "skills": opcoes})
    nome = str(d.value)
    escolhidas = [s for s in inst if s["nome"] == nome] if nome in opcoes and nome != "nenhuma" else []
    return escolhidas[:MAX_POR_TAREFA]


def texto_para_prompt(escolhidas: list[dict]) -> str:
    if not escolhidas:
        return ""
    linhas = "\n".join(f"- /{s['nome']}: {s['descricao']}" for s in escolhidas)
    if any(_MOBILE.search(s["descricao"]) for s in escolhidas):
        linhas += f"\n{REGRA_APP}"
    return f"\nSkills instaladas em .claude/skills que servem a esta tarefa — leia o SKILL.md e siga-o:\n{linhas}\n"
