import json
from typing import Dict, Any
from ..llm_client import LLMClient

DRAFT_PROMPT = """You are an SRE post-mortem writer. Generate a structured RCA (Root Cause Analysis) report based on the incident and investigation findings.

## Incident Details
{incident_json}

## Investigation Findings
{findings_json}

Write a comprehensive post-mortem report in Markdown with these sections:
1. **Incident Summary** — what happened, when, impact
2. **Timeline** — key events in chronological order
3. **Root Cause** — the underlying cause, supported by evidence
4. **5-Whys Analysis** — drill down to the deepest cause
5. **Impact Assessment** — affected users, services, revenue
6. **Resolution** — steps taken or recommended
7. **Action Items** — concrete prevention measures with owners

Be factual, avoid blame, focus on systemic improvements."""

CRITIQUE_PROMPT = """You are a senior SRE reviewer. Critique the following post-mortem report against quality standards.

## Report to Review
{report}

Evaluate on these dimensions:
1. Completeness: Are all sections present and thorough?
2. Accuracy: Is the root cause well-supported by evidence?
3. Actionability: Are the action items specific and assignable?
4. Clarity: Is the language clear and free of jargon?
5. Blame-free: Does the report focus on systems, not people?

Return a JSON object:
```json
{{"score": <1-10>, "issues": ["issue1", "issue2"], "suggestions": ["suggestion1"]}}
```

If score >= 8, the report is acceptable. Otherwise, list the top issues to fix."""

REVISE_PROMPT = """Revise the following post-mortem report based on the reviewer feedback.

## Original Report
{report}

## Reviewer Feedback
Score: {score}/10
Issues: {issues}
Suggestions: {suggestions}

Produce a revised Markdown report that addresses all feedback. Output ONLY the report."""


class PostmortemAgent:
    def __init__(self, llm: LLMClient, max_revisions: int = 1):
        self.llm = llm
        self.max_revisions = max_revisions

    def run(self, incident: Dict[str, Any], findings: Dict[str, Any]) -> str:
        draft = self._draft(incident, findings)
        if not draft:
            return ""

        for i in range(self.max_revisions):
            critique = self._critique(draft)
            if not critique:
                break

            score = critique.get("score", 0)
            if score >= 8:
                break

            issues = critique.get("issues", [])
            suggestions = critique.get("suggestions", [])
            draft = self._revise(draft, score, issues, suggestions)
            if not draft:
                break

        return draft

    def _draft(self, incident: Dict, findings: Dict) -> str:
        prompt = DRAFT_PROMPT.format(
            incident_json=json.dumps(incident, ensure_ascii=False, indent=2),
            findings_json=json.dumps(findings, ensure_ascii=False, indent=2),
        )
        return self.llm.think(
            [{"role": "user", "content": prompt}], temperature=0.3
        )

    def _critique(self, report: str) -> Dict:
        prompt = CRITIQUE_PROMPT.format(report=report)
        response = self.llm.think(
            [{"role": "user", "content": prompt}], temperature=0.1
        )
        if not response:
            return {}

        import re
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
        try:
            return json.loads(match.group(1) if match else response)
        except (json.JSONDecodeError, AttributeError):
            return {}

    def _revise(self, report: str, score: int, issues: list, suggestions: list) -> str:
        prompt = REVISE_PROMPT.format(
            report=report,
            score=score,
            issues=json.dumps(issues, ensure_ascii=False),
            suggestions=json.dumps(suggestions, ensure_ascii=False),
        )
        return self.llm.think(
            [{"role": "user", "content": prompt}], temperature=0.3
        )
