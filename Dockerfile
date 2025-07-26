# Usa uma imagem oficial do Python como base
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Define a variável de ambiente para o cache
ENV HF_HOME=/app/.cache

# 1. Cria o diretório de cache.
# 2. Dá permissão de escrita para o usuário padrão do contêiner (ID 1000).
RUN mkdir -p /app/.cache && chown -R 1000:1000 /app/.cache

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do código do projeto para o diretório de trabalho
COPY . .

# Comando para iniciar o servidor web de produção (gunicorn)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "app:app"]