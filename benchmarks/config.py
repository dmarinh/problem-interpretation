"""
Benchmark Configuration

Which LLM models to evaluate and where results go.

API keys are stored in .env (gitignored), not here.
Each model references the NAME of the env var that holds its key.

Required .env entries (add only the providers you want to test):

    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=sk-ant-...
    GEMINI_API_KEY=...
    DEEPSEEK_API_KEY=sk-...
"""

from pathlib import Path


# ---------------------------------------------------------------------------
# Paths — everything relative to this file
# ---------------------------------------------------------------------------

BENCHMARKS_ROOT = Path(__file__).parent
PROJECT_ROOT = BENCHMARKS_ROOT.parent
DATASETS_DIR = BENCHMARKS_ROOT / "datasets"
RESULTS_DIR = BENCHMARKS_ROOT / "results"


# ---------------------------------------------------------------------------
# Models to evaluate
# ---------------------------------------------------------------------------
# Each dict has:
#   name            — display name for tables and charts
#   litellm_model   — the string LiteLLM uses to route the call
#   api_key_env_var — name of the environment variable holding the API key
#                     (None for local models like Ollama that need no key)
#   api_base        — custom endpoint URL (None uses provider default)
#   cost_per_call   — rough USD estimate (fallback if token tracking fails)
#   instructor_mode — how Instructor extracts structured data:
#                     None   = tool/function calling (default, best for API providers)
#                     "JSON" = JSON-in-prompt (required for local Ollama models)
#
# Models are grouped into 4 tiers. Uncomment the ones you want to test.
# You don't need all API keys — the experiment skips models whose keys
# are missing and tells you which ones it skipped.

MODELS = [

    # ===================================================================
    # TIER 0: Latest frontier models (accuracy reference)
    # ===================================================================
    # Purpose: establish the absolute ceiling of what's achievable today.
    # Too expensive for production use, but the benchmark against which
    # all other tiers are measured. If a Tier 2 model matches these,
    # there's no reason to pay frontier prices.
    #
    # NOTE: Verify litellm_model strings match your LiteLLM version.
    # These models are recent — strings may need adjustment.

    {
        "name": "GPT-5.4",
        "litellm_model": "chatgpt/gpt-5.2",                      # verify exact string
        "api_key_env_var": "OPENAI_API_KEY",
        "api_base": None,
        "cost_per_call": 0.02,
        "instructor_mode": None,
        # OpenAI's latest. Accuracy ceiling for structured extraction.
    },
    {
        "name": "Claude Opus 4.6",
        "litellm_model": "anthropic/claude-opus-4-6",     # verify exact string
        "api_key_env_var": "ANTHROPIC_API_KEY",
        "api_base": None,
        "cost_per_call": 0.03,
        "instructor_mode": None
        # Anthropic's most advanced. Reference for reasoning-heavy queries.
    },
    {
        "name": "Gemini 3 Pro",
        "litellm_model": "gemini/gemini-3-pro-preview",           # verify exact string
        "api_key_env_var": "GEMINI_API_KEY",
        "api_base": None,
        "cost_per_call": 0.02,
        "instructor_mode": None,
        # Google's latest frontier. Tests third provider at maximum capability.
    },

    # ===================================================================
    # TIER 1: Frontier chat models (strong, established)
    # ===================================================================
    # Purpose: proven models with stable APIs. If Tier 0 shows marginal
    # improvement over these, the newer models aren't worth the premium.

    {
        "name": "GPT-4o",
        "litellm_model": "gpt-4o",
        "api_key_env_var": "OPENAI_API_KEY",
        "api_base": None,
        "cost_per_call": 0.005,
        "instructor_mode": None,
        # Current default. Strong structured output. Baseline for comparison.
    },
    {
        "name": "Claude Sonnet 4",
        "litellm_model": "anthropic/claude-sonnet-4-20250514",
        "api_key_env_var": "ANTHROPIC_API_KEY",
        "api_base": None,
        "cost_per_call": 0.007,
        "instructor_mode": None,
        # Alternative frontier provider. Tests provider independence.
    },

    # ===================================================================
    # TIER 2: Cost-optimized chat models (production candidates)
    # ===================================================================
    # Purpose: find the cheapest model that maintains acceptable accuracy.
    # If a model here matches Tier 1 accuracy, it's the production choice.

    {
        "name": "GPT-4o-mini",
        "litellm_model": "gpt-4o-mini",
        "api_key_env_var": "OPENAI_API_KEY",
        "api_base": None,
        "cost_per_call": 0.0003,
        "instructor_mode": None,
        # ~20x cheaper than GPT-4o. Same API. Key question: how much accuracy lost?
    },
    {
        "name": "Claude Haiku 3.5",
        "litellm_model": "anthropic/claude-3-5-haiku-20241022",
        "api_key_env_var": "ANTHROPIC_API_KEY",
        "api_base": None,
        "cost_per_call": 0.002,
        "instructor_mode": None,
        # Anthropic's cost tier. Tests provider flexibility at low cost.
    },
    {
        "name": "Gemini 2.0 Flash",
        "litellm_model": "gemini/gemini-2.0-flash",
        "api_key_env_var": "GEMINI_API_KEY",
        "api_base": None,
        "cost_per_call": 0.0001,
        # Extremely cheap. If it works, changes batch processing economics.
        "instructor_mode": None,
    },
    {
        "name": "DeepSeek V3",
        "litellm_model": "deepseek/deepseek-chat",
        "api_key_env_var": "DEEPSEEK_API_KEY",
        "api_base": None,
        "cost_per_call": 0.0003,
        "instructor_mode": None,
        # Chinese frontier model, very low cost. Competitive with GPT-4o on benchmarks.
    },

    # ===================================================================
    # TIER 3: Reasoning models (is reasoning needed?)
    # ===================================================================
    # Purpose: determine whether "thinking step by step" improves accuracy
    # on hard queries (model type classification, range preservation).
    # Reasoning tokens add 3-5x cost. If accuracy is the same as chat
    # models, reasoning is an unnecessary expense for this task.

    {
        "name": "o3-mini",
        "litellm_model": "o3-mini",
        "api_key_env_var": "OPENAI_API_KEY",
        "api_base": None,
        "cost_per_call": 0.015,
        "instructor_mode": None,
        # OpenAI reasoning model. ~3x cost of GPT-4o due to thinking tokens.
        # Tests: does reasoning help with growth/inactivation classification?
    },
    {
        "name": "Gemini 2.5 Flash",
        "litellm_model": "gemini/gemini-2.5-flash-preview-04-17",
        "api_key_env_var": "GEMINI_API_KEY",
        "api_base": None,
        "cost_per_call": 0.001,
        "instructor_mode": None,
        # Google's hybrid reasoning/chat. Cheaper than o3-mini.
        # Tests: does lightweight reasoning help without full cost?
    },

    # ===================================================================
    # TIER 4: Open source via Ollama (self-hosted option)
    # ===================================================================
    # Purpose: determine whether self-hosting is viable. Eliminates API
    # costs, data leaves no premises, but accuracy may be lower.
    # All use JSON mode because most local models lack tool-call support.
    # Run `ollama pull <model>` before testing.

    {
        "name": "Qwen 2.5 14B",
        "litellm_model": "ollama/qwen2.5:14b",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "cost_per_call": 0.0,
        "instructor_mode": "JSON",
        # Best open-source structured output at <=14B. Runs on 8GB VRAM + CPU offload.
    },
    {
        "name": "Qwen 2.5 7B",
        "litellm_model": "ollama/qwen2.5:7b",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "cost_per_call": 0.0,
        "instructor_mode": "JSON",
        # Fits entirely in 8GB VRAM. Fastest local option. Tests minimum viable size.
    },
    {
        "name": "Mistral Nemo 12B",
        "litellm_model": "ollama/mistral-nemo",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "cost_per_call": 0.0,
        "instructor_mode": "JSON",
        # Different architecture from Qwen. Isolates size vs. architecture effects.
    },
    {
        "name": "Gemma 3 12B",
        "litellm_model": "ollama/gemma3:12b",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "cost_per_call": 0.0,
        "instructor_mode": "JSON",
        # Different architecture from Qwen. Isolates size vs. architecture effects.
    },

]
