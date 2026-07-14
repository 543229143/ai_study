import json
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List


class JSONExtractor:
    @staticmethod
    def extract(
        response: str,
        required_fields: Optional[List[str]] = None,
        fallback_fields: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not response or not response.strip():
            raise ValueError("响应为空")
        fallback_fields = fallback_fields or {}
        required_fields = required_fields or []

        extractors = [
            JSONExtractor._extract_from_finish,
            JSONExtractor._extract_direct_json,
            JSONExtractor._extract_from_markdown_json,
            JSONExtractor._extract_from_markdown,
            JSONExtractor._extract_from_braces,
        ]
        last_error = None
        for extractor in extractors:
            try:
                result = extractor(response)
                if result is not None:
                    for key, default_value in fallback_fields.items():
                        if key not in result:
                            result[key] = default_value
                    if required_fields:
                        missing = [f for f in required_fields if f not in result]
                        if not missing:
                            return result
                    else:
                        return result
            except Exception as e:
                last_error = e
                continue
        try:
            result = JSONExtractor._extract_from_history(response)
            if result is not None:
                for key, default_value in fallback_fields.items():
                    if key not in result:
                        result[key] = default_value
                return result
        except Exception as e:
            last_error = e
        raise ValueError(f"响应中未找到有效的 JSON 数据: {last_error}")

    @staticmethod
    def _extract_from_finish(response: str) -> Optional[Dict[str, Any]]:
        match = re.search(r"Finish\[(.*)\]", response, re.DOTALL)
        if match:
            content = match.group(1).strip()
            return JSONExtractor._parse_json_with_retry(content)
        return None

    @staticmethod
    def _extract_direct_json(response: str) -> Optional[Dict[str, Any]]:
        stripped = response.strip()
        if stripped.startswith('{'):
            return JSONExtractor._parse_json_with_retry(stripped)
        return None

    @staticmethod
    def _extract_from_markdown_json(response: str) -> Optional[Dict[str, Any]]:
        if "```json" not in response:
            return None
        json_start = response.find("```json") + 7
        json_end = response.find("```", json_start)
        if json_end == -1:
            return None
        json_str = response[json_start:json_end].strip()
        return JSONExtractor._parse_json_with_retry(json_str)

    @staticmethod
    def _extract_from_markdown(response: str) -> Optional[Dict[str, Any]]:
        if "```" not in response:
            return None
        json_start = response.find("```") + 3
        json_end = response.find("```", json_start)
        if json_end == -1:
            return None
        json_str = response[json_start:json_end].strip()
        if json_str.startswith("json"):
            json_str = json_str[4:].strip()
        if json_str.startswith('{'):
            return JSONExtractor._parse_json_with_retry(json_str)
        return None

    @staticmethod
    def _extract_from_braces(response: str) -> Optional[Dict[str, Any]]:
        json_candidates = []
        i = 0
        while i < len(response):
            if response[i] == '{':
                brace_count = 0
                brace_start = i
                brace_end = i
                for j in range(i, len(response)):
                    if response[j] == '{':
                        brace_count += 1
                    elif response[j] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            brace_end = j + 1
                            break
                if brace_end > brace_start:
                    json_str = response[brace_start:brace_end]
                    try:
                        parsed = JSONExtractor._parse_json_with_retry(json_str)
                        if isinstance(parsed, dict):
                            json_candidates.append((parsed, len(parsed)))
                    except Exception:
                        pass
                    i = brace_end
                else:
                    i += 1
            else:
                i += 1
        if json_candidates:
            for parsed, _ in json_candidates:
                if 'content' in parsed and parsed.get('content'):
                    return parsed
            return max(json_candidates, key=lambda x: x[1])[0]
        return None

    @staticmethod
    def _extract_from_history(response: str) -> Optional[Dict[str, Any]]:
        json_matches = re.findall(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
        if not json_matches:
            json_matches = re.findall(r'(\{"column_title".*?"topics".*?\})', response, re.DOTALL)
        for json_str in json_matches:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _parse_json_with_retry(json_str: str) -> Dict[str, Any]:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        fixed = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        result = JSONExtractor._rebuild_json_from_fields(json_str)
        if result:
            return result
        raise json.JSONDecodeError("无法解析 JSON", json_str, 0)

    @staticmethod
    def _rebuild_json_from_fields(json_str: str) -> Optional[Dict[str, Any]]:
        title_match = re.search(r'"title"\s*:\s*"([^"]*)"', json_str)
        level_match = re.search(r'"level"\s*:\s*(\d+)', json_str)
        content_match = re.search(r'"content"\s*:\s*"(.*?)"(?=\s*[,}])', json_str, re.DOTALL)
        if not content_match:
            content_match = re.search(r'"content"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', json_str, re.DOTALL)
        if not any([title_match, level_match, content_match]):
            return None
        result = {}
        if title_match:
            result['title'] = title_match.group(1)
        if level_match:
            result['level'] = int(level_match.group(1))
        if content_match:
            result['content'] = content_match.group(1).replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
        result['word_count'] = len(result.get('content', ''))
        result['needs_expansion'] = False
        result.setdefault('subsections', [])
        result.setdefault('metadata', {})
        return result


def parse_react_output(text: str) -> Tuple[Optional[str], Optional[str]]:
    if not text or not text.strip():
        return None, None

    thought = None
    thought_patterns = [
        r"Thought:\s*(.*?)(?=\nAction:|\nFinish:|$)",
    ]
    for pattern in thought_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            thought = match.group(1).strip()
            break

    action = None
    action_patterns = [
        r"Action:\s*(.*?)(?=\nThought:|\nObservation:|\nFinish:|$)",
        r"Finish\[(.*?)\]",
    ]
    for pattern in action_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            action = match.group(1).strip()
            if pattern == r"Finish\[(.*?)\]":
                action = f"Finish[{action}]"
            break
    if not action:
        finish_match = re.search(r"Finish\s*\[(.*?)\]", text, re.DOTALL | re.IGNORECASE)
        if finish_match:
            action = f"Finish[{finish_match.group(1).strip()}]"

    return thought, action


def get_current_timestamp() -> str:
    return datetime.now().isoformat()
