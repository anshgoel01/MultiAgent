# agent-orchestrator/tools/vector_search.py
import logging
import os
from typing import List
import psycopg2
from psycopg2 import OperationalError
from psycopg2.pool import ThreadedConnectionPool
# pyrefly: ignore [missing-import]
from sentence_transformers import SentenceTransformer
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Initialize model
try:
    model = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("SentenceTransformer model loaded successfully")
except Exception as e:
    logger.error(f"Failed to load SentenceTransformer model: {str(e)}")
    model = None

# Initialize connection pool at import time
db_pool = None
database_url = os.getenv('DATABASE_URL')
if database_url:
    try:
        db_pool = ThreadedConnectionPool(1, 10, database_url)
        logger.info("Database connection pool initialized successfully at import time")
    except Exception as e:
        logger.error(f"Failed to initialize database connection pool at import time: {str(e)}")

@tool
def search_documents(query: str, top_k: int = 5) -> List[str]:
    """
    Search the internal document corpus using semantic similarity.
    
    Args:
        query: The search query string
        top_k: Number of top results to return (default: 5)
    
    Returns:
        List of formatted document results with scores
    """
    try:
        if model is None:
            logger.error("SentenceTransformer model not initialized")
            return ["Error: Model not available"]
        
        if not query or not query.strip():
            logger.warning("Empty query provided to search_documents")
            return []
        
        if top_k <= 0:
            logger.warning(f"Invalid top_k value: {top_k}")
            top_k = 5
        
        logger.info(f"Searching documents for query: {query[:100]}")
        
        # Encode query
        try:
            emb = model.encode(query).tolist()
        except Exception as e:
            logger.error(f"Failed to encode query: {str(e)}")
            return ["Error: Failed to process query"]
        
        # Ensure pool is initialized
        global db_pool
        if db_pool is None:
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                logger.error("DATABASE_URL not set")
                return ["Error: Database not configured"]
            try:
                db_pool = ThreadedConnectionPool(1, 10, database_url)
                logger.info("Database connection pool initialized lazily")
            except Exception as e:
                logger.error(f"Failed to initialize database connection pool lazily: {str(e)}")
                return ["Error: Database connection failed"]
        
        # Get connection from pool
        try:
            conn = db_pool.getconn()
            cur = conn.cursor()
            logger.debug("Database connection retrieved from pool")
        except Exception as e:
            logger.error(f"Failed to get connection from pool: {str(e)}")
            return ["Error: Database connection failed"]
        
        try:
            # Execute vector search query
            cur.execute(
                '''SELECT content, source, 1 - (embedding <=> %s::vector) AS score
                   FROM documents 
                   ORDER BY embedding <=> %s::vector 
                   LIMIT %s''',
                (emb, emb, top_k)
            )
            rows = cur.fetchall()
            logger.info(f"Found {len(rows)} documents")
            
            # Format results
            results = [f'[{r[1]}] (score={r[2]:.2f}): {r[0]}' for r in rows]
            return results if results else ["No documents found"]
            
        except Exception as e:
            is_undefined_table = False
            if hasattr(e, 'pgcode') and e.pgcode == '42P01':
                is_undefined_table = True
            elif "relation \"documents\" does not exist" in str(e).lower():
                is_undefined_table = True
                
            if is_undefined_table:
                logger.error("CRITICAL ERROR: The 'documents' table does not exist in the database. Please run migrations or initialize the database.", exc_info=True)
                raise e
                
            logger.error(f"Error executing search query: {str(e)}", exc_info=True)
            return ["Error: Search query failed"]
        finally:
            cur.close()
            db_pool.putconn(conn)
            logger.debug("Database connection returned to pool")
            
    except Exception as e:
        logger.error(f"Unexpected error in search_documents: {str(e)}", exc_info=True)
        return ["Error: Unexpected error occurred"]