# rag_processor.py

import os
from typing import List
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

embeddings_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

def get_relevant_context(file_paths: List[str], user_query: str) -> str:
    """
    Processa arquivos a partir de seus caminhos no disco, cria uma base de conhecimento
    e retorna os trechos mais relevantes para a consulta do usuário.
    """
    documents = []

    # 1. Carregar e Extrair Texto dos Arquivos a partir dos caminhos
    for file_path in file_paths:
        filename = os.path.basename(file_path)
        
        if filename.endswith(".pdf"):
            loader = PyPDFLoader(file_path)
        elif filename.endswith(".docx"):
            loader = Docx2txtLoader(file_path)
        elif filename.endswith(".txt"):
            loader = TextLoader(file_path, encoding='utf-8')
        else:
            continue
        
        documents.extend(loader.load())

    if not documents:
        return "Nenhum documento de referência foi fornecido ou os formatos não são suportados."

    # 2. Dividir o Texto em Chunks
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    texts = text_splitter.split_documents(documents)

    # 3. Criar a Base de Conhecimento Vetorial
    vector_store = FAISS.from_documents(texts, embeddings_model)

    # 4. Buscar os Chunks Mais Relevantes
    retriever = vector_store.as_retriever(search_kwargs={"k": 4})
    relevant_docs = retriever.invoke(user_query)

    # 5. Formatar e Retornar o Contexto
    context = "\n\n".join([doc.page_content for doc in relevant_docs])
    
    # Limpa os arquivos temporários após o uso
    for file_path in file_paths:
        try:
            os.remove(file_path)
        except OSError as e:
            print(f"Erro ao deletar o arquivo {file_path}: {e}")
            
    return context
