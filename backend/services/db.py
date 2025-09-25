import duckdb
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Define DB path
DB_PATH = "telemetry.duckdb"

def map_mavlink_to_duckdb(mav_type: str) -> str:
    """Map MAVLink field types to DuckDB column types"""
    mapping = {
        "int8_t": "TINYINT",
        "uint8_t": "UTINYINT",
        "int16_t": "SMALLINT",
        "uint16_t": "USMALLINT",
        "int32_t": "INTEGER",
        "uint32_t": "INTEGER",  # Changed from UINTEGER to INTEGER to handle negative values
        "int64_t": "BIGINT",
        "uint64_t": "UBIGINT",
        "float": "FLOAT",
        "double": "DOUBLE",
        "char[16]": "VARCHAR",
        "char[50]": "VARCHAR",
        "string": "VARCHAR",
        "uint8_t_mavlink_version": "UTINYINT"  # Special MAVLink version type
    }
    duck_type = mapping.get(mav_type.lower())
    if not duck_type:
        raise ValueError(f"Unknown MAVLink type '{mav_type}' - add it to the mapping in db.py")
    return duck_type

def get_connection():
    """Get a DuckDB connection"""
    return duckdb.connect(DB_PATH)

def create_tables_from_schema(normalized_schema: Dict[str, Any], 
                              enriched_schema: Dict[str, Any]):
    """Create DuckDB tables based on schema agent output"""
    conn = get_connection()
    
    for table, schema in normalized_schema.items():
        fields = schema["fields"]
        enriched_fields = enriched_schema.get(table, {}).get("fieldDescriptions", {})
        
        col_defs = []
        for field in fields:
            f_info = enriched_fields.get(field, {})
            duck_type = map_mavlink_to_duckdb(f_info.get("type", "string"))
            col_defs.append(f"{field} {duck_type}")
        
        create_stmt = f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(col_defs)});"
        logger.info(f"Executing: {create_stmt}")
        conn.execute(create_stmt)
    
    conn.close()
    logger.info(f"Database schema created at {DB_PATH}")

def insert_rows(table: str, rows: List[Dict[str, Any]]):
    """Insert rows into a DuckDB table"""
    if not rows:
        return 0
    
    conn = get_connection()
    columns = rows[0].keys()
    placeholders = ", ".join(["?"] * len(columns))
    insert_stmt = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    
    # Debug: log the first row to see data types
    logger.info(f"Sample row for {table}: {rows[0]}")
    
    try:
        values = [tuple(row[col] for col in columns) for row in rows]
        conn.executemany(insert_stmt, values)
        conn.close()
        logger.info(f"Inserted {len(rows)} rows into {table}")
        return len(rows)
    except Exception as e:
        logger.error(f"Error inserting rows into {table}: {e}")
        conn.close()
        raise

def ingest_telemetry_data(messageType: str, rows: List[Dict[str, Any]]) -> int:
    """Ingest telemetry data for a specific message type"""
    table_name = messageType.lower()
    return insert_rows(table_name, rows)
