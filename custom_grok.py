from typing import Any, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
import requests

class GrokChatModel(BaseChatModel):
    model: str
    api_key: str
    base_url: str

    def _llm_type(self) -> str:
        return "grok-chat"

    def _default_headers(self):
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _generate(
        self, messages: List[HumanMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any
    ) -> ChatResult:
        last_message = messages[-1].content

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": last_message}],
            "temperature": 0.7
        }

        response = requests.post(
            self.base_url,
            headers=self._default_headers(),
            json=payload
        )

        if response.status_code != 200:
            raise ValueError(f"Erro na chamada da API da Grok: {response.status_code} - {response.text}")

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # ✅ Correção: Retornar ChatResult com lista de ChatGeneration
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    @property
    def _identifying_params(self) -> dict:
        return {
            "model": self.model,
            "base_url": self.base_url,
        }
