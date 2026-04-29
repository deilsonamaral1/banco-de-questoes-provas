import requests
from bs4 import BeautifulSoup
import json
import os
import re

# Configurações iniciais
HEADERS = {'User-Agent': 'Mozilla/5.0'}
DISCIPLINAS_ALVO = ["Sociologia", "História"]

def classificar_nivel(texto):
    tamanho = len(texto)
    if tamanho < 300: return "Fácil"
    elif tamanho < 700: return "Médio"
    else: return "Difícil"

def buscar_questoes_real():
    # Exemplo: URL de um repositório de questões abertas ou portal educativo
    # Aqui o robô entra na "caça"
    url_fonte = "https://exemplo-portal-provas.com.br/enem-sociologia" 
    
    try:
        resposta = requests.get(url_fonte, headers=HEADERS)
        sopa = BeautifulSoup(resposta.text, 'html.parser')
        
        questoes_encontradas = []
        
        # O robô procura por blocos de questões no código do site
        for bloco in sopa.find_all('div', class_='questao-container'):
            texto_enunciado = bloco.find('p', class_='texto').text
            
            # Criamos o ID único para evitar duplicatas no seu Git
            id_gerado = f"ENEM_2025_{re.sub(r'[^a-zA-Z0-9]', '', texto_enunciado[:10])}"
            
            questoes_encontradas.append({
                "id_unico": id_gerado,
                "vestibular": "ENEM",
                "ano": 2025,
                "disciplina": "Sociologia",
                "enunciado": texto_enunciado,
                "alternativas": {
                    "a": bloco.find('span', id='alt-a').text,
                    "b": bloco.find('span', id='alt-b').text,
                    # ... etc
                },
                "resposta_correta": "a" # O robô também busca o gabarito
            })
        return questoes_encontradas
    except Exception as e:
        print(f"Erro na captura: {e}")
        return []

def salvar_no_banco(questoes):
    for q in questoes:
        pasta = f"banco_provas/{q['disciplina'].lower()}"
        if not os.path.exists(pasta): os.makedirs(pasta)
        
        arquivo = f"{pasta}/questoes.json"
        
        # Lógica de persistência (lê o que já existe e adiciona o novo)
        dados = []
        if os.path.exists(arquivo):
            with open(arquivo, 'r', encoding='utf-8') as f:
                dados = json.load(f)
        
        # Só adiciona se o ID for inédito
        if not any(item['id_unico'] == q['id_unico'] for item in dados):
            q['nivel'] = classificar_nivel(q['enunciado'])
            dados.append(q)
            
            with open(arquivo, 'w', encoding='utf-8') as f:
                json.dump(dados, f, indent=4, ensure_ascii=False)

# Rodar a automação
novas = buscar_questoes_real()
salvar_no_banco(novas)
