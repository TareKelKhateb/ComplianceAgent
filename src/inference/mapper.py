"""
mapper.py
---------
Fetches compliance mapping relationships between national laws 
and corporate policies from SQLite.
"""

import logging
import os
import sqlite3
from typing import Any, Dict, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class Mapper:
    """
    Connects to mapping.db and corporate_chunks.db to retrieve 
    the related corporate policy text and reasoning for a given law hash.
    """
    def __init__(self):
        # Resolve database paths relative to project root
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.mapping_db_path = os.path.join(base_dir, "data", "mapping.db")
        self.corp_db_path = os.path.join(base_dir, "data", "corporate_chunks.db")
        
        if not os.path.exists(self.mapping_db_path):
            logger.warning(f"Mapping database not found at {self.mapping_db_path}")
        if not os.path.exists(self.corp_db_path):
            logger.warning(f"Corporate database not found at {self.corp_db_path}")

    def get_mapping_data(self, law_hash: str) -> Optional[Dict[str, Any]]:
        """
        Performs an SQL JOIN between the mapping table and the corporate_chunks table
        across two SQLite databases. Returns corporate text and reasoning.
        """
        if not law_hash:
            logger.warning("Empty law_hash provided to Mapper.")
            return None

        conn = None
        try:
            # Connect to mapping.db
            conn = sqlite3.connect(self.mapping_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Attach corporate_chunks.db
            attach_query = "ATTACH DATABASE ? AS corp_db"
            cursor.execute(attach_query, (self.corp_db_path,))
            
            # Try user-specified 'mapping' table first, fallback to 'mapping_bridge' if it differs
            try:
                query = """
                    SELECT 
                        c.content AS corp_text, 
                        m.reasoning 
                    FROM mapping m
                    JOIN corp_db.corporate_chunks c 
                        ON m.corporate_chunk_hash = c.hash
                    WHERE m.country_law_hash = ?
                    LIMIT 1
                """
                cursor.execute(query, (law_hash,))
            except sqlite3.OperationalError as db_err:
                # If 'mapping' doesn't exist, try 'mapping_bridge' (as seen in schema.py/database.py)
                if "no such table: mapping" in str(db_err):
                    query = """
                        SELECT 
                            c.content AS corp_text, 
                            m.reasoning 
                        FROM mapping_bridge m
                        JOIN corp_db.corporate_chunks c 
                            ON m.corporate_chunk_hash = c.hash
                        WHERE m.country_law_hash = ?
                        LIMIT 1
                    """
                    cursor.execute(query, (law_hash,))
                else:
                    raise db_err
                    
            row = cursor.fetchone()
            
            if row:
                logger.info(f"Successfully found mapping data for law_hash: {law_hash}")
                return {
                    "corp_text": row["corp_text"],
                    "reasoning": row["reasoning"]
                }
            else:
                logger.info(f"No mapping record found for law_hash: {law_hash}")
                return None
                
        except sqlite3.Error as e:
            logger.error(f"Database error occurred in Mapper: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in Mapper: {e}")
            return None
        finally:
            if conn:
                try:
                    conn.execute("DETACH DATABASE corp_db")
                except:
                    pass
                conn.close()
