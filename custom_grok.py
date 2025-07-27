# custom_grok.py

from typing import Any, List, Optional, Dict
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
import requests

class GrokChatModel(BaseChatModel):
    """
    Wrapper customizado e robusto para o modelo GROK da xAI,
    com tratamento aprimorado de timeouts e erros de resposta.
    """
    model: str
    api_key: str
    base_url: str

    @property
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

        try:
            response = requests.post(
                self.base_url,
                headers=self._default_headers(),
                json=payload,
                timeout=300  # Adiciona um timeout de 300 segundos (5 minutos)
            )
            # Lança um erro para status HTTP 4xx ou 5xx
            response.raise_for_status()

            result = response.json()
            
            # Validação robusta da resposta da API
            if not result.get("choices") or not isinstance(result["choices"], list) or len(result["choices"]) == 0:
                raise ValueError("Resposta da API do GROK inválida: campo 'choices' ausente ou vazio.")

            message = result["choices"][0].get("message", {})
            content = message.get("content")

            if not content or not content.strip():
                # Isso captura o caso de uma resposta bem-sucedida, mas com conteúdo vazio.
                raise ValueError("Resposta da API do GROK retornou conteúdo vazio.")

            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=content))]
            )

        except requests.exceptions.Timeout:
            raise ValueError("Erro na chamada da API da Grok: Tempo limite excedido (Timeout).")
        except requests.exceptions.RequestException as e:
            # Captura outros erros de conexão (DNS, rede, etc.)
            raise ValueError(f"Erro de conexão com a API da Grok: {e}")

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Retorna um dicionário para identificar o modelo."""
        return {"model": self.model, "base_url": self.base_url}
