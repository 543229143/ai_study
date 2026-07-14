import json
import os
import re
import hashlib
from typing import Dict, Any, Optional, List, Tuple

from .llm_client import LLMClient
from .search_tools import SearchClient
from .models import ColumnPlan, ContentNode, ContentLevel, ReviewResult
from .prompts import (
    PLANNER_PROMPT, WRITER_PROMPT, REVIEWER_PROMPT,
    REVISION_PROMPT, REFLECTION_PROMPTS
)
from .utils import JSONExtractor, parse_react_output
from .config import get_settings, get_word_count


_llm_instance = None
def get_llm() -> LLMClient:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LLMClient()
    return _llm_instance


class PlannerAgent:
    def __init__(self):
        self.llm = get_llm()
        self.executor = _CachedExecutor(self.llm)

    def plan_column(self, topic: str) -> ColumnPlan:
        prompt = PLANNER_PROMPT.format(topic=topic)
        response = self.llm.think([{"role": "user", "content": prompt}], temperature=0.1)

        import json as _json
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if match:
            response = match.group(1)
        try:
            data = _json.loads(response)
            return ColumnPlan.from_dict(data)
        except _json.JSONDecodeError:
            pass

        try:
            data = JSONExtractor.extract(response, required_fields=["column_title", "topics"])
            return ColumnPlan.from_dict(data)
        except ValueError:
            pass

        return ColumnPlan(
            column_title=f"{topic} 专栏",
            column_description=f"关于{topic}的系统性解读",
            target_audience="开发者",
            topics=[{
                "id": "topic_001", "title": topic,
                "description": f"深入探讨{topic}的核心概念与实践",
                "estimated_words": 600, "key_points": ["基础概念", "核心原理", "实践应用"],
                "prerequisites": ["基础知识"]
            }]
        )


class _CachedExecutor:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "output", "plan_cache"
        )

    def _cache_key(self, topic: str, step: int) -> str:
        return hashlib.md5(f"{topic}:{step}".encode()).hexdigest()

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def execute_step(self, topic: str, step: Dict, step_idx: int, context: str) -> str:
        cache_key = self._cache_key(topic, step_idx)
        cache_path = self._cache_path(cache_key)
        os.makedirs(self.cache_dir, exist_ok=True)

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                return json.load(f)["result"]

        prompt = f"""## 上下文
{context}

## 当前步骤
{json.dumps(step, ensure_ascii=False)}

请执行此步骤并输出结果。"""
        result = self.llm.think([{"role": "user", "content": prompt}], temperature=0.1)

        with open(cache_path, "w") as f:
            json.dump({"result": result, "step": step_idx}, f)
        return result or ""


class WriterAgent:
    def __init__(self, enable_search: bool = True):
        self.llm = get_llm()
        self.search_client = SearchClient() if enable_search else None
        self.max_steps = 8
        self._setup_tools()

    def _setup_tools(self):
        self.tools = {}
        if self.search_client:
            self.tools["web_search"] = ("搜索网络信息，获取最新资料。输入搜索查询词。", self.search_client.web_search)
            self.tools["search_recent_info"] = ("搜索最新信息。输入话题。", self.search_client.search_recent_info)
            self.tools["search_code_examples"] = ("搜索代码示例。格式: 技术名|任务描述", self.search_client.search_code_examples)
            self.tools["verify_facts"] = ("验证事实准确性。输入需要验证的陈述。", self.search_client.verify_facts)

    def _tool_descriptions(self) -> str:
        return "\n".join(f"- {name}: {desc}" for name, (desc, _) in self.tools.items())

    def _run_tool(self, tool_name: str, query: str) -> str:
        tool = self.tools.get(tool_name)
        if not tool:
            return f"工具 '{tool_name}' 不可用"
        try:
            return tool[1](query)
        except Exception as e:
            return f"工具执行失败: {e}"

    def generate_content(self, node: ContentNode, context: Dict[str, Any], level: int, additional_requirements: str = "") -> Dict[str, Any]:
        question = self._build_question(node, context, level, additional_requirements)
        prompt = WRITER_PROMPT.format(tools=self._tool_descriptions(), question=question, history="(无)")

        history = []
        for step in range(self.max_steps):
            response = self.llm.think([{"role": "user", "content": prompt}], temperature=0.3)
            if not response:
                break

            thought, action = parse_react_output(response)

            if action and action.lower().startswith("finish"):
                finish_content = action[action.find("["):action.rfind("]")+1] if "[" in action else action[len("Finish"):].strip()
                try:
                    return JSONExtractor.extract(finish_content, required_fields=["content"])
                except ValueError:
                    try:
                        data = json.loads(finish_content)
                        if isinstance(data, dict) and "content" in data:
                            return data
                    except (json.JSONDecodeError, ValueError):
                        pass
                    if len(finish_content) > 100:
                        return {"title": node.title, "level": level, "content": finish_content,
                                "word_count": len(finish_content), "needs_expansion": False,
                                "subsections": [], "metadata": {}}
                break

            if action:
                tool_match = re.match(r"(\w+)\[(.*)\]", action, re.DOTALL)
                if tool_match:
                    tool_name, query = tool_match.group(1), tool_match.group(2).strip()
                    observation = self._run_tool(tool_name, query)
                else:
                    observation = f"无法解析动作: {action}"
            else:
                observation = "没有可执行的动作，继续生成内容。"

            history.append(f"Thought: {thought}")
            history.append(f"Action: {action}")
            history.append(f"Observation: {observation}")
            prompt = WRITER_PROMPT.format(tools=self._tool_descriptions(), question=question, history="\n".join(history))

        return {"title": node.title, "level": level, "content": "内容生成未完成，请重试。",
                "word_count": 0, "needs_expansion": False, "subsections": [], "metadata": {}}

    def _build_question(self, node: ContentNode, context: Dict[str, Any], level: int, additional: str = "") -> str:
        column_ctx = context.get('column_context', context)
        return (
            f"专栏标题: {context.get('column_title', '')}\n"
            f"专栏描述: {context.get('column_description', '')}\n"
            f"目标读者: {context.get('target_audience', '')}\n"
            f"当前层级: Level {level}\n"
            f"当前标题: {node.title}\n"
            f"当前描述: {node.description}\n"
            f"目标字数: {get_word_count(level)}\n"
            + (f"额外要求: {additional}\n" if additional else "")
        )


class ReviewerAgent:
    def __init__(self):
        self.llm = get_llm()

    def review_content(self, content: str, level: int, target_word_count: int, key_points: List[str]) -> ReviewResult:
        prompt = REVIEWER_PROMPT.format(
            level=level,
            target_word_count=target_word_count,
            key_points=key_points,
            content=content
        )
        response = self.llm.think([{"role": "user", "content": prompt}], temperature=0.1)
        if not response:
            return ReviewResult(score=75, grade="良好", dimension_scores={}, detailed_feedback={},
                                revision_plan={}, needs_revision=False)
        try:
            data = JSONExtractor.extract(response, required_fields=["score", "grade"])
            return ReviewResult.from_dict(data)
        except ValueError:
            match = re.search(r'"score"\s*:\s*(\d+)', response)
            score = int(match.group(1)) if match else 75
            grade = "良好" if score >= 75 else ("需改进" if score >= 60 else "不合格")
            return ReviewResult(score=score, grade=grade, dimension_scores={}, detailed_feedback={},
                                revision_plan={}, needs_revision=(score < 75))


class RevisionAgent:
    def __init__(self):
        self.llm = get_llm()

    def revise_content(self, original_content: str, review_result: ReviewResult, target_word_count: int) -> Dict[str, Any]:
        review_data = review_result.detailed_feedback
        strengths = "\n".join(f"- {s}" for s in review_data.get('strengths', ["保持优点"]))
        issues = "\n".join(
            f"- [{i.get('category','')}] {i.get('problem','')}"
            for i in review_data.get('issues', [{"problem": "需改进"}])
        )
        priority = review_result.revision_plan.get('priority_changes', [{"section": "", "action": "", "detail": ""}])
        minor = review_result.revision_plan.get('minor_improvements', [{"section": "", "action": "", "detail": ""}])
        priority_lines = "\n".join(f"- {p.get('section','')}: {p.get('detail','')}" for p in priority)
        minor_lines = "\n".join(f"- {m.get('section','')}: {m.get('detail','')}" for m in minor)

        prompt = REVISION_PROMPT.format(
            original_content=original_content,
            score=review_result.score,
            grade=review_result.grade,
            strengths=strengths or "无",
            issues=issues or "无",
            reviewer_notes=review_result.reviewer_notes or "",
            priority_changes=priority_lines or "无",
            minor_improvements=minor_lines or "无",
            word_count_range=f"{int(target_word_count*0.9)}-{int(target_word_count*1.1)}",
            current_word_count=str(len(original_content)),
            word_count_adjustment=f"{'需增加' if len(original_content) < target_word_count else '需精简'} 约{abs(len(original_content) - target_word_count)}字"
        )
        response = self.llm.think([{"role": "user", "content": prompt}], temperature=0.3)
        if not response:
            return {"revised_content": original_content, "revision_summary": {}, "word_count": len(original_content)}

        try:
            data = JSONExtractor.extract(response, required_fields=["revised_content"])
            return data
        except ValueError:
            if len(response) > 100:
                return {"revised_content": response, "revision_summary": {}, "word_count": len(response)}
            return {"revised_content": original_content, "revision_summary": {}, "word_count": len(original_content)}


class ReflectionWriterAgent:
    def __init__(self, max_iterations: int = 2):
        self.llm = get_llm()
        self.max_iterations = max_iterations

    def generate_and_refine_content(self, node: ContentNode, context: Dict[str, Any], level: int) -> Dict[str, Any]:
        question = (
            f"专栏标题: {context.get('column_title', '')}\n"
            f"当前标题: {node.title}\n"
            f"当前层级: Level {level}\n"
            f"目标字数: {get_word_count(level)}\n"
            f"请写一篇关于'{node.title}'的完整技术文章。"
        )

        init_prompt = f"""请根据以下要求撰写一篇技术文章。

{question}

文章需包含：
1. 引言（背景介绍、重要性）
2. 主体内容（核心概念、详细解释、代码示例）
3. 总结与展望

输出JSON格式：
{{"title": "...", "level": {level}, "content": "完整文章markdown", "word_count": xxx, "needs_expansion": true/false, "subsections": []}}"""

        draft = self.llm.think([{"role": "user", "content": init_prompt}], temperature=0.3)
        if not draft:
            return {"title": node.title, "level": level, "content": "", "word_count": 0,
                    "needs_expansion": False, "subsections": [], "metadata": {}}

        content_data = None
        try:
            content_data = JSONExtractor.extract(draft, required_fields=["content"])
        except ValueError:
            brace_start = draft.find('{')
            brace_end = draft.rfind('}')
            if brace_start != -1 and brace_end > brace_start:
                try:
                    content_data = json.loads(draft[brace_start:brace_end+1])
                except json.JSONDecodeError:
                    pass

        if not content_data:
            content_data = {"title": node.title, "level": level, "content": draft,
                            "word_count": len(draft), "needs_expansion": False,
                            "subsections": [], "metadata": {}}

        for i in range(self.max_iterations):
            reflect_prompt = REFLECTION_PROMPTS["self_reflect_prompt"].format(
                question=question, draft=content_data.get("content", "")
            )
            reflection = self.llm.think([{"role": "user", "content": reflect_prompt}], temperature=0.1)
            if not reflection or "无需改进" in reflection:
                break

            refine_prompt = REFLECTION_PROMPTS["refine_prompt"].format(
                question=question, draft=content_data.get("content", ""), reflection=reflection
            )
            refined = self.llm.think([{"role": "user", "content": refine_prompt}], temperature=0.3)
            if refined:
                try:
                    refined_data = JSONExtractor.extract(refined, required_fields=["content"])
                    content_data = refined_data
                except ValueError:
                    if len(refined) > 100:
                        content_data["content"] = refined

        content_data.setdefault("metadata", {})
        content_data["metadata"]["auto_refined"] = True
        content_data["metadata"]["refinement_rounds"] = min(i + 1, self.max_iterations)
        content_data.setdefault("word_count", len(content_data.get("content", "")))
        content_data.setdefault("needs_expansion", False)
        content_data.setdefault("subsections", [])
        return content_data
