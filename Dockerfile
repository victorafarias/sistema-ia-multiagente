# Usa uma imagem oficial do Python como base
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Define a variável de ambiente para o cache
ENV HF_HOME=/app/.cache

# e dá permissão de escrita para o usuário padrão do contêiner.
RUN mkdir -p /app/.cache /app/uploads && chown -R 1000:1000 /app/.cache /app/uploads

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do código do projeto para o diretório de trabalho
COPY . .

# Comando para iniciar o servidor web de produção (gunicorn)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "app:app"]

# Adiciona o parâmetro --timeout 300 para aumentar o tempo limite para 300 segundos (5 minutos)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--timeout", "900", "app:app"]