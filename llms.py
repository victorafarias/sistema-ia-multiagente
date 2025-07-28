# llms.py

import os
from dotenv import load_dotenv
# from langchain_openai import ChatOpenAI
from custom_grok import GrokChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- Inicialização dos LLMs ---

# GROK da xAI
grok_llm = GrokChatModel(
    api_key=os.getenv("X_API_KEY"),
    model=os.getenv("GROK_MODEL_ID"),
    base_url=os.getenv("X_API_BASE_URL"),
    client_kwargs={"timeout": 900}
)

# Claude Sonnet
claude_llm = ChatAnthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    model_name=os.getenv("CLAUDE_MODEL_ID"),
    client_kwargs={"timeout": 900}
)

# Gemini
gemini_llm = ChatGoogleGenerativeAI(
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    model=os.getenv("GEMINI_MODEL_ID"),
    client_kwargs={"timeout": 900}
)
