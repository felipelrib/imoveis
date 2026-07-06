import logging
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from src.core.entities import PropertyCandidate

logger = logging.getLogger(__name__)

def text_similarity(
    a: Optional[str],
    b: Optional[str],
    algorithm: str = "jaro_winkler",
) -> float:
    """Calculate similarity between two strings."""
    try:
        if not a or not b:
            return 0.0
            
        # Importação condicional para evitar dependências desnecessárias
        if algorithm == "jaro_winkler":
            from jellyfish import jaro_winkler_similarity
            return jaro_winkler_similarity(a, b)
        elif algorithm == "levenshtein":
            from jellyfish import levenshtein_distance
            max_len = max(len(a), len(b))
            if max_len == 0:
                return 1.0
            distance = levenshtein_distance(a, b)
            return 1.0 - (distance / max_len)
        else:
            raise ValueError(f"Unknown similarity algorithm: {algorithm}")
            
    except Exception as e:
        logger.error(f"Error calculating text similarity: {e}")
        return 0.0

def find_candidates(
    session: Session,
    lat: float,
    lon: float,
    radius_m: float = 50.0,
) -> List[Tuple[float, float, str]]:
    """Find property candidates within a given radius."""
    try:
        # Validação de parâmetros
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            logger.warning("Invalid coordinates provided")
            return []
            
        if radius_m <= 0:
            logger.warning("Invalid radius provided")
            return []
        
        # Consulta otimizada para encontrar candidatos próximos
        from sqlalchemy import func, text
        from src.adapters.db.models import Property
        
        # Usando uma consulta SQL direta para melhor performance
        query = """
            SELECT id, latitude, longitude, address 
            FROM properties 
            WHERE ST_Distance_Sphere(
                ST_MakePoint(:lon, :lat),
                ST_MakePoint(longitude, latitude)
            ) <= :radius
        """
        
        result = session.execute(text(query), {
            'lat': lat,
            'lon': lon,
            'radius': radius_m
        }).fetchall()
        
        candidates = []
        for row in result:
            candidates.append((row.latitude, row.longitude, row.address))
            
        logger.debug(f"Found {len(candidates)} candidates near ({lat}, {lon})")
        return candidates
        
    except Exception as e:
        logger.error(f"Error finding candidates: {e}")
        # Retornar lista vazia em caso de erro para evitar falha completa
        return []
