# llms.py

import os
from dotenv import load_dotenv
# from langchain_openai import ChatOpenAI
from custom_grok import GrokChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_experimental.openai_assistant import OpenAIAssistantRunnable
from langchain_core.runnables import RunnableLambda

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- Funções Auxiliares para o OpenAI Assistant ---

def format_assistant_input(prompt_value):
    """
    Converte a saída de um PromptTemplate (PromptValue) para o formato de dicionário
    que o OpenAIAssistantRunnable espera.
    """
    # Extrai o texto do objeto PromptValue
    content_string = prompt_value.to_string()
    return {"content": content_string}

def parse_assistant_output(assistant_output_messages):
    """
    Extrai o conteúdo de texto da última mensagem retornada pelo assistente.
    A API de Assistentes retorna uma lista de todas as mensagens da interação.
    """
    if assistant_output_messages and len(assistant_output_messages) > 0:
        # A última mensagem na lista é a resposta do assistente
        last_message = assistant_output_messages[-1]
        
        # O conteúdo da mensagem está em uma lista, geralmente com um único item de texto
        if last_message.content and len(last_message.content) > 0:
            # Acessa o valor do texto
            return last_message.content[0].text.value

    return "" # Retorna string vazia se não houver saída

# --- Inicialização dos LLMs ---

# OpenAI
assistant_runnable = OpenAIAssistantRunnable(
    assistant_id=os.getenv("OPENAI_ASSISTANT_ID"), 
    as_agent=True,
    timeout=900
)

openai_llm = (
    RunnableLambda(format_assistant_input) # Recebe PromptValue, retorna dict
    | assistant_runnable                   # Executa o assistente
    | RunnableLambda(parse_assistant_output) # Recebe lista de mensagens, retorna string
)

# GROK da xAI
grok_llm = GrokChatModel(
   api_key=os.getenv("X_API_KEY"),
   model=os.getenv("GROK_MODEL_ID"),
   base_url=os.getenv("X_API_BASE_URL"),
   timeout=900
)

# Claude Sonnet
claude_llm = ChatAnthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    model_name=os.getenv("CLAUDE_MODEL_ID"),
    timeout=900
)

# Gemini
gemini_llm = ChatGoogleGenerativeAI(
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    model=os.getenv("GEMINI_MODEL_ID"),
    timeout=900
)
