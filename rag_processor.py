# rag_processor.py

import os
from typing import List
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader

def get_relevant_context(file_paths: List[str], user_query: str = None) -> str:
    """
    Extrai o texto completo de todos os arquivos anexados e retorna como uma única string.
    """
    all_contents: List[str] = []

    for file_path in file_paths:
        filename = os.path.basename(file_path)
        try:
            # Escolhe o loader adequado
            if filename.lower().endswith(".pdf"):
                loader = PyPDFLoader(file_path)
            elif filename.lower().endswith(".docx"):
                loader = Docx2txtLoader(file_path)
            elif filename.lower().endswith(".txt"):
                loader = TextLoader(file_path, encoding='utf-8')
            else:
                # ignora formatos não suportados
                continue

            # Carrega todos os documentos e concatena o conteúdo
            docs = loader.load()
            for doc in docs:
                all_contents.append(doc.page_content)

        except Exception as e:
            # Log simples de erro de leitura, para você ver no console
            print(f"[rag_processor] Erro ao carregar '{filename}': {e}", flush=True)

    # Remove os arquivos temporários após a extração
    for file_path in file_paths:
        try:
            os.remove(file_path)
        except OSError as e:
            print(f"[rag_processor] Erro ao deletar '{file_path}': {e}", flush=True)

    if not all_contents:
        return "Nenhum documento de referência foi fornecido ou os formatos não são suportados."

    # Retorna todo o texto concatenado, separado por duas quebras de linha
    return "\n\n".join(all_contents)
