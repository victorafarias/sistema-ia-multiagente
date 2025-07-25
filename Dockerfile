# Usa uma imagem oficial do Python como base
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copia o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt requirements.txt

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do código do projeto para o diretório de trabalho
COPY . .

# Comando para iniciar o servidor web de produção (gunicorn)
# Ele vai procurar por uma variável chamada 'app' no arquivo 'app.py'
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "app:app"]
