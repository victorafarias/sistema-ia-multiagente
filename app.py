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
import sys

# Força o flush dos prints para aparecer nos logs do container
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

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

# Variável global para controle de interrupção
processing_cancelled = False

def log_print(message):
    """Função para garantir que os logs apareçam no container"""
    print(f"[DEBUG] {message}", flush=True)
    sys.stdout.flush()

def safe_json_dumps(data):
    """Função para criar JSON de forma segura, com tratamento de strings muito grandes"""
    try:
        json_str = json.dumps(data, ensure_ascii=False)
        
        # Se o JSON for muito grande (> 50MB), trunca o conteúdo
        if len(json_str.encode('utf-8')) > 50 * 1024 * 1024:
            log_print(f"JSON muito grande ({len(json_str)} chars), truncando...")
            if 'content' in str(data):
                # Cria uma versão truncada
                truncated_data = data.copy() if isinstance(data, dict) else {}
                if 'final_result' in truncated_data and 'content' in truncated_data['final_result']:
                    original_content = truncated_data['final_result']['content']
                    truncated_content = original_content[:10000] + "\n\n[CONTEÚDO TRUNCADO DEVIDO AO TAMANHO - Use o botão 'Copiar' para obter o texto completo]"
                    truncated_data['final_result']['content'] = truncated_content
                elif 'partial_result' in truncated_data and 'content' in truncated_data['partial_result']:
                    original_content = truncated_data['partial_result']['content']
                    truncated_content = original_content[:10000] + "\n\n[CONTEÚDO TRUNCADO DEVIDO AO TAMANHO - Use o botão 'Copiar' para obter o texto completo]"
                    truncated_data['partial_result']['content'] = truncated_content
                
                return json.dumps(truncated_data, ensure_ascii=False)
        
        return json_str
    except Exception as e:
        log_print(f"Erro ao criar JSON: {e}")
        return json.dumps({'error': f'Erro na serialização JSON: {str(e)}'})

# Variável global para armazenar o conteúdo completo do merge
merge_full_content = ""

# Função para renderização com fallback: tenta MarkdownIt, depois markdown2
def render_markdown_cascata(texto: str) -> str:
    try:
        html_1 = md.render(texto)
        if not is_html_empty(html_1):
            return html_1
    except Exception as e:
        log_print(f"MarkdownIt falhou: {e}")

    try:
        html_2 = markdown2_render(texto, extras=["fenced-code-blocks", "tables"])
        if not is_html_empty(html_2):
            return html_2
    except Exception as e:
        log_print(f"markdown2 falhou: {e}")

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

# ROTA ATUALIZADA: Para converter texto em Markdown sob demanda
@app.route('/convert', methods=['POST'])
def convert():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'Nenhum texto fornecido'}), 400
    
    text_to_convert = data['text']
    # USA A FUNÇÃO DE CASCATA PARA MAIOR ROBUSTEZ
    converted_html = render_markdown_cascata(text_to_convert)
    return jsonify({'html': converted_html})

# NOVA ROTA: Para cancelar processamento
@app.route('/cancel', methods=['POST'])
def cancel():
    global processing_cancelled
    processing_cancelled = True
    log_print("=== PROCESSAMENTO CANCELADO PELO USUÁRIO ===")
    return jsonify({'status': 'cancelled'})

# NOVA ROTA: Para obter o conteúdo completo do merge
@app.route('/get-full-content', methods=['POST'])
def get_full_content():
    global merge_full_content
    data = request.get_json()
    content_type = data.get('type', 'merge')
    
    if content_type == 'merge' and merge_full_content:
        return jsonify({'content': merge_full_content})
    else:
        return jsonify({'error': 'Conteúdo não encontrado'}), 404

@app.route('/process', methods=['POST'])
def process():
    """Processa a solicitação do usuário nos modos Hierárquico ou Atômico."""
    global processing_cancelled
    processing_cancelled = False  # Reset do flag de cancelamento
    
    log_print("=== ROTA PROCESS ACESSADA ===")
    
    form_data = request.form
    files = request.files.getlist('files')
    mode = form_data.get('mode', 'real')
    processing_mode = form_data.get('processing_mode', 'hierarchical')
    
    # NOVOS PARÂMETROS: Tamanho do texto
    min_chars = int(form_data.get('min_chars', 24000))
    max_chars = int(form_data.get('max_chars', 30000))
    
    log_print(f"Mode: {mode}, Processing: {processing_mode}")
    log_print(f"Tamanho solicitado: {min_chars} - {max_chars} caracteres")
    
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
        global processing_cancelled
        
        log_print(f"=== GENERATE_STREAM INICIADO - Mode: {current_mode} ===")
        
        solicitacao_usuario = form_data.get('solicitacao', '')
        
        if current_mode == 'test':
            log_print("=== MODO TESTE EXECUTADO ===")
            mock_text = form_data.get('mock_text', 'Este é um **texto** de `simulação`.')
            json_data = safe_json_dumps({'progress': 100, 'message': 'Simulação concluída!', 'partial_result': {'id': 'grok-output', 'content': mock_text}, 'done': True, 'mode': 'atomic' if processing_mode == 'atomic' else 'hierarchical'})
            yield f"data: {json_data}\n\n"
            if processing_mode == 'atomic':
                json_data = safe_json_dumps({'partial_result': {'id': 'sonnet-output', 'content': mock_text}})
                yield f"data: {json_data}\n\n"
                json_data = safe_json_dumps({'partial_result': {'id': 'gemini-output', 'content': mock_text}})
                yield f"data: {json_data}\n\n"
        else:
            if not solicitacao_usuario:
                log_print("=== ERRO: SOLICITAÇÃO VAZIA ===")
                json_data = safe_json_dumps({'error': 'Solicitação não fornecida.'})
                yield f"data: {json_data}\n\n"
                return

            try:
                log_print("=== INICIANDO PROCESSAMENTO REAL ===")
                json_data = safe_json_dumps({'progress': 0, 'message': 'Processando arquivos e extraindo contexto...'})
                yield f"data: {json_data}\n\n"
                rag_context = get_relevant_context(file_paths, solicitacao_usuario)
                log_print(f"=== RAG CONTEXT OBTIDO: {len(rag_context)} chars ===")
                
                output_parser = StrOutputParser()

                if processing_mode == 'atomic':
                    log_print("=== MODO ATÔMICO SELECIONADO ===")
                    # --- LÓGICA ATÔMICA (PARALELA) ---
                    results = {}
                    threads = []
                    
                    def run_chain_with_timeout(chain, inputs, key, timeout=300):
                        def task():
                            if processing_cancelled:
                                return "CANCELLED"
                            return chain.invoke(inputs)
                        
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(task)
                            try:
                                result = future.result(timeout=timeout)
                                if result == "CANCELLED":
                                    results[key] = "CANCELLED"
                                elif not result or not result.strip():
                                    results[key] = "Error:EmptyResponse"
                                else:
                                    results[key] = result
                            except concurrent.futures.TimeoutError:
                                results[key] = f"Erro ao processar {key.upper()}: Tempo limite excedido."
                            except Exception as e:
                                results[key] = f"Erro ao processar {key.upper()}: {e}"

                    claude_atomic_llm = claude_llm.bind(max_tokens=20000)
                    models = {'grok': grok_llm, 'sonnet': claude_atomic_llm, 'gemini': gemini_llm}
                    
                    # Substituir os placeholders no template
                    updated_prompt_template = PROMPT_ATOMICO_INICIAL.replace(
                        "MIN_CHARS_PLACEHOLDER", str(min_chars)
                    ).replace(
                        "MAX_CHARS_PLACEHOLDER", str(max_chars)
                    )
                    
                    prompt = PromptTemplate(template=updated_prompt_template, input_variables=["solicitacao_usuario", "rag_context"])
                    json_data = safe_json_dumps({'progress': 15, 'message': 'Iniciando processamento paralelo...'})
                    yield f"data: {json_data}\n\n"
                    
                    for name, llm in models.items():
                        if processing_cancelled:
                            json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                            yield f"data: {json_data}\n\n"
                            return
                            
                        chain = prompt | llm | output_parser
                        thread = threading.Thread(target=run_chain_with_timeout, args=(chain, {"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context}, name))
                        threads.append(thread)
                        thread.start()

                    for thread in threads:
                        thread.join()
                    
                    # Verificar se foi cancelado
                    if processing_cancelled or any(result == "CANCELLED" for result in results.values()):
                        json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    for key, result in results.items():
                        if result == "Error:EmptyResponse" or "Erro ao processar" in result:
                            error_msg = result if "Erro ao processar" in result else f"Falha no serviço {key.upper()}: Sem resposta."
                            json_data = safe_json_dumps({'error': error_msg})
                            yield f"data: {json_data}\n\n"
                            return

                    json_data = safe_json_dumps({'progress': 80, 'message': 'Todos os modelos responderam. Formatando saídas...'})
                    yield f"data: {json_data}\n\n"
                    
                    # MUDANÇA: Envia o texto bruto para cada modelo
                    grok_text = results.get('grok', '')
                    log_print(f"--- Resposta Bruta do GROK (Atômico) ---\n{grok_text[:200]}...\n--------------------------------------")
                    json_data = safe_json_dumps({'partial_result': {'id': 'grok-output', 'content': grok_text}})
                    yield f"data: {json_data}\n\n"

                    sonnet_text = results.get('sonnet', '')
                    log_print(f"--- Resposta Bruta do Sonnet (Atômico) ---\n{sonnet_text[:200]}...\n----------------------------------------")
                    json_data = safe_json_dumps({'partial_result': {'id': 'sonnet-output', 'content': sonnet_text}})
                    yield f"data: {json_data}\n\n"

                    gemini_text = results.get('gemini', '')
                    log_print(f"--- Resposta Bruta do Gemini (Atômico) ---\n{gemini_text[:200]}...\n----------------------------------------")
                    json_data = safe_json_dumps({'partial_result': {'id': 'gemini-output', 'content': gemini_text}})
                    yield f"data: {json_data}\n\n"
                    
                    json_data = safe_json_dumps({'progress': 100, 'message': 'Processamento Atômico concluído!', 'done': True, 'mode': 'atomic'})
                    yield f"data: {json_data}\n\n"
                
                else:
                    log_print("=== MODO HIERÁRQUICO SELECIONADO ===")
                    # --- LÓGICA HIERÁRQUICA (SEQUENCIAL) ---
                    
                    # Atualizar prompts hierárquicos com parâmetros de tamanho
                    updated_grok_template = PROMPT_HIERARQUICO_GROK.replace(
                        "MIN_CHARS_PLACEHOLDER", str(min_chars)
                    ).replace(
                        "MAX_CHARS_PLACEHOLDER", str(max_chars)
                    )
                    
                    updated_sonnet_template = PROMPT_HIERARQUICO_SONNET.replace(
                        "MIN_CHARS_PLACEHOLDER", str(min_chars)
                    ).replace(
                        "MAX_CHARS_PLACEHOLDER", str(max_chars)
                    )
                    
                    updated_gemini_template = PROMPT_HIERARQUICO_GEMINI.replace(
                        "MIN_CHARS_PLACEHOLDER", str(min_chars)
                    ).replace(
                        "MAX_CHARS_PLACEHOLDER", str(max_chars)
                    )
                    
                    json_data = safe_json_dumps({'progress': 15, 'message': 'O GROK está processando sua solicitação...'})
                    yield f"data: {json_data}\n\n"
                    
                    if processing_cancelled:
                        json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    log_print("=== PROCESSANDO GROK ===")
                    prompt_grok = PromptTemplate(template=updated_grok_template, input_variables=["solicitacao_usuario", "rag_context"])
                    chain_grok = prompt_grok | grok_llm | output_parser
                    resposta_grok = chain_grok.invoke({"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context})
                    
                    log_print(f"=== GROK TERMINOU: {len(resposta_grok)} chars ===")
                    
                    if processing_cancelled:
                        json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    if not resposta_grok or not resposta_grok.strip():
                        log_print("=== ERRO: GROK VAZIO ===")
                        json_data = safe_json_dumps({'error': 'Falha no serviço GROK: Sem resposta.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    log_print("=== ENVIANDO RESPOSTA GROK PARA FRONTEND ===")
                    json_data = safe_json_dumps({'progress': 33, 'message': 'Claude Sonnet está processando...', 'partial_result': {'id': 'grok-output', 'content': resposta_grok}})
                    yield f"data: {json_data}\n\n"
                    
                    if processing_cancelled:
                        json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    log_print("=== PROCESSANDO SONNET ===")
                    prompt_sonnet = PromptTemplate(template=updated_sonnet_template, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    claude_with_max_tokens = claude_llm.bind(max_tokens=20000)
                    chain_sonnet = prompt_sonnet | claude_with_max_tokens | output_parser
                    resposta_sonnet = chain_sonnet.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_grok})
                    
                    log_print(f"=== SONNET TERMINOU: {len(resposta_sonnet)} chars ===")
                    
                    if processing_cancelled:
                        json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    if not resposta_sonnet or not resposta_sonnet.strip():
                        log_print("=== ERRO: SONNET VAZIO ===")
                        json_data = safe_json_dumps({'error': 'Falha no serviço Claude Sonnet: Sem resposta.'})
                        yield f"data: {json_data}\n\n"
                        return

                    log_print("=== ENVIANDO RESPOSTA SONNET ===")
                    json_data = safe_json_dumps({'progress': 66, 'message': 'Gemini está processando...', 'partial_result': {'id': 'sonnet-output', 'content': resposta_sonnet}})
                    yield f"data: {json_data}\n\n"
                    
                    if processing_cancelled:
                        json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    log_print("=== PROCESSANDO GEMINI ===")
                    prompt_gemini = PromptTemplate(template=updated_gemini_template, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    chain_gemini = prompt_gemini | gemini_llm | output_parser
                    resposta_gemini = chain_gemini.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_sonnet})
                    
                    log_print(f"=== GEMINI TERMINOU: {len(resposta_gemini)} chars ===")
                    
                    if processing_cancelled:
                        json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                        yield f"data: {json_data}\n\n"
                        return
                    
                    if not resposta_gemini or not resposta_gemini.strip():
                        log_print("=== ERRO: GEMINI VAZIO ===")
                        json_data = safe_json_dumps({'error': 'Falha no serviço Gemini: Sem resposta.'})
                        yield f"data: {json_data}\n\n"
                        return

                    log_print("=== ENVIANDO RESPOSTA GEMINI ===")
                    json_data = safe_json_dumps({'progress': 100, 'message': 'Processamento concluído!', 'partial_result': {'id': 'gemini-output', 'content': resposta_gemini}, 'done': True, 'mode': 'hierarchical'})
                    yield f"data: {json_data}\n\n"
                    log_print("=== PROCESSAMENTO COMPLETO ===")

            except Exception as e:
                log_print(f"Ocorreu um erro durante o processamento: {e}")
                import traceback
                log_print(f"Traceback: {traceback.format_exc()}")
                json_data = safe_json_dumps({'error': f'Ocorreu um erro inesperado na aplicação: {e}'})
                yield f"data: {json_data}\n\n"

    return Response(generate_stream(mode, form_data, temp_file_paths), mimetype='text/event-stream')

@app.route('/merge', methods=['POST'])
def merge():
    """Recebe os textos do modo Atômico e os consolida usando Claude Sonnet."""
    global merge_full_content, processing_cancelled
    processing_cancelled = False  # Reset do flag
    
    data = request.get_json()
    log_print("=== ROTA MERGE ACESSADA ===")
    log_print("=== USANDO CLAUDE SONNET PARA MERGE ===")
    
    def generate_merge_stream():
        """Gera a resposta do merge em streaming."""
        global merge_full_content, processing_cancelled
        
        try:
            log_print("=== INICIANDO MERGE STREAM ===")
            json_data = safe_json_dumps({'progress': 0, 'message': 'Iniciando o processo de merge...'})
            yield f"data: {json_data}\n\n"
            
            if processing_cancelled:
                json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                yield f"data: {json_data}\n\n"
                return
            
            output_parser = StrOutputParser()
            
            # Atualizar o template de merge com os parâmetros de tamanho padrão
            updated_merge_template = PROMPT_ATOMICO_MERGE.replace(
                "MIN_CHARS_PLACEHOLDER", "24000"
            ).replace(
                "MAX_CHARS_PLACEHOLDER", "30000"
            )
            
            prompt_merge = PromptTemplate(template=updated_merge_template, input_variables=["solicitacao_usuario", "texto_para_analise_grok", "texto_para_analise_sonnet", "texto_para_analise_gemini"])
            
            # MUDANÇA: Usar Claude Sonnet para o merge
            claude_with_max_tokens = claude_llm.bind(max_tokens=64000)
            chain_merge = prompt_merge | claude_with_max_tokens | output_parser

            json_data = safe_json_dumps({'progress': 50, 'message': 'Enviando textos para o Claude Sonnet para consolidação...'})
            yield f"data: {json_data}\n\n"
            log_print("=== INVOCANDO CLAUDE SONNET PARA MERGE ===")

            if processing_cancelled:
                json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                yield f"data: {json_data}\n\n"
                return

            resposta_merge = chain_merge.invoke({
                "solicitacao_usuario": data.get('solicitacao_usuario'),
                "texto_para_analise_grok": data.get('grok_text'),
                "texto_para_analise_sonnet": data.get('sonnet_text'),
                "texto_para_analise_gemini": data.get('gemini_text')
            })
            
            log_print(f"=== MERGE CLAUDE SONNET CONCLUÍDO: {len(resposta_merge)} chars ===")
            
            if processing_cancelled:
                json_data = safe_json_dumps({'error': 'Processamento cancelado pelo usuário.'})
                yield f"data: {json_data}\n\n"
                return
            
            if not resposta_merge or not resposta_merge.strip():
                json_data = safe_json_dumps({'error': 'Falha no serviço de Merge (Claude Sonnet): Sem resposta.'})
                yield f"data: {json_data}\n\n"
                return
            
            # Armazena o conteúdo completo na variável global
            merge_full_content = resposta_merge
            word_count = len(resposta_merge.split())
            
            log_print(f"=== CRIANDO JSON DE RESPOSTA DO MERGE ===")
            # Usa a função safe para evitar problemas com JSON muito grande
            json_data = safe_json_dumps({
                'progress': 100, 
                'message': 'Merge concluído!', 
                'final_result': {
                    'content': resposta_merge, 
                    'word_count': word_count
                }, 
                'done': True
            })
            
            log_print(f"=== JSON CRIADO: {len(json_data)} chars ===")
            yield f"data: {json_data}\n\n"
            log_print("=== MERGE STREAM FINALIZADO ===")

        except Exception as e:
            log_print(f"Erro no processo de merge: {e}")
            import traceback
            log_print(f"Traceback: {traceback.format_exc()}")
            json_data = safe_json_dumps({'error': str(e)})
            yield f"data: {json_data}\n\n"
            
    return Response(generate_merge_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    log_print("=== SERVIDOR FLASK INICIADO ===")
    app.run(debug=True)
