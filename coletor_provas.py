import requests
from bs4 import BeautifulSoup
import json
import os
import logging
import time
import fitz  # PyMuPDF
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Configurações ─────────────────────────────────────────────────────────────
URL_ENEM = "https://raw.githubusercontent.com/dombelini/enem-questions/master/data/enem.json"
URL_UECE_RAIZ = "https://www.cev.uece.br/home/home/concursos-servicos/encerrados/vestibulares/vestibular-uece/"
BASE_URL_UECE = "https://www.cev.uece.br"
BANCO_DIR = Path("banco_provas")

# ── Modelo de Dados ───────────────────────────────────────────────────────────
@dataclass
class Questao:
    id_unico: str
    vestibular: str
    ano: Optional[str]
    disciplina: str
    area: str
    nivel: str
    enunciado: str
    alternativas: Optional[list]
    resposta_correta: Optional[str]

def inferir_area(disciplina: str) -> str:
    disc = disciplina.lower()
    if any(x in disc for x in ["história", "sociologia", "filosofia", "geografia", "humanas"]):
        return "ciencias_humanas"
    if any(x in disc for x in ["biologia", "física", "química", "natureza"]):
        return "ciencias_natureza"
    return "outras"

def salvar_questao(q: Questao) -> bool:
    pasta = BANCO_DIR / q.area / q.vestibular.lower()
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "questoes.json"
    
    dados = []
    if arquivo.exists():
        with open(arquivo, 'r', encoding='utf-8') as f:
            dados = json.load(f)
            
    if any(item["id_unico"] == q.id_unico for item in dados):
        return False
        
    dados.append(asdict(q))
    with open(arquivo, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)
    return True

# ── Processamento ENEM ────────────────────────────────────────────────────────
def processar_enem():
    log.info("Iniciando captura do ENEM...")
    try:
        r = requests.get(URL_ENEM, timeout=25)
        r.raise_for_status()
        questoes = r.json()
        inseridas = 0
        for q in questoes[:100]: # Limite inicial para não sobrecarregar
            disc = q.get("disciplina") or "História"
            area = inferir_area(disc)
            if area == "ciencias_humanas":
                obj = Questao(
                    id_unico=f"ENEM_{q.get('ano')}_{q.get('id')}",
                    vestibular="ENEM",
                    ano=str(q.get("ano")),
                    disciplina=disc,
                    area=area,
                    nivel="Médio",
                    enunciado=q.get("enunciado", ""),
                    alternativas=q.get("alternativas"),
                    resposta_correta=q.get("gabarito")
                )
                if salvar_questao(obj):
                    inseridas += 1
        log.info(f"ENEM concluído: {inseridas} novas questões salvas.")
    except Exception as e:
        log.error(f"Erro ao processar ENEM: {e}")

# ── Processamento UECE ────────────────────────────────────────────────────────
def extrair_texto_pdf(url_pdf, nome_prova):
    try:
        r = requests.get(url_pdf, timeout=30)
        temp_pdf = "temp_uece.pdf"
        with open(temp_pdf, "wb") as f:
            f.write(r.content)
            
        doc = fitz.open(temp_pdf)
        texto_acumulado = ""
        for pagina in doc:
            texto_acumulado += pagina.get_text()
        doc.close()
        os.remove(temp_pdf)
        
        # Cria um registro da prova no banco (MVP de extração)
        obj = Questao(
            id_unico=f"UECE_{nome_prova[:10].replace(' ', '_')}",
            vestibular="UECE",
            ano="2024", # Pode ser extraído do nome da pasta no futuro
            disciplina=nome_prova,
            area="ciencias_humanas",
            nivel="Difícil",
            enunciado=texto_acumulado[:1500] + "...", # Amostra do conteúdo
            alternativas=[],
            resposta_correta="Consultar PDF Oficial"
        )
        salvar_questao(obj)
        log.info(f"Sucesso ao processar PDF: {nome_prova}")
    except Exception as e:
        log.error(f"Erro na extração do PDF UECE: {e}")

def processar_uece():
    log.info("Explorando portal CEV/UECE...")
    try:
        r = requests.get(URL_UECE_RAIZ)
        soup = BeautifulSoup(r.text, "html.parser")
        
        links_vestibulares = []
        for a in soup.find_all("a", href=True):
            if "vestibular" in a["href"].lower():
                url = a["href"] if a["href"].startswith("http") else BASE_URL_UECE + a["href"]
                links_vestibulares.append(url)
        
        # Analisa as 3 pastas mais recentes
        for pasta_url in list(set(links_vestibulares))[:3]:
            log.info(f"Entrando na pasta: {pasta_url}")
            r_p = requests.get(pasta_url)
            soup_p = BeautifulSoup(r_p.text, "html.parser")
            
            for link_pdf in soup_p.find_all("a", href=True):
                nome = link_pdf.text.lower()
                href = link_pdf["href"]
                # Filtra apenas Gabarito 1 de Sociologia ou História
                if ".pdf" in href and "gabarito 1" in nome:
                    if "sociologia" in nome or "história" in nome:
                        pdf_full_url = href if href.startswith("http") else BASE_URL_UECE + href
                        extrair_texto_pdf(pdf_full_url, nome)
    except Exception as e:
        log.error(f"Erro ao navegar na UECE: {e}")

# ── Execução Principal ────────────────────────────────────────────────────────
if __name__ == "__main__":
    processar_enem()
    processar_uece()
    log.info("Todos os processos foram finalizados.")
