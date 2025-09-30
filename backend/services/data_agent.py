import logging
from typing import Any, Dict
from models.data_Ag import DataAgentResponse
from services import db
from openai import OpenAI
from dotenv import load_dotenv
from e2b import Sandbox
import os
import time
import json
# Load environment variables
load_dotenv()

# Suppress verbose E2B HTTP logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("e2b").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI()

def run_data_agent(task_spec: dict, intent: str) -> DataAgentResponse:
    """
    Self-healing Data Agent with LLM-driven retry loop.
    Attempts to generate and execute code, with LLM-guided repair on failures.
    """
    # Start timing the entire execution
    start_time = time.time()
    
    # Get schema bundle and DB connection "baked in" automatically
    schema_bundle = get_schema_bundle()
    db_connection = db.get_connection()
    
    # Log inputs concisely
    logger.info(f"Data Agent: {task_spec.get('query', 'Unknown task')[:60]}...")
    
    # Self-healing retry loop
    attempts = []
    max_retries = 3
    
    for attempt_num in range(1, max_retries + 1):
        try:
            # Generate code using LLM
            if attempt_num == 1:
                prompt = build_initial_prompt(schema_bundle, task_spec, intent)
            else:
                # Repair attempt: ask LLM to fix code based on previous error
                last_attempt = attempts[-1]
                prompt = build_repair_prompt(
                    schema_bundle, task_spec, intent,
                    last_attempt["generated_code"], last_attempt["error"],
                    last_attempt["stdout"], last_attempt["stderr"]
                )
            
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You generate executable code for UAV telemetry analysis. You are a code generator. Always return runnable Python code only. No explanations, no formatting, no extra text."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=5000
            )
            
            generated_code = response.choices[0].message.content.strip()
            
            # Execute the generated code in E2B sandbox
            success, result_data, stdout, stderr, error_msg = execute_in_sandbox(generated_code)
            
            # Save attempt record
            attempt_record = {
                "attempt": attempt_num,
                "generated_code": generated_code,
                "stdout": stdout,
                "stderr": stderr,
                "error": error_msg,
                "success": success
            }
            attempts.append(attempt_record)
            
            if success:
                # Calculate total execution time
                total_duration = time.time() - start_time
                
                # Success! Return with attempt history for transparency
                return DataAgentResponse(
                    ok=True,
                    data=result_data,
                    executed_code=generated_code,
                    errors=[],
                    logs=[f"Attempt {a['attempt']}: {'Success' if a['success'] else a['error']}" for a in attempts],
                    attempts=attempts,
                    duration_sec=total_duration
                )
            else:
                if attempt_num < max_retries:
                    logger.warning(f"Attempt {attempt_num} failed, retrying...")
                else:
                    logger.error(f"All retries exhausted: {error_msg}")
        
        except Exception as e:
            logger.error(f"LLM code generation failed on attempt {attempt_num}: {e}")
            attempt_record = {
                "attempt": attempt_num,
                "generated_code": None,
                "stdout": "",
                "stderr": "",
                "error": f"LLM generation failed: {str(e)}",
                "success": False
            }
            attempts.append(attempt_record)
    
        # All attempts failed - return structured failure with history
        total_duration = time.time() - start_time
        return DataAgentResponse(
            ok=False,
            data=None,
            executed_code=attempts[-1]["generated_code"] if attempts else None,
            errors=[a["error"] for a in attempts if a["error"]],
            logs=["All retries failed"] + [f"Attempt {a['attempt']}: {a['error']}" for a in attempts],
            attempts=attempts,
            duration_sec=total_duration
        )

def build_initial_prompt(schema_bundle: dict, task_spec: dict, intent: str) -> str:
    """Build the initial prompt for code generation"""
    return f"""
You are a specialized coding agent for UAV telemetry analysis. 
Your sole job is to write clean, runnable Python code that uses DuckDB 
to query and analyze telemetry data.

Context:
- The schema bundle describes the available tables, columns, and datatypes.
- The task spec defines what the user is asking for.
- The intent explains the high-level purpose of the task.

Rules:
1. Always output valid Python code (no explanations, no Markdown, no prose).
2. Use `duckdb` Python API (via a connection object passed in as `db_connection`).
3. Use pandas if a DataFrame makes sense (e.g., for returning tabular results).
4. Include clear variable names (e.g., `query`, `df`, `result`).
5. The final line of code should assign the result to a variable called `result`.
6. Do not print or log inside the generated code.
7. You may only import: duckdb, pandas, numpy. Do not import scipy, sklearn, or any other library.


DuckDB SQL REQUIREMENTS:
- Only use supported aggregate functions: MIN, MAX, AVG, COUNT, SUM, STDDEV.
- Do NOT use QUANTILE_DISC, PERCENTILE_DISC, or advanced window/ordered aggregate functions.
- If you need medians or quantiles, approximate them using basic math/statistics in Python after fetching the data.
- Always check table schema first: SELECT * FROM table LIMIT 1
- Cast time columns if needed: CAST(time_boot_ms AS BIGINT)
- Stick to columns listed in the schema bundle — dont invent new ones.


Try to do full analysis on the data fields that you select to work on, dont really just analyze a single point.

Inputs:
- Schema bundle: {schema_bundle}
- Task spec: {task_spec}
- Intent: {intent}

Now generate only the Python code that fulfills the task.
"""


def build_repair_prompt(schema_bundle: dict, task_spec: dict, intent: str, 
                       failed_code: str, error_msg: str, stdout: str, stderr: str) -> str:
    """Build the repair prompt for fixing failed code"""
    return f"""
You previously wrote this code for UAV telemetry analysis:

```python
{failed_code}
```

It failed with this error from DuckDB:
{error_msg}

Additional context:
- stdout: {stdout}
- stderr: {stderr}

Schema bundle:
{schema_bundle}

Original task spec: {task_spec}
Original intent: {intent}

Please correct the SQL so it runs successfully in DuckDB. 
- Remove any unsupported functions (e.g., QUANTILE_DISC, PERCENTILE_DISC, ordered aggregates).
- If the query requires quantiles or medians, fetch the raw data and compute them in Python instead.
- Use only basic DuckDB functions: MIN, MAX, AVG, COUNT, SUM, STDDEV.
- Ensure all columns exist in the schema bundle.

Please revise the code so it will run successfully in DuckDB while preserving the intent.
Only output corrected Python code (no explanations, no Markdown, no extra text).
"""


def execute_in_sandbox(generated_code: str) -> tuple[bool, Any, str, str, str]:
    """
    Execute generated code in E2B sandbox and return success status and outputs.
    Returns: (success, result_data, stdout, stderr, error_msg)
    """
    try:
        # Prepare the code with database connection setup
        full_code = f"""
import duckdb
import pandas as pd

# Database connection (simulated - in real E2B we'd need to pass the DB file)
# For now, we'll create a mock connection for testing
db_connection = duckdb.connect(":memory:")

# User's generated code:
{generated_code}
"""
        
        with Sandbox.create(template="39lf1as0rvcg60o5u43r", api_key=os.getenv("E2B_API_KEY")) as sandbox:
            # Upload the database file to the sandbox
            sandbox.files.write("/tmp/telemetry.duckdb", open("telemetry.duckdb", "rb").read())
            
            # Update the code to use the uploaded database
            full_code = full_code.replace('duckdb.connect(":memory:")', 'duckdb.connect("/tmp/telemetry.duckdb")')
            
            # Add print(result) to capture the final output
            full_code_with_print = full_code + "\nprint('=== RESULT ===')\nprint(result)"
            
            # Write the code to a file and run it
            sandbox.files.write("/tmp/analysis.py", full_code_with_print)
            
            # Run the analysis (packages are pre-installed in custom template)
            process = sandbox.commands.run("python3 /tmp/analysis.py")
            
            # Capture outputs
            stdout = process.stdout
            stderr = process.stderr
            
            # Check if execution was successful
            if process.exit_code == 0:
                # Extract the result from stdout
                result_data = None
                if stdout and "=== RESULT ===" in stdout:
                    # Extract everything after the result marker
                    result_section = stdout.split("=== RESULT ===")[1].strip()
                    result_data = result_section
                elif stdout:
                    # Fallback: use the entire stdout if no result marker
                    result_data = stdout
                
                return True, result_data, stdout, stderr, ""
            else:
                # Execution failed - preserve full error details for LLM repair
                error_msg = stderr if stderr else f"Command exited with code {process.exit_code}"
                return False, None, stdout, stderr, error_msg
                
    except Exception as e:
        logger.error(f"E2B execution failed: {e}")
        return False, None, "", "", f"E2B execution failed: {str(e)}"

def get_schema_bundle() -> dict:
    """Get enriched schema with descriptions, units, field metadata"""
    conn = db.get_connection()
    
    try:
        # Retrieve enriched schema from metadata table
        result = conn.execute(
            "SELECT value FROM __metadata__ WHERE key = 'enriched_schema'"
        ).fetchone()
        
        if result:
            schema_data = json.loads(result[0])
            conn.close()  # Close AFTER using the data
            return schema_data
    except Exception as e:
        logger.warning(f"Could not load enriched schema from metadata: {e}")
    finally:
        # Ensure connection is closed even on error
        try:
            conn.close()
        except:
            pass
    
    # Fallback: basic schema without enrichment
    conn = db.get_connection()  # NEW connection for fallback
    tables = conn.execute("SHOW TABLES").fetchall()
    schema_info = {}
    
    for table in tables:
        table_name = table[0]
        if table_name.startswith("__"):
            continue
        schema = conn.execute(f"DESCRIBE {table_name}").fetchall()
        schema_info[table_name] = {
            "columns": [{"name": col[0], "type": col[1]} for col in schema]
        }
    
    conn.close()
    return {
        "message_types": list(schema_info.keys()),
        "enriched_schema": schema_info,
        "normalized_schema": schema_info
    }