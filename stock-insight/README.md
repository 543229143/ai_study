# Stock Insight Agent

AI-powered A-share stock analysis assistant with multi-paradigm analysis, memory system, and RAG knowledge base.

## Architecture

```
User Question
     │
     ▼
┌──────────────┐
│ FrameworkAgent│  Unified entry, selects paradigm
└──┬───┬───┬───┘
   │   │   │
   ▼   ▼   ▼
ReAct  PlanSolve  Reflection
Agent   Agent      Agent
   │      │          │
   └──────┴──────────┘
          │
          ▼
┌─────────────────────┐
│   ToolExecutor      │  18 tools across 5 categories
│ ┌─────────────────┐ │
│ │ Data Tools (5)  │ │  GetRealtimeQuote, GetHistoricalData,
│ │ Memory Tools(7) │ │  GetFinancialData, CalcIndicators, GetNews,
│ │ RAG Tools  (3)  │ │  Watchlist CRUD, History, Preferences,
│ │ Context    (3)  │ │  Knowledge Search, Document Import
│ └─────────────────┘ │
└─────────────────────┘
          │
          ▼
┌─────────────────────┐
│   Data Layer        │
│ akshare → 东方财富  │  Real-time market data via akshare
│ NumPy/Pandas → 指标 │  All technical indicators self-calculated
│ TF-IDF → 知识库    │  Built-in investment methodology KB
│ JSON → 记忆系统     │  Watchlist, history, preferences
└─────────────────────┘
```

## Quick Start

```bash
pip install openai python-dotenv akshare numpy pandas
cp .env.example .env    # add your LLM_API_KEY
python3 core/cli.py "分析贵州茅台" --mode react
```

## Three Analysis Paradigms

| Paradigm | Speed | Depth | How It Works |
|----------|-------|-------|-------------|
| **ReAct** | ~30s | Medium | Thought → Action → Observation loop, max 6 steps |
| **PlanSolve** | ~2min | Deep | Planner decomposes question → Executor runs each step |
| **Reflection** | ~3min | Deepest | Draft analysis → Critique → Revise, max 2 iterations |

## Project Structure

```
stock-insight/
├── core/
│   ├── llm_client.py          # OpenAI-compatible LLM client (streaming support)
│   ├── tools.py                # 5 data tools + ToolExecutor registry
│   ├── memory.py               # JSON-based persistent memory
│   ├── rag.py                  # TF-IDF investment knowledge base
│   ├── context_manager.py      # Context compression + token management
│   ├── agent.py                # Hand-written ReAct (no framework)
│   ├── plan_agent.py           # Hand-written PlanSolve (Planner + Executor)
│   ├── reflection_agent.py     # Hand-written Reflection (draft → critique → revise)
│   ├── framework_agent.py      # Unified entry (NO hello-agents dependency)
│   └── cli.py                  # CLI entry: react/plan/reflect modes
├── data/
│   ├── knowledge/              # Investment methodology documents
│   └── memory/                 # User watchlist, history, preferences
├── .cursor/skills/             # Cursor SKILL.md
└── .opencode/agents/           # opencode sub-agent definition
```

## Key Design Decisions

- **Zero framework dependency**: All agents are pure Python. No hello-agents, LangChain, or CrewAI.
- **Hand-written + unified entry duality**: Three hand-written implementations exist alongside `FrameworkStockAgent` that provides a clean unified interface — demonstrating both "understand the internals" and "provide a clean API"
- **Self-calculated indicators**: MA, MACD, RSI, Bollinger Bands all computed with NumPy/Pandas, not external libraries
- **2-gram Chinese tokenization**: TF-IDF knowledge base uses 1-2 character n-gram tokenization for Chinese text
- **Real market data**: All quotes, K-lines, financials come from akshare wrapping 东方财富/新浪/腾讯 APIs
