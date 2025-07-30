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
from langchain_experimental.openai_assistant.schema import OpenAIAssistantFinish

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- Funções Auxiliares para o OpenAI Assistant ---

def format_assistant_input(prompt_value):
    """
    Converte a saída de um PromptTemplate (PromptValue) para o formato de dicionário
    que o OpenAIAssistantRunnable espera.
    """
    content_string = prompt_value.to_string()
    return {"content": content_string}

def parse_assistant_output(assistant_finish_object):
    """
    (CORRIGIDO) Extrai a string de saída de um objeto OpenAIAssistantFinish.
    O resultado final do assistente está no dicionário `return_values`.
    """
    # Verifica se o objeto recebido é do tipo esperado
    if isinstance(assistant_finish_object, OpenAIAssistantFinish):
        # A resposta final em string está na chave 'output' do dicionário return_values
        return assistant_finish_object.return_values.get('output', '')
    
    # Adicionado um fallback caso a saída já seja uma string
    if isinstance(assistant_finish_object, str):
        return assistant_finish_object
    
    # Retorna uma string vazia se o formato for inesperado
    return ""

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
