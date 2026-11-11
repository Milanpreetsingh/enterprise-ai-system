import os
import re
import time
import json
try:
    import certifi
    if "SSL_CERT_FILE" not in os.environ:
        os.environ["SSL_CERT_FILE"] = certifi.where()
except ImportError:
    pass

# ── 1. Prompt Injection & Extraction Patterns ───────────────────────────────────
INJECTION_PATTERNS = [
    r"(ignore|override|disregard)\s+(previous|system|all)\s+(instructions|prompts)",
    r"you\s+are\s+now\s+a",
    r"system\s+prompt\s+override",
    r"bypass\s+security\s+filter",
    r"forget\s+all\s+rules",
    r"enter\s+(developer|jailbreak|god)\s+mode",
    r"act\s+as\s+an\s+unrestricted\s+ai",
    r"hypothetically\s+if\s+you\s+had\s+no\s+rules",
]

# PII Redaction Regex Patterns
CREDIT_CARD_PATTERN = r"\b(?:\d[ -]*?){13,16}\b"
EMAIL_PASSWORD_PATTERN = r"(?i)(password|passwd|pwd)\s*[:=]\s*(\S+)"
SSN_PATTERN = r"\b\d{3}-\d{2}-\d{4}\b"
JWT_PATTERN = r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"
API_KEY_PATTERN = r"\b(?:sk|pk|bearer|token)[-_][a-zA-Z0-9_-]{20,}\b"

# Secret & Credential Extraction Attack Actions & Targets
EXTRACTION_ACTIONS = [
    r"share", r"give", r"show", r"reveal", r"tell", r"leak", r"print", r"display",
    r"what\s+is", r"what\'s", r"send", r"provide", r"export", r"cat\b", r"dump", r"read",
    r"access", r"get", r"output", r"expose"
]

SECRET_TARGETS = [
    r"openai\s+api\s+key",
    r"api[_\s-]?keys?",
    r"\.env(?:[_\.-]\w+)?",
    r"secret[_\s-]?keys?",
    r"master[_\s-]?keys?",
    r"private[_\s-]?keys?",
    r"database[_\s-]?passwords?",
    r"db[_\s-]?passwords?",
    r"system\s+passwords?",
    r"auth[_\s-]?tokens?",
    r"jwt[_\s-]?secrets?",
    r"credentials?",
    r"system\s+keys?",
]

EXTRACTION_PATTERN_1 = rf"(?:{'|'.join(EXTRACTION_ACTIONS)}).*?(?:{'|'.join(SECRET_TARGETS)})"
EXTRACTION_PATTERN_2 = rf"(?:{'|'.join(SECRET_TARGETS)}).*?(?:{'|'.join(EXTRACTION_ACTIONS)})"

# ── 2. Tier 1 Deterministic Guardrail ──────────────────────────────────────────
def check_security_violation(input_text: str) -> tuple[bool, str]:
    """
    Tier 1 Fast Heuristic Guardrail: Evaluates user input against credential extraction
    and prompt injection patterns in sub-millisecond execution.
    Returns (is_violation, refusal_message).
    """
    # 1. Credential & secret extraction detection
    if re.search(EXTRACTION_PATTERN_1, input_text, re.IGNORECASE) or re.search(EXTRACTION_PATTERN_2, input_text, re.IGNORECASE):
        return True, "Access Denied: Requesting internal credentials, API keys, or system environment secrets is strictly forbidden by enterprise security policies."

    # 2. System prompt injection / instruction hijacking detection
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, input_text, re.IGNORECASE):
            return True, "Access Denied: System prompt overrides and instruction bypass attempts are blocked by enterprise security guardrails."

    return False, ""

# ── 3. PII & Sensitive Data Sanitizer ───────────────────────────────────────────
def inspect_and_sanitize(input_text: str) -> tuple[str, list[str]]:
    """
    Sanitizes user input by redacting PII (Credit cards, SSNs, passwords, tokens)
    and neutralizing prompt injection markers.
    Returns (sanitized_text, list_of_security_warnings).
    """
    warnings = []

    # 1. Neutralize injection patterns
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, input_text, re.IGNORECASE):
            warnings.append(f"Prompt injection pattern detected: '{pattern}'")
            input_text = re.sub(pattern, "[MALICIOUS_INSTRUCTION_REDACTED]", input_text, flags=re.IGNORECASE)

    # 2. PII Sanitization (Credit Cards)
    if re.search(CREDIT_CARD_PATTERN, input_text):
        warnings.append("PII Detected: Credit card number sanitized.")
        input_text = re.sub(CREDIT_CARD_PATTERN, "[REDACTED_CREDIT_CARD]", input_text)

    # 3. PII Sanitization (Passwords)
    if re.search(EMAIL_PASSWORD_PATTERN, input_text):
        warnings.append("PII Detected: Plaintext password sanitized.")
        input_text = re.sub(EMAIL_PASSWORD_PATTERN, r"\1: [REDACTED_PASSWORD]", input_text)

    # 4. PII Sanitization (SSN)
    if re.search(SSN_PATTERN, input_text):
        warnings.append("PII Detected: SSN sanitized.")
        input_text = re.sub(SSN_PATTERN, "[REDACTED_SSN]", input_text)

    # 5. Sensitive Tokens & API Keys
    if re.search(JWT_PATTERN, input_text):
        warnings.append("Security Token Detected: JWT sanitized.")
        input_text = re.sub(JWT_PATTERN, "[REDACTED_AUTH_TOKEN]", input_text)

    if re.search(API_KEY_PATTERN, input_text, re.IGNORECASE):
        warnings.append("Security Key Detected: API Key sanitized.")
        input_text = re.sub(API_KEY_PATTERN, "[REDACTED_API_KEY]", input_text)

    return input_text, warnings

# ── 4. Tier 2 Model-Based Semantic Guardrail ──────────────────────────────────
_injection_classifier = None

def get_injection_classifier():
    """
    Lazy loads the fine-tuned DeBERTa prompt-injection classification pipeline.
    Runs on Apple Silicon MPS or CPU in ~25-35ms with zero token generation overhead.
    """
    global _injection_classifier
    if _injection_classifier is None:
        try:
            import torch
            from transformers import pipeline

            model_id = os.getenv("GUARDRAIL_MODEL", "protectai/deberta-v3-base-prompt-injection-v2")
            device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
            print(f"[Tier 2 Semantic Guardrail] Loading classifier: {model_id} on {device}...")
            _injection_classifier = pipeline(
                "text-classification",
                model=model_id,
                device=device,
                truncation=True,
                max_length=512
            )
            print("[Tier 2 Semantic Guardrail] Model loaded and active.")
        except Exception as e:
            print(f"[Tier 2 Semantic Guardrail Warning] Failed to initialize classifier: {e}")
            _injection_classifier = False

    return _injection_classifier if _injection_classifier is not False else None


def semantic_guardrail_check(input_text: str) -> tuple[bool, str]:
    """
    Tier 2 Semantic Model Guardrail: Detects nuanced adversarial attacks, persona escapes,
    and social engineering that evade regex patterns.
    Uses local fast DeBERTa encoder classification head (~30ms) on Apple Silicon MPS/CPU.
    """
    if not input_text or not input_text.strip():
        return False, ""

    # 1. Fast Path Heuristic Bypass: Short benign messages avoid inference overhead
    words = input_text.lower().split()
    if len(words) < 4 and not any(kw in input_text.lower() for kw in ["mode", "pretend", "jailbreak", "act", "dan"]):
        return False, ""

    # 2. Fast Path Domain Allowlist: Standard customer order lookups and UUID submissions
    # Normal customer inquiries (providing order IDs, checking tracking, asking for order status)
    # with zero adversarial keywords must never be blocked by off-the-shelf classifier biases.
    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    suspicious_adversarial_markers = [
        "ignore", "override", "disregard", "system", "prompt", "rule", "instruction",
        "jailbreak", "bypass", "mode", "pretend", "roleplay", "unrestricted", "unfiltered",
        "developer", "dan", "god", "hypothetical", "secret", "reveal", "leak", "dump",
        "password", "token", "api key", "apikey"
    ]
    clean_lower = input_text.lower()
    has_adversarial_signal = any(sig in clean_lower for sig in suspicious_adversarial_markers)

    if not has_adversarial_signal:
        # Standard customer submits order UUID
        if re.search(uuid_pattern, clean_lower):
            return False, ""
        # Standard customer order/tracking/status queries
        if any(kw in clean_lower for kw in ["order", "status", "track", "tracking", "package", "refund", "return", "cancel"]):
            return False, ""

    # 3. Fast Heuristic Filter: Flag obvious roleplay or jailbreak indicators instantly (<1ms)
    suspicious_markers = [
        "roleplay as", "pretend to be", "dan mode", "unfiltered", "hypothetical scenario where you have no guidelines",
        "developer mode enabled", "ignore all safety guidelines"
    ]
    for marker in suspicious_markers:
        if marker in input_text.lower():
            return True, f"Access Denied: Semantic guardrail detected adversarial persona manipulation ('{marker}')."

    # 3. Model-Based Semantic Guardrail: DeBERTa Encoder Classifier
    classifier = get_injection_classifier()
    if classifier is not None:
        try:
            t0 = time.time()
            result = classifier(input_text)
            elapsed_ms = (time.time() - t0) * 1000

            # Result format: [{'label': 'INJECTION', 'score': 0.999}]
            if result and len(result) > 0:
                top_pred = result[0]
                label = top_pred.get("label", "").upper()
                score = float(top_pred.get("score", 0.0))

                if label == "INJECTION" and score >= 0.85:
                    print(f"[Tier 2 Semantic Guardrail] Blocked adversarial injection (Score: {score:.4f}, Latency: {elapsed_ms:.2f}ms): '{input_text[:60]}...'")
                    return True, "Access Denied: Semantic AI security guardrail detected an adversarial prompt injection or jailbreak attempt."

                print(f"[Tier 2 Semantic Guardrail] Query classified as SAFE (Score: {score:.4f}, Latency: {elapsed_ms:.2f}ms).")
        except Exception as e:
            print(f"[Tier 2 Semantic Guardrail Warning] Inference failed: {e}")

    return False, ""

# ── 5. Data Loss Prevention (DLP) Output Guardrail ─────────────────────────────
def inspect_and_sanitize_output(output_text: str) -> str:
    """
    Tier 3 Output Guardrail: Prevents accidental data leakage (DLP) in model-generated output,
    such as database connection strings, internal file system paths, or raw stack traces.
    """
    if not output_text:
        return ""

    # Redact DB URIs
    output_text = re.sub(r"postgres(?:ql)?://[^\s]+", "[REDACTED_DATABASE_CONNECTION_URI]", output_text)

    # Redact raw Python tracebacks
    if "Traceback (most recent call last):" in output_text:
        output_text = "An internal processing error occurred. Our operations team has been notified."

    # Redact exposed internal file system paths
    output_text = re.sub(r"/(?:Users|home|tmp|etc)/[a-zA-Z0-9_\-\./]+", "[INTERNAL_PATH_REDACTED]", output_text)

    # Redact any accidental credit card numbers in response
    output_text = re.sub(CREDIT_CARD_PATTERN, "[REDACTED_CREDIT_CARD]", output_text)

    return output_text
