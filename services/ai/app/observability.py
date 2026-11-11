import json
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AI_Observability")

class MeasureLatency:
    """
    Structured Latency Context Manager for AI & Vector performance benchmarking.
    """
    def __init__(self, operation_name: str):
        self.operation_name = operation_name

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000.0
        log_entry = {
            "event": "operation_latency",
            "operation": self.operation_name,
            "duration_ms": round(elapsed_ms, 2),
            "status": "error" if exc_type else "success"
        }
        logger.info(json.dumps(log_entry))

def log_eval_metric(test_name: str, passed: bool, details: dict):
    """
    Logs an automated evaluation result.
    """
    log_entry = {
        "event": "eval_metric",
        "test_name": test_name,
        "passed": passed,
        "details": details
    }
    logger.info(json.dumps(log_entry))
