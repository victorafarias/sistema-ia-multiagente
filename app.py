# app.py

from flask import Flask, render_template, request, Response
import json
import time
import os
import uuid
import threading
import concurrent.futures
from html import escape, unescape
import re
from markdown_it import MarkdownIt
from markdown2 import markdown as markdown2_render

# Importações do LangChain
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

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

# Instancia o conversor de Markdown
md = MarkdownIt()

# [ADICIONADO] Função para renderização com fallback: tenta MarkdownIt, depois markdown2

def render_markdown_cascata(texto: str) -> str:
    try:
        html_1 = md.render(texto)
        if not is_html_empty(html_1):
            return html_1
    except Exception as e:
        print(f"MarkdownIt falhou: {e}")

    try:
        html_2 = markdown2_render(texto)
        if not is_html_empty(html_2):
            return html_2
    except Exception as e:
        print(f"markdown2 falhou: {e}")

    return f"<pre>{escape(texto)}</pre>"

def is_html_empty(html: str) -> bool:
    """
    Verifica de forma robusta se uma string HTML não contém texto visível,
    lidando com entidades HTML e múltiplos tipos de espaços em branco.
    """
    if not html:
        return True
    # 1. Remove todas as tags HTML
    text_only = re.sub('<[^<]+?>', '', html)
    # 2. Decodifica entidades HTML (ex: &nbsp; para ' ')
    decoded_text = unescape(text_only)
    # 3. Substitui qualquer sequência de caracteres de espaço em branco por um único espaço
    normalized_space = re.sub(r'\s+', ' ', decoded_text)
    # 4. Verifica se o texto restante (após remover espaços nas pontas) está de fato vazio
    return not normalized_space.strip()

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
            mock_html = md.render(mock_text)
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
                
                output_parser = StrOutputParser()

                if processing_mode == 'atomic':
                    # --- LÓGICA ATÔMICA (PARALELA) ---
                    results = {}
                    threads = []
                    
                    def run_chain_with_timeout(chain, inputs, key, timeout=300):
                        def task():
                            return chain.invoke(inputs)
                        
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

                    claude_atomic_llm = claude_llm.bind(max_tokens=20000)
                    models = {'grok': grok_llm, 'sonnet': claude_atomic_llm, 'gemini': gemini_llm}
                    
                    prompt = PromptTemplate(template=PROMPT_ATOMICO_INICIAL, input_variables=["solicitacao_usuario", "rag_context"])
                    yield f"data: {json.dumps({'progress': 15, 'message': 'Iniciando processamento paralelo...'})}\n\n"
                    
                    for name, llm in models.items():
                        chain = prompt | llm | output_parser
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
                    
                    grok_text = results.get('grok', '')
                    print(f"--- Resposta Bruta do GROK (Atômico) ---\n{grok_text}\n--------------------------------------")
                    grok_html = render_markdown_cascata(grok_text)
                    if is_html_empty(grok_html):
                        grok_html = f"<pre>{escape(grok_text)}</pre>"
                    yield f"data: {json.dumps({'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"

                    sonnet_text = results.get('sonnet', '')
                    print(f"--- Resposta Bruta do Sonnet (Atômico) ---\n{sonnet_text}\n----------------------------------------")
                    sonnet_html = render_markdown_cascata(sonnet_text)
                    if is_html_empty(sonnet_html):
                        sonnet_html = f"<pre>{escape(sonnet_text)}</pre>"
                    yield f"data: {json.dumps({'partial_result': {'id': 'sonnet-output', 'content': sonnet_html}})}\n\n"

                    gemini_text = results.get('gemini', '')
                    print(f"--- Resposta Bruta do Gemini (Atômico) ---\n{gemini_text}\n----------------------------------------")
                    gemini_html = render_markdown_cascata(gemini_text)
                    if is_html_empty(gemini_html):
                        gemini_html = f"<pre>{escape(gemini_text)}</pre>"
                    yield f"data: {json.dumps({'partial_result': {'id': 'gemini-output', 'content': gemini_html}})}\n\n"
                    
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento Atômico concluído!', 'done': True, 'mode': 'atomic'})}\n\n"
                
                else:
                    # --- LÓGICA HIERÁRQUICA (SEQUENCIAL) ---
                    yield f"data: {json.dumps({'progress': 15, 'message': 'O GROK está processando sua solicitação...'})}\n\n"
                    prompt_grok = PromptTemplate(template=PROMPT_HIERARQUICO_GROK, input_variables=["solicitacao_usuario", "rag_context"])
                    chain_grok = prompt_grok | grok_llm | output_parser
                    resposta_grok = chain_grok.invoke({"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context})
                    
                    if not resposta_grok or not resposta_grok.strip():
                        yield f"data: {json.dumps({'error': 'Falha no serviço GROK: Sem resposta.'})}\n\n"
                        return
                    
                    print(f"--- Resposta Bruta do GROK (Hierárquico) ---\n{resposta_grok}\n------------------------------------------")
                    grok_html = render_markdown_cascata(resposta_grok)
                    if is_html_empty(grok_html):
                        grok_html = f"<pre>{escape(resposta_grok)}</pre>"
                    yield f"data: {json.dumps({'progress': 33, 'message': 'Claude Sonnet está processando...', 'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"
                    
                    prompt_sonnet = PromptTemplate(template=PROMPT_HIERARQUICO_SONNET, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    claude_with_max_tokens = claude_llm.bind(max_tokens=20000)
                    chain_sonnet = prompt_sonnet | claude_with_max_tokens | output_parser
                    resposta_sonnet = chain_sonnet.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_grok})
                    
                    if not resposta_sonnet or not resposta_sonnet.strip():
                        yield f"data: {json.dumps({'error': 'Falha no serviço Claude Sonnet: Sem resposta.'})}\n\n"
                        return

                    print(f"--- Resposta Bruta do Sonnet (Hierárquico) ---\n{resposta_sonnet}\n--------------------------------------------")
                    sonnet_html = render_markdown_cascata(resposta_sonnet)
                    if is_html_empty(sonnet_html):
                        sonnet_html = f"<pre>{escape(resposta_sonnet)}</pre>"
                    yield f"data: {json.dumps({'progress': 66, 'message': 'Gemini está processando...', 'partial_result': {'id': 'sonnet-output', 'content': sonnet_html}})}\n\n"
                    
                    prompt_gemini = PromptTemplate(template=PROMPT_HIERARQUICO_GEMINI, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    chain_gemini = prompt_gemini | gemini_llm | output_parser
                    resposta_gemini = chain_gemini.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_sonnet})
                    
                    if not resposta_gemini or not resposta_gemini.strip():
                        yield f"data: {json.dumps({'error': 'Falha no serviço Gemini: Sem resposta.'})}\n\n"
                        return

                    print(f"--- Resposta Bruta do Gemini (Hierárquico) ---\n{resposta_gemini}\n--------------------------------------------")
                    gemini_html = render_markdown_cascata(resposta_gemini)
                    if is_html_empty(gemini_html):
                        gemini_html = f"<pre>{escape(gemini_html)}</pre>"
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
            
            output_parser = StrOutputParser()
            prompt_merge = PromptTemplate(template=PROMPT_ATOMICO_MERGE, input_variables=["solicitacao_usuario", "texto_para_analise_grok", "texto_para_analise_sonnet", "texto_para_analise_gemini"])
            
            grok_with_max_tokens = grok_llm.bind(max_tokens=20000)
            chain_merge = prompt_merge | grok_with_max_tokens | output_parser

            yield f"data: {json.dumps({'progress': 50, 'message': 'Enviando textos para o GROK para consolidação...'})}\n\n"

            resposta_merge = chain_merge.invoke({
                "solicitacao_usuario": data.get('solicitacao_usuario'),
                "texto_para_analise_grok": data.get('grok_text'),
                "texto_para_analise_sonnet": data.get('sonnet_text'),
                "texto_para_analise_gemini": data.get('gemini_text')
            })
            
            if not resposta_merge or not resposta_merge.strip():
                yield f"data: {json.dumps({'error': 'Falha no serviço de Merge (GROK): Sem resposta.'})}\n\n"
                return
            
            print(f"--- Resposta Bruta do Merge (GROK) ---\n{resposta_merge}\n------------------------------------")
            word_count = len(resposta_merge.split())
            
            merge_html = render_markdown_cascata(resposta_merge)
            if is_html_empty(merge_html):
                merge_html = f"<pre>{escape(resposta_merge)}</pre>"
            
            yield f"data: {json.dumps({'progress': 100, 'message': 'Merge concluído!', 'final_result': {'content': merge_html, 'word_count': word_count}, 'done': True})}\n\n"

        except Exception as e:
            print(f"Erro no processo de merge: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return Response(generate_merge_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True)
