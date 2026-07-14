import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    def __init__(self):
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        model_id = os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        if not api_key:
            raise RuntimeError("LLM_API_KEY or OPENAI_API_KEY not set in environment")

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model_id

    def think(self, messages, temperature=0.0):
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM call failed: {e}")
            return None
