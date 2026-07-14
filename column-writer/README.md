# Column Writer — 多 Agent 专栏写作系统

## Architecture

```
User Topic
    │
    ▼
┌──────────────────┐
│  PlannerAgent   │  Plan-and-Solve: decomposes topic → column outline
│  (PlanSolve)    │  with file-based caching for each plan step
└──────┬───────────┘
       │ column_plan (ColumnPlan)
       ▼
┌──────────────────┐
│  WriterAgent    │  Choose mode:
│  ReAct /        │    ReAct → Thought→Action→Observation + web search
│  Reflection     │    Reflection → generate→critique→refine (auto)
└──────┬───────────┘
       │ content_data (dict with content, subsections)
       ▼
┌──────────────────┐
│ ReviewerAgent   │  Independent Review (ReAct mode only)
│  + RevisionAgent│  Score → if < threshold → revise or rewrite
└──────┬───────────┘
       │ revised content
       ▼
┌──────────────────┐
│ ColumnExporter  │  Export to .md files + REPORT.md
└──────────────────┘
```

## Quick Start

```bash
pip install openai python-dotenv pydantic pydantic-settings
# Optional: pip install tavily-python  (for web search)
cp .env.example .env    # add your LLM_API_KEY
python3 core/cli.py
```

## Project Structure

```
column-writer/
├── core/
│   ├── llm_client.py       # OpenAI-compatible LLM client
│   ├── agents.py            # 4 agent patterns (zero framework dep)
│   ├── orchestrator.py      # Workflow orchestration
│   ├── models.py            # Data classes: ContentNode, ColumnPlan, ReviewResult
│   ├── prompts.py           # All prompt templates (~400 lines)
│   ├── search_tools.py      # Direct Tavily/SerpAPI calls
│   ├── utils.py             # JSON extractor, ReAct parser
│   ├── exporter.py          # Export to files
│   ├── config.py            # Settings via pydantic-settings
│   └── cli.py               # CLI entry point
├── .cursor/skills/          # SKILL.md (方案A)
├── .opencode/agents/        # Agent definition (方案B)
├── INTERVIEW.md
└── README.md
```

## Agent Patterns Demonstrated

| Pattern | Agent | Lines | Description |
|---------|-------|-------|-------------|
| Plan-and-Solve | PlannerAgent | ~100 | Decompose topic → structured outline with caching |
| ReAct | WriterAgent | ~130 | Thought → Action → Observation → Finish loop |
| Reflection | ReflectionWriterAgent | ~80 | Draft → Self-critique → Refine (up to 2 iterations) |
| Independent Review | ReviewerAgent + RevisionAgent | ~80 | External LLM scores + RevisionAgent rewrites |

## Key Design Decisions

- **Zero framework dependency**: All agents are pure Python, no hello-agents/LangChain/CrewAI
- **ReAct with tool dispatch**: Web search tools available via dict-based registry
- **Cached Plan steps**: PlannerAgent caches MD5-hashed plan steps to files, avoids redundant LLM calls
- **Multi-strategy JSON extraction**: JSONExtractor handles Finish[], ```json, bare JSON, malformed content
- **Fallback column plan**: If LLM returns unparsable output, PlannerAgent falls back to a hardcoded single-topic plan
