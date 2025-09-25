#!/usr/bin/env python3
"""
Quick script to inspect the DuckDB database
"""
import duckdb
import os

def inspect_database():
    db_path = "telemetry.duckdb"
    
    if not os.path.exists(db_path):
        print("❌ Database file not found!")
        return
    
    print(f"📊 Inspecting database: {db_path}")
    print("=" * 50)
    
    conn = duckdb.connect(db_path)
    
    # List all tables
    tables = conn.execute("SHOW TABLES").fetchall()
    print(f"📋 Found {len(tables)} tables:")
    for table in tables:
        print(f"  - {table[0]}")
    
    print("\n" + "=" * 50)
    
    # Show details for each table
    for table in tables:
        table_name = table[0]
        print(f"\n🔍 Table: {table_name}")
        print("-" * 30)
        
        # Get row count
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"Rows: {count}")
        
        # Show schema
        schema = conn.execute(f"DESCRIBE {table_name}").fetchall()
        print("Schema:")
        for col in schema:
            print(f"  {col[0]}: {col[1]}")
        
        # Show sample data (first 3 rows)
        if count > 0:
            sample = conn.execute(f"SELECT * FROM {table_name} LIMIT 3").fetchall()
            print("Sample data:")
            for row in sample:
                print(f"  {row}")
        else:
            print("  (No data)")
    
    conn.close()
    print("\n✅ Database inspection complete!")

if __name__ == "__main__":
    inspect_database()