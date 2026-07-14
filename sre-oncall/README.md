# SRE On-Call Agent

AI-powered SRE investigation assistant: triage → investigate → post-mortem.

## Architecture

```
alert JSON
    │
    ▼
┌─────────────────┐
│  TriageAgent    │  Plan-and-Solve: generates investigation plan
└────────┬────────┘
         │ plan (list of {tool, query, reason})
         ▼
┌─────────────────┐
│ Investigation   │  ReAct: thought → action → observation loop
│     Agent       │  Tools: log_search, metric_query, runbook_lookup
└────────┬────────┘
         │ findings (evidence, root_cause, runbook_steps)
         ▼
┌─────────────────┐
│ PostmortemAgent │  Reflection: draft → critique → revise
└────────┬────────┘
         │
         ▼
    Markdown RCA Report
```

## Quick Start

```bash
pip install openai python-dotenv pyyaml
cp .env.example .env    # add your LLM_API_KEY
python3 core/cli.py db_pool_exhaustion
```

## Project Structure

```
sre-oncall/
├── core/
│   ├── llm_client.py          # OpenAI-compatible LLM client
│   ├── tools/
│   │   ├── log_search.py      # Regex-based log search
│   │   ├── metric_query.py    # Metric value query
│   │   └── runbook.py         # YAML runbook lookup
│   ├── agents/
│   │   ├── triage.py          # Plan-and-Solve: alert → plan
│   │   ├── investigation.py   # ReAct: plan → findings
│   │   ├── postmortem.py      # Reflection: findings → report
│   │   └── pipeline.py        # Orchestrator: wires all 3 stages
│   └── cli.py                 # CLI entry point
├── data/
│   ├── incidents/             # 3 sample incident fixtures
│   ├── runbooks/              # Runbook procedures (YAML)
│   └── reports/               # Generated RCA reports
├── .cursor/skills/            # Cursor SKILL.md
└── .opencode/agents/          # opencode sub-agent definition
```

## Agent Paradigms Demonstrated

| Stage | Paradigm | Description |
|-------|----------|-------------|
| Triage | Plan-and-Solve | LLM generates ordered investigation steps from alert data |
| Investigation | ReAct | Thought → Action → Observation loop with tool execution |
| Postmortem | Reflection | Draft → Critique → Revise cycle with quality scoring |

## Key Design Decisions

- **No framework dependency**: All agents are pure Python classes with no base class inheritance
- **Prompt-based ReAct**: Uses regex parsing of Thought/Action instead of function calling
- **Tool deduplication**: `called_actions` set prevents redundant tool calls
- **Fallback plans**: Triage agent falls back to hardcoded plans when LLM parsing fails
- **Reflection quality gate**: Score threshold (≥8/10) determines whether revision is needed
