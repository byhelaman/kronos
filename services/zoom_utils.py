"""
Utilidades para procesamiento de texto y matching de usuarios/reuniones de Zoom.

Este módulo proporciona funciones para normalizar y buscar coincidencias
entre nombres de usuarios, reuniones y datos del Excel.
"""
import re
import unicodedata
from rapidfuzz import process, fuzz
from typing import Dict, Any, Optional

# Palabras irrelevantes que se eliminan durante la normalización
IRRELEVANT_WORDS = re.compile(
    r"\b("
    + "|".join(
        [
            # Modalities
            r"online",
            r"presencial",
            r"virtual",
            r"hibrido",
            r"remoto",
            # Languages
            r"english",
            r"espanol",
            r"aleman",
            r"coreano",
            r"chino",
            r"ruso",
            r"japones",
            r"frances",
            r"italiano",
            r"mandarin",
            # Levels and courses
            r"nivelacion",
            r"beginner",
            r"electiv[oa]s?",
            r"leccion[es]?",
            r"repit[eo]?",
            r"repaso",
            r"crash",
            r"complete",
            r"revision",
            r"evaluacion[es]?",
            # Organization / structure
            r"grupo",
            r"bvp",
            r"bvs",
            r"pia",
            r"mod",
            r"otg",
            r"kids",
            r"look\s?\d+",
            r"tz\d+",
            # Location / country
            r"per",
            r"ven",
            r"arg",
            r"uru",
            # Others
            r"true",
            r"business",
            r"impact",
            r"social",
            r"travel",
            r"gerencia",
            r"beca",
            r"camacho",
        ]
    )
    + r")\b",
    flags=re.IGNORECASE,
)


def remove_irrelevant(text: str) -> str:
    """Elimina palabras irrelevantes del texto."""
    tokens = re.findall(r"\w+", text.lower())
    filtered_tokens = [t for t in tokens if not IRRELEVANT_WORDS.search(t)]
    return " ".join(filtered_tokens)


def canonical(s: str) -> str:
    """
    Normaliza una cadena a su forma canónica para comparaciones exactas.
    
    Elimina acentos, caracteres especiales y palabras irrelevantes,
    dejando solo caracteres alfanuméricos en minúsculas.
    """
    s = remove_irrelevant(s or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\W+", "", s)
    return s.casefold()


def normalizar_cadena(s: str) -> str:
    """
    Normaliza una cadena para búsquedas fuzzy.
    
    Similar a canonical pero preserva espacios y algunos caracteres
    para permitir matching más flexible.
    """
    s = remove_irrelevant(s or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.strip().casefold()
    s = re.sub(r"[''ʻ‚]", "'", s)
    s = re.sub(r"[-_–—]", " ", s)
    s = re.sub(r"[^\w\s']", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\d+", "", s)
    return s.strip()


def fuzzy_find(
    raw: str,
    choices: Dict[str, Any],
    scorer=fuzz.token_set_ratio,
    threshold: int = 85,
) -> Optional[Any]:
    """
    Busca una coincidencia aproximada en un diccionario de opciones.
    
    Args:
        raw: Texto a buscar
        choices: Diccionario donde las claves son strings normalizados
        scorer: Función de scoring de rapidfuzz
        threshold: Umbral mínimo de similitud (0-100)
        
    Returns:
        El valor del diccionario si se encuentra una coincidencia, None en caso contrario
    """
    if not raw or not choices:
        return None

    normalized_query = normalizar_cadena(raw)

    result = process.extractOne(
        normalized_query,
        list(choices.keys()),
        scorer=scorer,
        score_cutoff=threshold,
    )

    if result:
        best_match_key = result[0]
        return choices[best_match_key]

    return None

