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
MAX_PASTAS_UECE = 3 # Reduzido para ser mais rápido no teste

# ── Modelo ────────────────────────────────────────────────────────────────────
@dataclass
class Questao:
    id_unico: str
    vestibular: str
    ano: Optional[int]
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
    dados = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
    if any(item["id_unico"] == q.id_unico for item in dados): return False
    dados.append(asdict(q))
    arquivo.write_text(json.dumps(dados, indent=4, ensure_ascii=False), encoding="utf-8")
    return True

# ── ENEM ──────────────────────────────────────────────────────────────────────
def processar_enem():
    log.info("Puxando questões do ENEM...")
    try:
        r = requests.get(URL_ENEM, timeout=20)
        r.raise_for_status()
        questoes = r.json()
        inseridas = 0
        for q in questoes[:100]: # Pegando as 100 primeiras para testar
            disc = q.get("disciplina") or "História"
            area = inferir_area(disc)
            if area == "ciencias_humanas":
                obj = Questao(
                    id_unico=f"ENEM_{q.get('ano')}_{q.get('id')}",
                    vestibular="ENEM", ano=q.get("ano"),
                    disciplina=disc, area=area,
                    nivel="Médio", enunciado=q.get("enunciado", ""),
                    alternativas=q.get("alternativas"),
                    resposta_correta=q.get("gabarito")
                )
                if salvar_questao(obj): inseridas += 1
        log.info(f"ENEM: {inseridas} questões novas.")
    except Exception as e:
        log.error(f"Erro no ENEM: {e}")

# ── UECE (Extração de PDF) ───────────────────────────────────────────────────
def extrair_texto_uece(url_pdf, disciplina, ano):
    try:
        r = requests.get(url_pdf, timeout=30)
        with open("temp.pdf", "wb") as f: f.write(r.content)
        doc = fitz.open("temp.pdf")
        texto_completo = ""
        for pagina in doc: texto_completo += pagina.get_text()
        doc.close()
        
        # Lógica simples de quebra: Procura por "1." ou "Questão 01"
        # Para este MVP, vamos salvar o texto bruto do PDF como uma questão única de referência
        obj = Questao(
            id_unico=f"UECE_{ano}_{disciplina[:3].upper()}",
            vestibular="UECE", ano=ano,
            disciplina=disciplina, area="ciencias_humanas",
            nivel="Difícil", enunciado=texto_completo[:1000] + "...", # Amostra do texto
            alternativas=[], resposta_correta="Ver PDF"
        )
        salvar_questao(obj)
    except Exception as e:
        log.error(f"Erro ao ler PDF UECE: {e}")

def processar_uece():
    log.info("Mapeando UECE...")
    try:
        soup = BeautifulSoup(requests.get(URL_UECE_RAIZ).text, "html.parser")
        pastas = [a["href"] for a in soup.find_all("a", href=True) if "vestibular" in a["href"].lower()]
        for url_p in list(set(pastas))[:MAX_PASTAS_UECE]:
            full_url = url_p if url_p.startswith("http") else BASE_URL_UECE + url_p
            soup_p = BeautifulSoup(requests.get(full_url).text, "html.parser")
            for a in soup_p.find_all("a", href=True):
                nome = a.text.lower()
                if ".pdf" in a["href"] and ("sociologia" in nome or "história" in nome) and "gabarito 1" in nome:
                    pdf_url = a["href"] if a["href"].startswith("http") else BASE_URL_UECE + a["href"]
                    log.info(f"Baixando prova UECE: {nome}")
                    extrair_texto_uece(pdf_url, nome, "2024") # Ano genérico para teste
    except Exception as e:
        log.error(f"Erro na UECE: {e}")

if __name__ == "__main__":
    processar_enem()
    processar_uece()
    log.info("Fim do processo.")
