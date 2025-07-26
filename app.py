# app.py

from flask import Flask, render_template, request, Response
import markdown2
import json
import time
import os
import uuid

# Importações do LangChain
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

# Importa os LLMs
from llms import claude_llm, grok_llm, gemini_llm

# Importa os prompts
from config import PROMPT_CLAUDE_SONNET, PROMPT_GROK, PROMPT_GEMINI

# Importa nosso processador RAG
from rag_processor import get_relevant_context

app = Flask(__name__)

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 

# A linha 'os.makedirs('uploads')' foi removida daqui, pois agora é gerenciada pelo Dockerfile.

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    form_data = request.form
    files = request.files.getlist('files')
    mode = form_data.get('mode', 'real')
    
    temp_file_paths = []
    if mode == 'real':
        for file in files:
            if file and file.filename:
                unique_filename = str(uuid.uuid4()) + "_" + file.filename
                file_path = os.path.join('uploads', unique_filename)
                file.save(file_path)
                temp_file_paths.append(file_path)

    def generate_stream(current_mode, form_data, file_paths):
        if current_mode == 'test':
            mock_text = form_data.get('mock_text', 'Este é um texto de simulação.')
            mock_html = markdown2.markdown(mock_text, extras=["fenced-code-blocks", "tables"])
            
            # --- CORREÇÃO APLICADA AQUI ---
            yield f"data: {json.dumps({'progress': 0, 'message': 'Simulando Etapa 1: GROK...'})}\n\n"
            time.sleep(1)
            # O primeiro resultado agora vai corretamente para 'grok-output'
            yield f"data: {json.dumps({'progress': 33, 'message': 'Simulando Etapa 2: Claude Sonnet...', 'partial_result': {'id': 'grok-output', 'content': mock_html}})}\n\n"
            time.sleep(1)
            # O segundo resultado agora vai corretamente para 'sonnet-output'
            yield f"data: {json.dumps({'progress': 66, 'message': 'Simulando Etapa 3: Gemini...', 'partial_result': {'id': 'sonnet-output', 'content': mock_html}})}\n\n"
            time.sleep(1)
            yield f"data: {json.dumps({'progress': 100, 'message': 'Simulação concluída!', 'partial_result': {'id': 'gemini-output', 'content': mock_html}, 'done': True})}\n\n"
        
        else:
            solicitacao_usuario = form_data.get('solicitacao', '')
            if not solicitacao_usuario:
                yield f"data: {json.dumps({'error': 'Solicitação não fornecida.'})}\n\n"
                return

            try:
                yield f"data: {json.dumps({'progress': 0, 'message': 'Processando arquivos e extraindo contexto...'})}\n\n"
                rag_context = get_relevant_context(file_paths, solicitacao_usuario)
                
                yield f"data: {json.dumps({'progress': 15, 'message': 'O GROK está processando sua solicitação com os arquivos...'})}\n\n"
                prompt_grok = PromptTemplate(template=PROMPT_GROK, input_variables=["solicitacao_usuario", "rag_context"])
                chain_grok = LLMChain(llm=grok_llm, prompt=prompt_grok)
                resposta_grok = chain_grok.invoke({"solicitacao_usuario": solicitacao_usuario, "rag_context": rag_context})['text']
                grok_html = markdown2.markdown(resposta_grok, extras=["fenced-code-blocks", "tables"])
                yield f"data: {json.dumps({'progress': 33, 'message': 'Agora, o Claude Sonnet está aprofundando o texto...', 'partial_result': {'id': 'grok-output', 'content': grok_html}})}\n\n"
                
                prompt_sonnet = PromptTemplate(template=PROMPT_CLAUDE_SONNET, input_variables=["solicitacao_usuario", "texto_para_analise"])
                claude_with_max_tokens = claude_llm.bind(max_tokens=8000)
                chain_sonnet = LLMChain(llm=claude_with_max_tokens, prompt=prompt_sonnet)
                resposta_sonnet = chain_sonnet.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_grok})['text']
                sonnet_html = markdown2.markdown(resposta_sonnet, extras=["fenced-code-blocks", "tables"])
                yield f"data: {json.dumps({'progress': 66, 'message': 'Estamos quase lá! Seu texto está passando por uma revisão final com o Gemini...', 'partial_result': {'id': 'sonnet-output', 'content': sonnet_html}})}\n\n"
                
                prompt_gemini = PromptTemplate(template=PROMPT_GEMINI, input_variables=["solicitacao_usuario", "texto_para_analise"])
                chain_gemini = LLMChain(llm=gemini_llm, prompt=prompt_gemini)
                resposta_gemini = chain_gemini.invoke({"solicitacao_usuario": solicitacao_usuario, "texto_para_analise": resposta_sonnet})['text']
                gemini_html = markdown2.markdown(resposta_gemini, extras=["fenced-code-blocks", "tables"])
                yield f"data: {json.dumps({'progress': 100, 'message': 'Processamento concluído!', 'partial_result': {'id': 'gemini-output', 'content': gemini_html}, 'done': True})}\n\n"

            except Exception as e:
                print(f"Ocorreu um erro durante o processamento: {e}")
                yield f"data: {json.dumps({'error': f'Ocorreu um erro inesperado na aplicação: {e}'})}\n\n"

    return Response(generate_stream(mode, form_data, temp_file_paths), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True)
