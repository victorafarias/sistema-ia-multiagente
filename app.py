# app.py

from flask import Flask, render_template, request, Response, jsonify
import markdown2
import json
import time
import os
import uuid
import threading # Necessário para o processamento em paralelo

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

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    form_data = request.form
    files = request.files.getlist('files')
    mode = form_data.get('mode', 'real')
    processing_mode = form_data.get('processing_mode', 'hierarchical')
    
    temp_file_paths = []
    if mode == 'real':
        for file in files:
            if file and file.filename:
                unique_filename = str(uuid.uuid4()) + "_" + file.filename
                file_path = os.path.join('uploads', unique_filename)
                file.save(file_path)
                temp_file_paths.append(file_path)

    def generate_stream(current_mode, form_data, file_paths):
        solicitacao_usuario = form_data.get('solicitacao', '')
        
        if current_mode == 'test':
            # Lógica de simulação (simplificada para focar na lógica real)
            mock_text = form_data.get('mock_text', 'Este é um texto de simulação.')
            mock_html = markdown2.markdown(mock_text, extras=["fenced-code-blocks", "tables"])
            yield f"data: {json.dumps({'progress': 100, 'message': 'Simulação concluída!', 'partial_result': {'id': 'grok-output', 'content': mock_html}, 'done': True, 'mode': 'atomic' if processing_mode == 'atomic' else 'hierarchical'})}\n\n"
        
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

                    def run_chain(chain, inputs, key):
                        try:
                            results[key] = chain.invoke(inputs)['text']
                        except Exception as e:
                            results[key] = f"Erro ao processar {key}: {e}"

                    # Configurar e iniciar threads
                    models = {'grok': grok_llm, 'sonnet': claude_llm, 'gemini': gemini_llm}
                    prompt = PromptTemplate(template=PROMPT_ATOMICO_INICIAL, input_variables=["solicitacao_usuario", "rag_context"])
                    
                    for name, llm in models.items():
                        chain = LLMChain(llm=llm, prompt=prompt)
                        thread = threading.Thread(target=run_chain, args=(chain, {"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context}, name))
                        threads.append(thread)
                        thread.start()

                    # Monitorar e enviar resultados conforme chegam
                    completed_threads = 0
                    while completed_threads < len(threads):
                        for i, thread in enumerate(threads):
                            key = list(models.keys())[i]
                            if not thread.is_alive() and key not in results:
                                # Se a thread terminou mas não há resultado, algo deu errado
                                results[key] = f"Falha na thread para {key}."

                            if key in results:
                                html_content = markdown2.markdown(results[key], extras=["fenced-code-blocks", "tables"])
                                yield f"data: {json.dumps({'progress': int((len(results)/len(threads))*100), 'message': f'Modelo {key.upper()} concluiu.', 'partial_result': {'id': f'{key}-output', 'content': html_content}})}\n\n"
                                threads.pop(i) # Remove para não processar de novo
                                completed_threads += 1
                        time.sleep(1)
                    
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento Atômico concluído!', 'done': True, 'mode': 'atomic'})}\n\n"

                else:
                    # --- LÓGICA HIERÁRQUICA (SEQUENCIAL) ---
                    # (Mesma lógica de antes, com nomes de prompts atualizados)
                    yield f"data: {json.dumps({'progress': 15, 'message': 'O GROK está processando sua solicitação com os arquivos...'})}\n\n"
                    prompt_grok = PromptTemplate(template=PROMPT_HIERARQUICO_GROK, input_variables=["solicitacao_usuario", "rag_context"])
                    chain_grok = LLMChain(llm=grok_llm, prompt=prompt_grok)
                    resposta_grok = chain_grok.invoke({"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context})['text']
                    if not resposta_grok or not resposta_grok.strip(): raise ValueError("Falha no serviço GROK: Sem resposta.")
                    grok_html = markdown2.markdown(resposta_grok, extras=["fenced-code-blocks", "tables"])
                    yield f"data: {json.dumps({'progress': 33, 'message': 'Agora, o Claude Sonnet está aprofundando o texto...', 'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"
                    
                    prompt_sonnet = PromptTemplate(template=PROMPT_HIERARQUICO_SONNET, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    claude_with_max_tokens = claude_llm.bind(max_tokens=8000)
                    chain_sonnet = LLMChain(llm=claude_with_max_tokens, prompt=prompt_sonnet)
                    resposta_sonnet = chain_sonnet.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_grok})['text']
                    if not resposta_sonnet or not resposta_sonnet.strip(): raise ValueError("Falha no serviço Claude Sonnet: Sem resposta.")
                    sonnet_html = markdown2.markdown(resposta_sonnet, extras=["fenced-code-blocks", "tables"])
                    yield f"data: {json.dumps({'progress': 66, 'message': 'Estamos quase lá! Seu texto está passando por uma revisão final com o Gemini...', 'partial_result': {'id': 'sonnet-output', 'content': sonnet_html}})}\n\n"
                    
                    prompt_gemini = PromptTemplate(template=PROMPT_HIERARQUICO_GEMINI, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    chain_gemini = LLMChain(llm=gemini_llm, prompt=prompt_gemini)
                    resposta_gemini = chain_gemini.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_sonnet})['text']
                    if not resposta_gemini or not resposta_gemini.strip(): raise ValueError("Falha no serviço Gemini: Sem resposta.")
                    gemini_html = markdown2.markdown(resposta_gemini, extras=["fenced-code-blocks", "tables"])
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento concluído!', 'partial_result': {'id': 'gemini-output', 'content': gemini_html}, 'done': True, 'mode': 'hierarchical'})}\n\n"

            except Exception as e:
                print(f"Ocorreu um erro durante o processamento: {e}")
                yield f"data: {json.dumps({'error': f'Ocorreu um erro inesperado na aplicação: {e}'})}\n\n"

    return Response(generate_stream(mode, form_data, temp_file_paths), mimetype='text/event-stream')

# --- NOVA ROTA PARA O MERGE ---
@app.route('/merge', methods=['POST'])
def merge():
    data = request.get_json()
    try:
        # Cria o prompt e a chain para o merge
        prompt_merge = PromptTemplate(template=PROMPT_ATOMICO_MERGE, input_variables=["solicitacao_usuario", "texto_para_analise_grok", "texto_para_analise_sonnet", "texto_para_analise_gemini"])
        
        # O merge será feito pelo Claude Sonnet com limite de tokens alto
        claude_with_max_tokens = claude_llm.bind(max_tokens=8000)
        chain_merge = LLMChain(llm=claude_with_max_tokens, prompt=prompt_merge)

        # Invoca a chain com os dados recebidos
        resposta_merge = chain_merge.invoke({
            "solicitacao_usuario": data.get('solicitacao_usuario'),
            "texto_para_analise_grok": data.get('grok_text'),
            "texto_para_analise_sonnet": data.get('sonnet_text'),
            "texto_para_analise_gemini": data.get('gemini_text')
        })['text']
        
        if not resposta_merge or not resposta_merge.strip():
            raise ValueError("Falha no serviço de Merge (Claude Sonnet): Sem resposta.")
        
        # Retorna o resultado como HTML
        merge_html = markdown2.markdown(resposta_merge, extras=["fenced-code-blocks", "tables"])
        return jsonify({"success": True, "content": merge_html})

    except Exception as e:
        print(f"Erro no processo de merge: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
