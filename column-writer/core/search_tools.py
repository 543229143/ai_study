import os
from typing import Optional


class SearchClient:
    def __init__(self):
        self.tavily_key = os.getenv("TAVILY_API_KEY")
        self.serpapi_key = os.getenv("SERPAPI_API_KEY")

    def search(self, query: str, max_results: int = 3) -> str:
        if self.tavily_key:
            return self._tavily_search(query, max_results)
        if self.serpapi_key:
            return self._serpapi_search(query, max_results)
        return "搜索功能不可用: 请配置 TAVILY_API_KEY 或 SERPAPI_API_KEY"

    def _tavily_search(self, query: str, max_results: int) -> str:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=self.tavily_key)
            response = client.search(query=query, max_results=max_results)

            parts = []
            if response.get('answer'):
                parts.append(f"AI 答案：{response['answer']}\n")
            parts.append("相关结果：\n")
            for i, item in enumerate(response.get('results', [])[:max_results], 1):
                parts.append(f"[{i}] {item.get('title', '')}")
                parts.append(f"    {item.get('content', '')[:200]}...")
                parts.append(f"    来源: {item.get('url', '')}\n")
            return "\n".join(parts)
        except Exception as e:
            return f"Tavily 搜索失败: {e}"

    def _serpapi_search(self, query: str, max_results: int) -> str:
        try:
            from serpapi import GoogleSearch
            search = GoogleSearch({
                "q": query, "api_key": self.serpapi_key,
                "num": max_results, "gl": "cn", "hl": "zh-cn"
            })
            results = search.get_dict()
            parts = ["搜索结果：\n"]
            if "answer_box" in results and "answer" in results["answer_box"]:
                parts.append(f"直接答案：{results['answer_box']['answer']}\n")
            if "organic_results" in results:
                for i, res in enumerate(results["organic_results"][:max_results], 1):
                    parts.append(f"[{i}] {res.get('title', '')}")
                    parts.append(f"    {res.get('snippet', '')}\n")
            return "\n".join(parts)
        except Exception as e:
            return f"SerpAPI 搜索失败: {e}"

    def web_search(self, query: str) -> str:
        return self.search(query, max_results=3)

    def search_recent_info(self, topic: str) -> str:
        return self.search(f"{topic} 最新 2025 2026", max_results=3)

    def search_code_examples(self, technology: str, task: str) -> str:
        return self.search(f"{technology} {task} 代码示例 教程", max_results=3)

    def verify_facts(self, statement: str) -> str:
        return self.search(f"{statement} 事实验证", max_results=3)
