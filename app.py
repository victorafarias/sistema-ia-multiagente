# app.py

from flask import Flask, render_template, request, Response, jsonify
import markdown2
import json
import time
import os
import uuid
import threading

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
                    results = {}
                    threads = []
                    def run_chain(chain, inputs, key):
                        try: results[key] = chain.invoke(inputs)['text']
                        except Exception as e: results[key] = f"Erro ao processar {key}: {e}"

                    models = {'grok': grok_llm, 'sonnet': claude_llm, 'gemini': gemini_llm}
                    prompt = PromptTemplate(template=PROMPT_ATOMICO_INICIAL, input_variables=["solicitacao_usuario", "rag_context"])
                    yield f"data: {json.dumps({'progress': 15, 'message': 'Iniciando processamento paralelo...'})}\n\n"
                    for name, llm in models.items():
                        chain = LLMChain(llm=llm, prompt=prompt)
                        thread = threading.Thread(target=run_chain, args=(chain, {"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context}, name))
                        threads.append(thread)
                        thread.start()
                    for thread in threads:
                        thread.join()
                    yield f"data: {json.dumps({'progress': 80, 'message': 'Todos os modelos responderam. Formatando saída...'})}\n\n"
                    grok_html = markdown2.markdown(results.get('grok', 'Falha ao obter resposta.'), extras=["fenced-code-blocks", "tables"])
                    yield f"data: {json.dumps({'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"
                    sonnet_html = markdown2.markdown(results.get('sonnet', 'Falha ao obter resposta.'), extras=["fenced-code-blocks", "tables"])
                    yield f"data: {json.dumps({'partial_result': {'id': 'sonnet-output', 'content': sonnet_html}})}\n\n"
                    gemini_html = markdown2.markdown(results.get('gemini', 'Falha ao obter resposta.'), extras=["fenced-code-blocks", "tables"])
                    yield f"data: {json.dumps({'partial_result': {'id': 'gemini-output', 'content': gemini_html}})}\n\n"
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento Atômico concluído!', 'done': True, 'mode': 'atomic'})}\n\n"
                else:
                    yield f"data: {json.dumps({'progress': 15, 'message': 'O GROK está processando sua solicitação com os arquivos...'})}\n\n"
                    prompt_grok = PromptTemplate(template=PROMPT_HIERARQUICO_GROK, input_variables=["solicitacao_usuario", "rag_context"])
                    chain_grok = LLMChain(llm=grok_llm, prompt=prompt_grok)
                    resposta_grok = chain_grok.invoke({"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context})['text']
                    if not resposta_grok or not resposta_grok.strip(): raise ValueError("Falha no serviço GROK: Sem resposta.")
                    grok_html = markdown2.markdown(resposta_grok, extras=["fenced-code-blocks", "tables"])
                    yield f"data: {json.dumps({'progress': 33, 'message': 'Agora, o Claude Sonnet está aprofundando o texto...', 'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"
                    
                    prompt_sonnet = PromptTemplate(template=PROMPT_HIERARQUICO_SONNET, input_variables=["solicitacao_usuario", "texto_para_analise"])
                    claude_with_max_tokens = claude_llm.bind(max_tokens=12000)
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

# --- ROTA DE MERGE ATUALIZADA PARA USAR GROK ---
@app.route('/merge', methods=['POST'])
def merge():
    data = request.get_json()
    
    def generate_merge_stream():
        try:
            yield f"data: {json.dumps({'progress': 0, 'message': 'Iniciando o processo de merge...'})}\n\n"
            
            prompt_merge = PromptTemplate(template=PROMPT_ATOMICO_MERGE, input_variables=["solicitacao_usuario", "texto_para_analise_grok", "texto_para_analise_sonnet", "texto_para_analise_gemini"])
            
            # ATUALIZAÇÃO: O merge agora será feito pelo GROK
            chain_merge = LLMChain(llm=grok_llm, prompt=prompt_merge)

            yield f"data: {json.dumps({'progress': 50, 'message': 'Enviando textos para o GROK para consolidação...'})}\n\n"

            resposta_merge = chain_merge.invoke({
                "solicitacao_usuario": data.get('solicitacao_usuario'),
                "texto_para_analise_grok": data.get('grok_text'),
                "texto_para_analise_sonnet": data.get('sonnet_text'),
                "texto_para_analise_gemini": data.get('gemini_text')
            })['text']
            
            if not resposta_merge or not resposta_merge.strip():
                raise ValueError("Falha no serviço de Merge (GROK): Sem resposta.")
            
            merge_html = markdown2.markdown(resposta_merge, extras=["fenced-code-blocks", "tables"])
            
            yield f"data: {json.dumps({'progress': 100, 'message': 'Merge concluído!', 'final_result': {'content': merge_html}, 'done': True})}\n\n"

        except Exception as e:
            print(f"Erro no processo de merge: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return Response(generate_merge_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True)
