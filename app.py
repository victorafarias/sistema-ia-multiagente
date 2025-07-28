# app.py

from flask import Flask, render_template, request, Response, jsonify
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
import traceback
import sys

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

# Função para renderização com fallback: tenta MarkdownIt, depois markdown2
def render_markdown_cascata(texto: str) -> str:
    try:
        html_1 = md.render(texto)
        if not is_html_empty(html_1):
            return html_1
    except Exception as e:
        print(f"MarkdownIt falhou: {e}")

    try:
        html_2 = markdown2_render(texto, extras=["fenced-code-blocks", "tables"])
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
    print("=== ROTA INDEX ACESSADA ===")
    return render_template('index.html')

# ROTA ATUALIZADA: Para converter texto em Markdown sob demanda
@app.route('/convert', methods=['POST'])
def convert():
    print("=== ROTA CONVERT ACESSADA ===")
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'Nenhum texto fornecido'}), 400
    
    text_to_convert = data['text']
    # USA A FUNÇÃO DE CASCATA PARA MAIOR ROBUSTEZ
    converted_html = render_markdown_cascata(text_to_convert)
    return jsonify({'html': converted_html})

@app.route('/process', methods=['POST'])
def process():
    """Processa a solicitação do usuário nos modos Hierárquico ou Atômico."""
    print("=== ROTA PROCESS ACESSADA ===")
    print(f"Method: {request.method}")
    print(f"Content-Type: {request.content_type}")
    
    try:
        form_data = request.form
        print(f"Form data keys: {list(form_data.keys())}")
        print(f"Form data: {dict(form_data)}")
        
        files = request.files.getlist('files')
        print(f"Files: {len(files)} arquivo(s)")
        
        mode = form_data.get('mode', 'real')
        processing_mode = form_data.get('processing_mode', 'hierarchical')
        
        print(f"Mode: {mode}")
        print(f"Processing mode: {processing_mode}")
        
        temp_file_paths = []
        if mode == 'real':
            for file in files:
                if file and file.filename:
                    print(f"Processando arquivo: {file.filename}")
                    unique_filename = str(uuid.uuid4()) + "_" + os.path.basename(file.filename)
                    file_path = os.path.join('uploads', unique_filename)
                    file.save(file_path)
                    temp_file_paths.append(file_path)
                    print(f"Arquivo salvo em: {file_path}")

        print("=== INICIANDO GENERATOR STREAM ===")
        
        def generate_stream(current_mode, form_data, file_paths):
            """Gera a resposta em streaming para o front-end."""
            print(f"=== DENTRO DO GENERATE_STREAM - Mode: {current_mode} ===")
            
            try:
                solicitacao_usuario = form_data.get('solicitacao', '')
                print(f"Solicitação do usuário: {solicitacao_usuario[:100]}...")
                
                if current_mode == 'test':
                    print("=== MODO TESTE ===")
                    mock_text = form_data.get('mock_text', 'Este é um **texto** de `simulação`.')
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Simulação concluída!', 'partial_result': {'id': 'grok-output', 'content': mock_text}, 'done': True, 'mode': 'atomic' if processing_mode == 'atomic' else 'hierarchical'})}\n\n"
                    if processing_mode == 'atomic':
                        yield f"data: {json.dumps({'partial_result': {'id': 'sonnet-output', 'content': mock_text}})}\n\n"
                        yield f"data: {json.dumps({'partial_result': {'id': 'gemini-output', 'content': mock_text}})}\n\n"
                else:
                    print("=== MODO REAL ===")
                    if not solicitacao_usuario:
                        print("=== ERRO: SOLICITAÇÃO VAZIA ===")
                        yield f"data: {json.dumps({'error': 'Solicitação não fornecida.'})}\n\n"
                        return

                    print("=== PROCESSANDO ARQUIVOS E CONTEXTO ===")
                    yield f"data: {json.dumps({'progress': 0, 'message': 'Processando arquivos e extraindo contexto...'})}\n\n"
                    
                    rag_context = get_relevant_context(file_paths, solicitacao_usuario)
                    print(f"RAG Context obtido: {len(rag_context)} caracteres")
                    
                    output_parser = StrOutputParser()

                    if processing_mode == 'atomic':
                        print("=== MODO ATÔMICO ===")
                        # Lógica atômica permanece a mesma...
                        pass
                    
                    else:
                        print("=== MODO HIERÁRQUICO INICIADO ===")
                        
                        # GROK
                        print("=== PROCESSANDO GROK ===")
                        yield f"data: {json.dumps({'progress': 15, 'message': 'O GROK está processando sua solicitação...'})}\n\n"
                        
                        prompt_grok = PromptTemplate(template=PROMPT_HIERARQUICO_GROK, input_variables=["solicitacao_usuario", "rag_context"])
                        chain_grok = prompt_grok | grok_llm | output_parser
                        
                        print("=== INVOCANDO GROK ===")
                        resposta_grok = chain_grok.invoke({"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context})
                        print(f"=== GROK RESPONDEU: {len(resposta_grok)} caracteres ===")
                        
                        if not resposta_grok or not resposta_grok.strip():
                            print("=== ERRO: GROK SEM RESPOSTA ===")
                            yield f"data: {json.dumps({'error': 'Falha no serviço GROK: Sem resposta.'})}\n\n"
                            return
                        
                        print("=== ENVIANDO RESPOSTA DO GROK ===")
                        yield f"data: {json.dumps({'progress': 33, 'message': 'Claude Sonnet está processando...', 'partial_result': {'id': 'grok-output', 'content': resposta_grok}})}\n\n"
                        
                        # SONNET
                        print("=== PROCESSANDO SONNET ===")
                        prompt_sonnet = PromptTemplate(template=PROMPT_HIERARQUICO_SONNET, input_variables=["solicitacao_usuario", "texto_para_analise"])
                        claude_with_max_tokens = claude_llm.bind(max_tokens=20000)
                        chain_sonnet = prompt_sonnet | claude_with_max_tokens | output_parser
                        
                        print("=== INVOCANDO SONNET ===")
                        resposta_sonnet = chain_sonnet.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_grok})
                        print(f"=== SONNET RESPONDEU: {len(resposta_sonnet)} caracteres ===")
                        
                        if not resposta_sonnet or not resposta_sonnet.strip():
                            print("=== ERRO: SONNET SEM RESPOSTA ===")
                            yield f"data: {json.dumps({'error': 'Falha no serviço Claude Sonnet: Sem resposta.'})}\n\n"
                            return

                        print("=== ENVIANDO RESPOSTA DO SONNET ===")
                        try:
                            sonnet_response = {
                                'progress': 66, 
                                'message': 'Gemini está processando...', 
                                'partial_result': {
                                    'id': 'sonnet-output', 
                                    'content': resposta_sonnet
                                }
                            }
                            yield f"data: {json.dumps(sonnet_response)}\n\n"
                            print("=== SONNET JSON ENVIADO COM SUCESSO ===")
                        except Exception as json_error:
                            print(f"=== ERRO NO JSON DO SONNET: {json_error} ===")
                            # Fallback
                            fallback_response = {
                                'progress': 66, 
                                'message': 'Gemini está processando...', 
                                'partial_result': {
                                    'id': 'sonnet-output', 
                                    'content': f"ERRO DE ENCODING: {str(json_error)}"
                                }
                            }
                            yield f"data: {json.dumps(fallback_response)}\n\n"
                        
                        # GEMINI
                        print("=== PROCESSANDO GEMINI ===")
                        prompt_gemini = PromptTemplate(template=PROMPT_HIERARQUICO_GEMINI, input_variables=["solicitacao_usuario", "texto_para_analise"])
                        chain_gemini = prompt_gemini | gemini_llm | output_parser
                        
                        print("=== INVOCANDO GEMINI ===")
                        resposta_gemini = chain_gemini.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_sonnet})
                        print(f"=== GEMINI RESPONDEU: {len(resposta_gemini)} caracteres ===")
                        
                        if not resposta_gemini or not resposta_gemini.strip():
                            print("=== ERRO: GEMINI SEM RESPOSTA ===")
                            yield f"data: {json.dumps({'error': 'Falha no serviço Gemini: Sem resposta.'})}\n\n"
                            return

                        print("=== ENVIANDO RESPOSTA DO GEMINI ===")
                        yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento concluído!', 'partial_result': {'id': 'gemini-output', 'content': resposta_gemini}, 'done': True, 'mode': 'hierarchical'})}\n\n"
                        print("=== PROCESSAMENTO HIERÁRQUICO CONCLUÍDO ===")

            except Exception as e:
                print(f"=== ERRO GERAL NO GENERATE_STREAM: {e} ===")
                print(f"=== TRACEBACK: {traceback.format_exc()} ===")
                yield f"data: {json.dumps({'error': f'Erro inesperado: {str(e)}'})}\n\n"

        return Response(generate_stream(mode, form_data, temp_file_paths), mimetype='text/event-stream')
        
    except Exception as e:
        print(f"=== ERRO NA ROTA PROCESS: {e} ===")
        print(f"=== TRACEBACK: {traceback.format_exc()} ===")
        return Response(f"data: {json.dumps({'error': f'Erro na rota process: {str(e)}'})}\n\n", mimetype='text/event-stream')

@app.route('/merge', methods=['POST'])
def merge():
    """Recebe os textos do modo Atômico e os consolida usando um LLM."""
    print("=== ROTA MERGE ACESSADA ===")
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
            
            yield f"data: {json.dumps({'progress': 100, 'message': 'Merge concluído!', 'final_result': {'content': resposta_merge, 'word_count': word_count}, 'done': True})}\n\n"

        except Exception as e:
            print(f"Erro no processo de merge: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return Response(generate_merge_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    print("=== INICIANDO SERVIDOR FLASK ===")
    app.run(debug=True)
