import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    def __init__(self, model=None, api_key=None, base_url=None, timeout=60):
        self.model = model or os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")

        if not self.api_key:
            raise RuntimeError("LLM_API_KEY or OPENAI_API_KEY not set in environment")

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=timeout)

    def think(self, messages, temperature=0.1, stream=False):
        try:
            if stream:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                )
                chunks = []
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        chunks.append(chunk.choices[0].delta.content)
                return "".join(chunks)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )
                return response.choices[0].message.content
        except Exception as e:
            print(f"LLM call failed: {e}")
            return None
