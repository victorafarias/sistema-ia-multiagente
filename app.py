# app.py

from flask import Flask, render_template, request, Response
import markdown2
import json
import time
import os
import uuid
import threading
import concurrent.futures
import re  # Importação para expressões regulares

# Importações do LangChain
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

# Importa os LLMs
from llms import claude_llm, grok_llm, gemini_llm

# Importa os prompts
from config import *

# Importa nosso processador RAG
from rag_processor import get_relevant_context

app = Flask(__name__)

# Garante que o diretório de uploads exista
if not os.path.exists('uploads'):
    os.makedirs('uploads')

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

def is_html_empty(html: str) -> bool:
    """Verifica se uma string HTML não contém texto visível."""
    if not html:
        return True
    # Remove todas as tags HTML
    text_only = re.sub('<[^<]+?>', '', html)
    # Verifica se o texto restante é apenas espaço em branco
    return not text_only.strip()

@app.route('/')
def index():
    """Renderiza a página inicial da aplicação."""
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    """Processa a solicitação do usuário nos modos Hierárquico ou Atômico."""
    form_data = request.form
    files = request.files.getlist('files')
    mode = form_data.get('mode', 'real')
    processing_mode = form_data.get('processing_mode', 'hierarchical')
    
    temp_file_paths = []
    if mode == 'real':
        for file in files:
            if file and file.filename:
                unique_filename = str(uuid.uuid4()) + "_" + os.path.basename(file.filename)
                file_path = os.path.join('uploads', unique_filename)
                file.save(file_path)
                temp_file_paths.append(file_path)

    def generate_stream(current_mode, form_data, file_paths):
        """Gera a resposta em streaming para o front-end."""
        solicitacao_usuario = form_data.get('solicitacao', '')
        
        if current_mode == 'test':
            mock_text = form_data.get('mock_text', 'Este é um texto de simulação.')
            mock_html = markdown2.markdown(mock_text, extras=["fenced-code-blocks", "tables"])
            yield f"data: {json.dumps({'progress': 100, 'message': 'Simulação concluída!', 'partial_result': {'id': 'grok-output', 'content': mock_html}, 'done': True, 'mode': 'atomic' if processing_mode == 'atomic' else 'hierarchical'})}\n\n"
            if processing_mode == 'atomic':
                yield f"data: {json.dumps({'partial_result': {'id': 'sonnet-output', 'content': mock_html}})}\n\n"
                yield f"data: {json.dumps({'partial_result': {'id': 'gemini-output', 'content': mock_html}})}\n\n"
        else:
            if not solicitacao_usuario:
                yield f"data: {json.dumps({'error': 'Solicitação não fornecida.'})}\n\n"
                return

            try:
                yield f"data: {json.dumps({'progress': 0, 'message': 'Processando arquivos e extraindo contexto...'})}\n\n"
                rag_context = get_relevant_context(file_paths, solicitacao_usuario)
                
                if processing_mode == 'atomic':
                    # --- LÓGICA ATÔMICA (PARALELA) ---
                    results = {}
                    threads = []
                    
                    def run_chain_with_timeout(chain, inputs, key, timeout=300):
                        def task():
                            return chain.invoke(inputs)['text']
                        
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(task)
                            try:
                                result = future.result(timeout=timeout)
                                if not result or not result.strip():
                                    results[key] = "Error:EmptyResponse"
                                else:
                                    results[key] = result
                            except concurrent.futures.TimeoutError:
                                results[key] = f"Erro ao processar {key.upper()}: Tempo limite excedido."
                            except Exception as e:
                                results[key] = f"Erro ao processar {key.upper()}: {e}"

                    # ✅ CORREÇÃO: Aumenta o max_tokens para o Claude Sonnet também no modo atômico
                    claude_atomic_llm = claude_llm.bind(max_tokens=20000)
                    models = {'grok': grok_llm, 'sonnet': claude_atomic_llm, 'gemini': gemini_llm}
                    
                    prompt = PromptTemplate(template=PROMPT_ATOMICO_INICIAL, input_variables=["solicitacao_usuario", "rag_context"])
                    yield f"data: {json.dumps({'progress': 15, 'message': 'Iniciando processamento paralelo...'})}\n\n"
                    
                    for name, llm in models.items():
                        chain = LLMChain(llm=llm, prompt=prompt)
                        thread = threading.Thread(target=run_chain_with_timeout, args=(chain, {"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context}, name))
                        threads.append(thread)
                        thread.start()

                    for thread in threads:
                        thread.join()
                    
                    for key, result in results.items():
                        if result == "Error:EmptyResponse" or "Erro ao processar" in result:
                            error_msg = result if "Erro ao processar" in result else f"Falha no serviço {key.upper()}: Sem resposta."
                            yield f"data: {json.dumps({'error': error_msg})}\n\n"
                            return

                    yield f"data: {json.dumps({'progress': 80, 'message': 'Todos os modelos responderam. Formatando saídas...'})}\n\n"
                    
                    # GROK
                    grok_text = results.get('grok', '')
                    grok_html = markdown2.markdown(grok_text, extras=["fenced-code-blocks", "tables"])
                    if is_html_empty(grok_html):
                        grok_html = f"<pre>{grok_text}</pre>"
                    yield f"data: {json.dumps({'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"

                    # SONNET
                    sonnet_text = results.get('sonnet', '')
                    sonnet_html = markdown2.markdown(sonnet_text, extras=["fenced-code-blocks", "tables"])
                    if is_html_empty(sonnet_html):
                        sonnet_html = f"<pre>{sonnet_text}</pre>"
                    yield f"data: {json.dumps({'partial_result': {'id': 'sonnet-output', 'content': sonnet_html}})}\n\n"

                    # GEMINI
                    gemini_text = results.get('gemini', '')
                    gemini_html = markdown2.markdown(gemini_text, extras=["fenced-code-blocks", "tables"])
                    if is_html_empty(gemini_html):
                        gemini_html = f"<pre>{gemini_text}</pre>"
                    yield f"data: {json.dumps({'partial_result': {'id': 'gemini-output', 'content': gemini_html}})}\n\n"
                    
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento Atômico concluído!', 'done': True, 'mode': 'atomic'})}\n\n"
                
                else:
                    # --- LÓGICA HIERÁRQUICA (SEQUENCIAL) ---
                    yield f"data: {json.dumps({'progress': 15, 'message': 'O GROK está processando sua solicitação...'})}\n\n"
                    prompt_grok = PromptTemplate(template=PROMPT_HIERARQUICO_GROK, input_variables=["solicitacao_usuario", "rag_context"])
                    chain_grok = LLMChain(llm=grok_llm, prompt=prompt_grok)
                    resposta_grok = chain_grok.invoke({"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context})['text']
                    
                    if not resposta_grok or not resposta_grok.strip():
                        yield f"data: {json.dumps({'error': 'Falha no serviço GROK: Sem resposta.'})}\n\n"
                        return
                    
                    grok_html = markdown2.markdown(resposta_grok, extras=["fenced-code-blocks", "tables"])
                    if is_html_empty(grok_html):
                        grok_html = f"<pre>{resposta_grok}</pre>"
                    yield f"data: {json.dumps({'progress': 33, 'message': 'Claude Sonnet está processando...', 'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"
                    
                    prompt_sonnet = PromptTemplate(template=PROMPT_HIERARQUICO_SONNET, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    claude_with_max_tokens = claude_llm.bind(max_tokens=20000)
                    chain_sonnet = LLMChain(llm=claude_with_max_tokens, prompt=prompt_sonnet)
                    resposta_sonnet = chain_sonnet.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_grok})['text']
                    
                    if not resposta_sonnet or not resposta_sonnet.strip():
                        yield f"data: {json.dumps({'error': 'Falha no serviço Claude Sonnet: Sem resposta.'})}\n\n"
                        return

                    sonnet_html = markdown2.markdown(resposta_sonnet, extras=["fenced-code-blocks", "tables"])
                    if is_html_empty(sonnet_html):
                        sonnet_html = f"<pre>{resposta_sonnet}</pre>"
                    yield f"data: {json.dumps({'progress': 66, 'message': 'Gemini está processando...', 'partial_result': {'id': 'sonnet-output', 'content': sonnet_html}})}\n\n"
                    
                    prompt_gemini = PromptTemplate(template=PROMPT_HIERARQUICO_GEMINI, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    chain_gemini = LLMChain(llm=gemini_llm, prompt=prompt_gemini)
                    resposta_gemini = chain_gemini.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_sonnet})['text']
                    
                    if not resposta_gemini or not resposta_gemini.strip():
                        yield f"data: {json.dumps({'error': 'Falha no serviço Gemini: Sem resposta.'})}\n\n"
                        return

                    gemini_html = markdown2.markdown(resposta_gemini, extras=["fenced-code-blocks", "tables"])
                    if is_html_empty(gemini_html):
                        gemini_html = f"<pre>{resposta_gemini}</pre>"
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento concluído!', 'partial_result': {'id': 'gemini-output', 'content': gemini_html}, 'done': True, 'mode': 'hierarchical'})}\n\n"

            except Exception as e:
                print(f"Ocorreu um erro durante o processamento: {e}")
                yield f"data: {json.dumps({'error': f'Ocorreu um erro inesperado na aplicação: {e}'})}\n\n"

    return Response(generate_stream(mode, form_data, temp_file_paths), mimetype='text/event-stream')

@app.route('/merge', methods=['POST'])
def merge():
    """Recebe os textos do modo Atômico e os consolida usando um LLM."""
    data = request.get_json()
    
    def generate_merge_stream():
        """Gera a resposta do merge em streaming."""
        try:
            yield f"data: {json.dumps({'progress': 0, 'message': 'Iniciando o processo de merge...'})}\n\n"
            
            prompt_merge = PromptTemplate(template=PROMPT_ATOMICO_MERGE, input_variables=["solicitacao_usuario", "texto_para_analise_grok", "texto_para_analise_sonnet", "texto_para_analise_gemini"])
            chain_merge = LLMChain(llm=grok_llm, prompt=prompt_merge)

            yield f"data: {json.dumps({'progress': 50, 'message': 'Enviando textos para o GROK para consolidação...'})}\n\n"

            resposta_merge = chain_merge.invoke({
                "solicitacao_usuario": data.get('solicitacao_usuario'),
                "texto_para_analise_grok": data.get('grok_text'),
                "texto_para_analise_sonnet": data.get('sonnet_text'),
                "texto_para_analise_gemini": data.get('gemini_text')
            })['text']
            
            if not resposta_merge or not resposta_merge.strip():
                yield f"data: {json.dumps({'error': 'Falha no serviço de Merge (GROK): Sem resposta.'})}\n\n"
                return
            
            word_count = len(resposta_merge.split())
            merge_html = markdown2.markdown(resposta_merge, extras=["fenced-code-blocks", "tables"])
            
            yield f"data: {json.dumps({'progress': 100, 'message': 'Merge concluído!', 'final_result': {'content': merge_html, 'word_count': word_count}, 'done': True})}\n\n"

        except Exception as e:
            print(f"Erro no processo de merge: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return Response(generate_merge_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True)
