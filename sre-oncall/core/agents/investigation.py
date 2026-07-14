import re
import json
from typing import Dict, Any, List
from ..llm_client import LLMClient

REACT_PROMPT = """You are an SRE investigation engineer. Follow the investigation plan step by step using the ReAct (Reasoning + Acting) pattern.

## Incident Summary
{incident_summary}

## Investigation Plan
{plan}

## Available Tools
{tools}

## Interaction History
{history}

## Instructions
For each step, respond with:
Thought: <your reasoning about what to investigate next and why>
Action: <tool_name>[<query>]

When you have identified the root cause, respond with:
Thought: <final reasoning consolidating all evidence>
Action: Finish[<root cause conclusion>]

Now respond:"""


class InvestigationAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(
        self,
        plan: List[Dict[str, str]],
        incident: Dict[str, Any],
        tools: Dict[str, Any],
        max_steps: int = 12,
    ) -> Dict[str, Any]:
        history: List[str] = []
        called_actions: set = set()
        findings: Dict[str, Any] = {
            "evidence": [],
            "root_cause": "",
            "runbook_steps": [],
        }

        incident_summary = json.dumps(
            {
                "id": incident.get("incident_id", ""),
                "service": incident.get("service", ""),
                "severity": incident.get("severity", ""),
                "title": incident.get("title", ""),
                "description": incident.get("description", ""),
            },
            ensure_ascii=False,
            indent=2,
        )

        tools_desc = "\n".join(
            f"- {t.name}: {t.description}" for t in tools.values()
        )
        plan_text = "\n".join(
            f"{i+1}. [{s['tool']}] {s['query']} — {s['reason']}"
            for i, s in enumerate(plan)
        )

        for step_num in range(1, max_steps + 1):
            prompt = REACT_PROMPT.format(
                incident_summary=incident_summary,
                plan=plan_text,
                tools=tools_desc,
                history="\n".join(history) if history else "(none yet)",
            )
            messages = [{"role": "user", "content": prompt}]

            response = self.llm.think(messages=messages, temperature=0.1)
            if not response:
                break

            thought, action = self._parse_react(response)

            if action.lower().startswith("finish"):
                conclusion = self._extract_action_input(action)
                findings["root_cause"] = conclusion
                break

            tool_name, query = self._parse_tool_call(action)
            if not tool_name:
                history.append(f"Action: {action} (unparseable)")
                continue

            action_key = f"{tool_name}[{query}]"
            if action_key in called_actions:
                history.append(
                    f"Action: {action} (skipped — already executed {action_key})"
                )
                continue
            called_actions.add(action_key)

            tool = tools.get(tool_name)
            if not tool:
                observation = f"Tool '{tool_name}' not found. Available: {list(tools.keys())}"
            else:
                observation = tool.run(query)

            history.append(f"Thought: {thought}")
            history.append(f"Action: {action}")
            history.append(f"Observation: {observation}")

            if tool_name in ("log_search", "metric_query") and "No " not in observation[:10]:
                findings["evidence"].append(
                    {"tool": tool_name, "query": query, "result": observation}
                )
            elif tool_name == "runbook_lookup":
                findings["runbook_steps"].append(observation)

        return findings

    def _parse_react(self, text: str):
        thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", text, re.DOTALL)
        action_match = re.search(r"Action:\s*(.*?)$", text, re.MULTILINE)
        thought = thought_match.group(1).strip() if thought_match else ""
        action = action_match.group(1).strip() if action_match else ""
        return thought, action

    def _parse_tool_call(self, action: str):
        match = re.match(r"(\w+)\[(.*)\]", action, re.DOTALL)
        if match:
            return match.group(1), match.group(2).strip()
        return None, None

    def _extract_action_input(self, action: str):
        match = re.search(r"\[(.*)\]", action, re.DOTALL)
        return match.group(1).strip() if match else action[len("Finish"):].strip()
