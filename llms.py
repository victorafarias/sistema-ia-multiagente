# llms.py

import os
from dotenv import load_dotenv
# from langchain_openai import ChatOpenAI
from custom_grok import GrokChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_experimental.openai_assistant import OpenAIAssistantRunnable

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- Inicialização dos LLMs ---

# OpenAI
openai_llm = OpenAIAssistantRunnable(
    assistant_id=os.getenv("OPENAI_ASSISTANT_ID"), 
    as_agent=True, # O 'as_agent=True' garante o comportamento correto de entrada/saída
    timeout=900
)

# GROK da xAI
grok_llm = GrokChatModel(
   api_key=os.getenv("X_API_KEY"),
   model=os.getenv("GROK_MODEL_ID"),
   base_url=os.getenv("X_API_BASE_URL"),
   timeout=900

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
