import requests
from bs4 import BeautifulSoup
import json
import os
import logging
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configurações ─────────────────────────────────────────────────────────────
URL_ENEM = "[https://raw.githubusercontent.com/dombelini/enem-questions/master/data/enem.json](https://raw.githubusercontent.com/dombelini/enem-questions/master/data/enem.json)"
URL_UECE_RAIZ = "https://www.cev.uece.br/home/home/concursos-servicos/encerrados/vestibulares/vestibular-uece/"
BASE_URL_UECE = "https://www.cev.uece.br"
BANCO_DIR = Path("banco_provas")
TIMEOUT = 15
DELAY_UECE = 1.0
MAX_PASTAS_UECE = 5

# ── Mapeamento disciplina → área do conhecimento ──────────────────────────────
# Cobre variações de grafia e disciplinas do ENEM e da UECE
MAPA_AREAS: dict[str, str] = {
    # Ciências Humanas
    "história":                        "ciencias_humanas",
    "historia":                        "ciencias_humanas",
    "geografia":                       "ciencias_humanas",
    "filosofia":                       "ciencias_humanas",
    "sociologia":                      "ciencias_humanas",
    "ciências humanas":                "ciencias_humanas",
    "ciencias humanas":                "ciencias_humanas",

    # Ciências da Natureza
    "biologia":                        "ciencias_natureza",
    "física":                          "ciencias_natureza",
    "fisica":                          "ciencias_natureza",
    "química":                         "ciencias_natureza",
    "quimica":                         "ciencias_natureza",
    "ciências da natureza":            "ciencias_natureza",
    "ciencias da natureza":            "ciencias_natureza",

    # Linguagens
    "língua portuguesa":               "linguagens",
    "lingua portuguesa":               "linguagens",
    "português":                       "linguagens",
    "portugues":                       "linguagens",
    "literatura":                      "linguagens",
    "inglês":                          "linguagens",
    "ingles":                          "linguagens",
    "espanhol":                        "linguagens",
    "artes":                           "linguagens",
    "educação física":                 "linguagens",
    "educacao fisica":                 "linguagens",
    "linguagens":                      "linguagens",

    # Matemática
    "matemática":                      "matematica",
    "matematica":                      "matematica",
    "matemática e suas tecnologias":   "matematica",
}


def inferir_area(disciplina: str) -> str:
    """Retorna a área do conhecimento. Tenta correspondência parcial se exata falhar."""
    chave = disciplina.lower().strip()
    if chave in MAPA_AREAS:
        return MAPA_AREAS[chave]
    # busca parcial (ex: "ciências humanas e suas tecnologias" → humanas)
    for k, area in MAPA_AREAS.items():
        if k in chave:
            return area
    return "outras"   # não descarta: vai para pasta "outras"


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


def classificar_nivel(texto: str) -> str:
    n = len(texto)
    if n < 300: return "Fácil"
    if n < 700: return "Médio"
    return "Difícil"


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def get_json(url: str):
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_html(url: str) -> BeautifulSoup:
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _url_absoluta(href: str) -> str:
    return href if href.startswith("http") else BASE_URL_UECE + href


# ── Persistência ──────────────────────────────────────────────────────────────
def salvar_questao(q: Questao) -> bool:
    """
    Salva em banco_provas/<area>/<vestibular>/questoes.json
    Retorna True se inserida, False se duplicata.
    """
    pasta = BANCO_DIR / q.area / q.vestibular.lower()
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "questoes.json"

    dados: list[dict] = []
    if arquivo.exists():
        dados = json.loads(arquivo.read_text(encoding="utf-8"))

    if any(item["id_unico"] == q.id_unico for item in dados):
        return False

    dados.append(asdict(q))
    arquivo.write_text(json.dumps(dados, indent=4, ensure_ascii=False), encoding="utf-8")
    return True


def reorganizar_banco() -> None:
    """
    Lê todos os questoes.json existentes e reescreve nas pastas corretas
    segundo o MAPA_AREAS. Útil para migrar dados antigos.
    """
    log.info("Reorganizando banco existente por área…")
    movidas = 0
    for arquivo in BANCO_DIR.rglob("questoes.json"):
        questoes = json.loads(arquivo.read_text(encoding="utf-8"))
        restantes = []
        for item in questoes:
            area_correta = inferir_area(item.get("disciplina", ""))
            if item.get("area") == area_correta:
                restantes.append(item)   # já está no lugar certo
                continue
            # área errada ou ausente: reescreve com área correta e salva no lugar certo
            item["area"] = area_correta
            q = Questao(**item)
            if salvar_questao(q):
                movidas += 1
            # remove do arquivo original
        if len(restantes) < len(questoes):
            arquivo.write_text(json.dumps(restantes, indent=4, ensure_ascii=False), encoding="utf-8")
    log.info("Reorganização concluída: %d questão(ões) movida(s).", movidas)


# ── ENEM ──────────────────────────────────────────────────────────────────────
def processar_enem() -> None:
    log.info("Puxando TODAS as questões do ENEM…")
    try:
        questoes = get_json(URL_ENEM)
    except Exception as e:
        log.error("Falha ao buscar ENEM: %s", e)
        return

    inseridas = ignoradas = 0
    for q in questoes:
        # Pega a disciplina como vier; se vier vazia, marca como "Não Informada"
        disc = (q.get("disciplina") or "Não Informada").strip()
        enunciado = q.get("enunciado") or ""

        obj = Questao(
            id_unico=f"ENEM_{q.get('ano')}_{q.get('id')}",
            vestibular="ENEM",
            ano=q.get("ano"),
            disciplina=disc,
            area=inferir_area(disc),
            nivel=classificar_nivel(enunciado),
            enunciado=enunciado,
            alternativas=q.get("alternativas"),
            resposta_correta=q.get("gabarito"),
        )
        if salvar_questao(obj):
            inseridas += 1
        else:
            ignoradas += 1

    log.info("ENEM: %d inserida(s), %d duplicata(s) ignorada(s).", inseridas, ignoradas)


# ── UECE ──────────────────────────────────────────────────────────────────────
def processar_uece() -> None:
    log.info("Mapeando provas da UECE…")
    try:
        soup = get_html(URL_UECE_RAIZ)
    except Exception as e:
        log.error("Falha ao acessar página raiz da UECE: %s", e)
        return

    pastas = {
        _url_absoluta(a["href"])
        for a in soup.find_all("a", href=True)
        if "vestibular" in a["href"].lower()
    }

    pdfs_encontrados = 0
    for url_pasta in list(pastas)[:MAX_PASTAS_UECE]:
        time.sleep(DELAY_UECE)
        try:
            soup_p = get_html(url_pasta)
        except Exception as e:
            log.warning("Não foi possível acessar %s: %s", url_pasta, e)
            continue

        for a in soup_p.find_all("a", href=True):
            href = a["href"].lower()
            nome = a.text.lower()

            if ".pdf" not in href:
                continue

            # Pega TODOS os PDFs de prova (qualquer área), não apenas Humanas
            # Filtra apenas gabaritos duplicados que não interessam
            if "gabarito" in nome and "gabarito 1" not in nome:
                continue

            pdf_url = _url_absoluta(a["href"])

            # Tenta inferir disciplina pelo nome do link
            disc = _inferir_disciplina_uece(nome)
            area = inferir_area(disc)

            log.info("[UECE] PDF %-20s | área: %-20s | %s", disc, area, pdf_url)
            pdfs_encontrados += 1
            # TODO (Fase 4): baixar PDF, extrair questões e chamar salvar_questao()

    log.info("UECE: %d PDF(s) identificado(s).", pdfs_encontrados)


def _inferir_disciplina_uece(nome_link: str) -> str:
    """Extrai a disciplina pelo nome do link PDF da UECE."""
    mapa = {
        "sociologia":   "Sociologia",
        "história":     "História",
        "historia":     "História",
        "geografia":    "Geografia",
        "filosofia":    "Filosofia",
        "biologia":     "Biologia",
        "física":       "Física",
        "fisica":       "Física",
        "química":      "Química",
        "quimica":      "Química",
        "matemática":   "Matemática",
        "matematica":   "Matemática",
        "português":    "Língua Portuguesa",
        "portugues":    "Língua Portuguesa",
        "literatura":   "Literatura",
        "inglês":       "Inglês",
        "ingles":       "Inglês",
        "espanhol":     "Espanhol",
    }
    for chave, disc in mapa.items():
        if chave in nome_link:
            return disc
    return "Não Informada"


# ── Entry-point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    processar_enem()
    processar_uece()
    reorganizar_banco()   # garante que tudo está na pasta certa
    log.info("Processo concluído.")
