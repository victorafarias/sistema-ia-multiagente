# Usa uma imagem oficial do Python como base
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# CORREÇÃO: Define uma variável de ambiente para que o cache de modelos
# seja salvo dentro da nossa pasta de projeto, onde temos permissão de escrita.
ENV HF_HOME=/app/.cache

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do código do projeto para o diretório de trabalho
COPY . .

# Comando para iniciar o servidor web de produção (gunicorn)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "app:app"]
