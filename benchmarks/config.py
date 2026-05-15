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
#   instructor_mode — how Instructor extracts structured data:
#                     None   = tool/function calling (default, best for API providers)
#                     "JSON" = JSON-in-prompt (required for local Ollama models)
#   tier            — model tier for visualization grouping:
#                     0 = latest frontier (accuracy reference)
#                     1 = established frontier
#                     2 = cost-optimized chat
#                     3 = reasoning models
#                     4 = open source (Ollama)
#
# Models are grouped into 4 tiers. Uncomment the ones you want to test.
# You don't need all API keys — the experiment skips models whose keys
# are missing and tells you which ones it skipped.

MODELS = [


    # ===================================================================
    # TIER 1: Frontier chat models (strong, established)
    # ===================================================================
    # Purpose: proven models with stable APIs. If Tier 0 shows marginal
    # improvement over these, the newer models aren't worth the premium.

    # {
    #     "name": "Claude Opus 4.7",
    #     "litellm_model": "anthropic/claude-opus-4-7",
    #     "api_key_env_var": "ANTHROPIC_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "drop_params": True,  # Anthropic deprecated `temperature` for this model
    #     "tier": 1,
    #     # $5/M in, $25/M out. 1M context, adaptive thinking. Anthropic flagship.
    #     # PTM quality anchor; released Apr 16, 2026.
    # },
    {
        "name": "GPT-5.5",
        "litellm_model": "openai/gpt-5.5",
        "api_key_env_var": "OPENAI_API_KEY",
        "api_base": None,
        "instructor_mode": None,
        "drop_params": True,  # GPT-5 only accepts temperature=1; drop to use model default
        "tier": 1,
        # $5/M in, $30/M out. 1.05M context. Released Apr 23, 2026.
        # Beats Opus 4.7 and Gemini 3.1 Pro on Terminal-Bench 2.0 and FrontierMath.
        # OpenAI flagship; provider-independence triangulation point.
    },
    # {
    #     "name": "Gemini 3.1 Pro",
    #     "litellm_model": "gemini/gemini-3.1-pro-preview",
    #     "api_key_env_var": "GOOGLE_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "tier": 1,
    #     # Google flagship. Leading ARC-AGI-2 reasoning score in proprietary tier.
    # },

    # ===================================================================
    # TIER 2: Cost-optimized chat models (production candidates)
    # ===================================================================
    # Purpose: find the cheapest model that maintains acceptable accuracy.
    # If a model here matches Tier 1 accuracy, it's the production choice.

    # {
    #     "name": "Claude Haiku 4.5",
    #     "litellm_model": "anthropic/claude-haiku-4-5",
    #     "api_key_env_var": "ANTHROPIC_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "tier": 2,
    #     # $1/M in, $5/M out. 200K context. Anthropic budget tier.
    #     # ~5x cheaper than Sonnet 4.6 for typical PTM payloads.
    # },
    # {
    #     "name": "Claude Sonnet 4.6",
    #     "litellm_model": "anthropic/claude-sonnet-4-6",
    #     "api_key_env_var": "ANTHROPIC_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "tier": 2,
    #     # $3/M in, $15/M out. 1M context. Anthropic production workhorse;
    #     # ~half the cost of Opus 4.7 for typical PTM RAG payloads.
    # },
    # {
    #     "name": "Gemini 3 Flash",
    #     "litellm_model": "gemini/gemini-3-flash-preview",
    #     "api_key_env_var": "GOOGLE_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "tier": 2,
    #     # $0.50/M in, $3/M out. Google mid-tier; cheapest of the four.
    #     # Pair with Gemini 3.1 Pro to test within-family scaling effects.
    # },
    # {
    #     "name": "GPT-5.4 Mini",
    #     "litellm_model": "openai/gpt-5.4-mini",
    #     "api_key_env_var": "OPENAI_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "drop_params": True,  # GPT-5 only accepts temperature=1; drop to use model default
    #     "tier": 2,
    #     # OpenAI current-gen mini (released Mar 17, 2026).
    #     # GPT-5.5 Mini not yet shipped at time of config; revisit when available.
    # },
    {
        "name": "GPT-4o",
        "litellm_model": "openai/gpt-4o",
        "api_key_env_var": "OPENAI_API_KEY",
        "api_base": None,
        "instructor_mode": None,
        "extra_params": {"temperature": 0.0},
        "tier": 2,  
        # $2.50/M in, $10/M out. 128K context. Released May 2024.
        # Pre-reasoning-era flagship; most-cited proprietary baseline in 2024-2025
        # RAG and structured-output literature. Cross-paper comparability anchor.
    },
    # {
    #     "name": "Gemini 2.0 Flash",
    #     "litellm_model": "gemini/gemini-2.0-flash",
    #     "api_key_env_var": "GOOGLE_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "extra_params": {"temperature": 0.0},
    #     "tier": 5,
    #     # $0.10/M in, $0.40/M out. 1M context. Released Dec 2024.
    #     # Pre-reasoning-era Google fast-tier baseline.
    # },
    # {
    #     "name": "Gemini 1.5 Pro",
    #     "litellm_model": "gemini/gemini-1.5-pro",
    #     "api_key_env_var": "GOOGLE_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "extra_params": {"temperature": 0.0},
    #     "tier": 2, 
    #     # $1.25/M in, $5/M out (under 128K input). 2M context window.
    #     # Contemporaneous Google flagship (Feb 2024 / May 2024 GA).
    #     # Pre-reasoning era; direct cross-paper pair with GPT-4o.
    # },

    # ===================================================================
    # TIER 3: Reasoning ablation (same frontier models, thinking OFF)
    # ===================================================================
    # Purpose: A/B test against Tier 1 to determine if "thinking" actually
    # helps on PTM tasks (model-type classification, range preservation,
    # multi-source citation). Default behavior of Tier 1 models is
    # thinking-on (Opus adaptive, GPT-5.5 effort=medium, Gemini Pro default).
    # If Tier 3 matches Tier 1 accuracy, thinking is wasted spend.

    # {
    #     "name": "Claude Opus 4.7 (no thinking)",
    #     "litellm_model": "anthropic/claude-opus-4-7",
    #     "api_key_env_var": "ANTHROPIC_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "drop_params": True,
    #     "extra_params": {"thinking": {"type": "disabled"}},
    #     "tier": 3,
    #     # A/B pair with Tier 1 Opus 4.7. Same $5/M in, $25/M out,
    #     # but no reasoning-token overhead -> ~2-3x cheaper per call.
    # },
    # {
    #     "name": "GPT-5.5 (no reasoning)",
    #     "litellm_model": "openai/gpt-5.5",
    #     "api_key_env_var": "OPENAI_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "drop_params": True,
    #     "extra_params": {"reasoning_effort": "none"},
    #     "tier": 3,
    #     # A/B pair with Tier 1 GPT-5.5. Default effort is "medium";
    #     # "none" eliminates reasoning tokens entirely. Supported values:
    #     # none, low, medium (default), high, xhigh.
    # },
    # {
    #     "name": "Gemini 3.1 Pro (no thinking)",
    #     "litellm_model": "gemini/gemini-3.1-pro-preview",
    #     "api_key_env_var": "GOOGLE_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "extra_params": {"thinking_config": {"thinking_budget": 0}},
    #     "tier": 3,
    #     # A/B pair with Tier 1 Gemini 3.1 Pro. thinking_budget=0
    #     # forces direct answer without reasoning trace.
    # },

    # ===================================================================
    # TIER 4: Open source via Ollama (self-hosted option)
    # ===================================================================
    # Purpose: determine whether self-hosting is viable. Eliminates API
    # costs, data leaves no premises, but accuracy may be lower.
    # All use JSON mode because most local models lack tool-call support.
    # Run `ollama pull <model>` before testing.

    {
        "name": "Gemma4 E4B",
        "litellm_model": "ollama/gemma4:latest",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "instructor_mode": None,  # It has native support for function calling
        "tier": 4,
        # Effective 4B parameters Q4_K_M quantization, with 128k context lentgh
        # Weights ~2.2 GB * (1.2 to 1.5 overhead and KV cache) -> ~4GB VRAM usage
    },
    {
        "name": "Qwen 3 8B",
        "litellm_model": "ollama/qwen3:8b",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "instructor_mode": None,  # Native tools + thinking support
        "tier": 4,
        # 8.19B params Q4_K_M quantization, 40K context length
        # Weights ~4.5 GB * (1.2 to 1.5 overhead and KV cache) -> ~5-6 GB VRAM usage
        # Hybrid /think toggle for controlled CoT-on vs CoT-off comparisons
    },
    {
        "name": "Llama 3.1 8B Instruct",
        "litellm_model": "ollama/llama3.1:8b",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "instructor_mode": None,  # Native tools support (no thinking mode)
        "extra_params": {"temperature": 0.0, "seed": 42},
        "tier": 4,
        # 8.03B params Q4_K_M quantization, 128K context length
        # Weights ~4.5 GB * (1.2 to 1.5 overhead and KV cache) -> ~5-6 GB VRAM usage
        # Cross-paper comparability baseline; most-cited 8B in RAG/structured-output literature
    },
    {
        "name": "Phi-4 14B",
        "litellm_model": "ollama/phi4",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "instructor_mode": "JSON",  # No native tools; force JSON mode via Instructor
        "tier": 4,
        # 14.7B params Q4_K_M quantization, 16K context length
        # Weights ~9.1 GB + KV cache -> ~10-11 GB; partial CPU offload on 8 GB VRAM
        # STEM reasoning ceiling probe; tight context limits heavy RAG payloadsA)
    },

    {
        "name": "GLM-4.7 Flash",
        "litellm_model": "ollama/glm-4.7-flash:q4_K_M",
        "api_key_env_var": None,
        "api_base": "http://localhost:11434",
        "instructor_mode": "JSON",  # Native tools + thinking (confirmed in Ollama capabilities)
        "tier": 4,
        # 30B-A3B MoE (3B active/token), Q4_K_M, 198K context, MIT licensed
        # 19 GB total weights -> spills to RAM; ~5-15 t/s RAM-bandwidth-bound on 8 GB VRAM
        # Requires Ollama >= 0.14.3 (was pre-release; check `ollama --version`)
        # Agentic/tool-use specialist (tau2-Bench 79.5); validate tool-call parsing first
    },

    # Kimi is open weights but not viable to the local tier - wrong scale enntirely
    # Moonshot ships an OpenAI/Anthropic-compatible API at platform.moonshot.ai. 
    # So Kimi K2.6 / K2-Thinking slots cleanly into your frontier-API tier alongside
    #  Claude Opus 4.x, GPT-5.x, Gemini, and DeepSeek V3.2 — as the open-weights frontier reference

    # MiniMax M2
    # MiniMax M2 / M2.5 / M2.7 are all the same architecture family: 
    # 230B total params / 10B active (MoE).
  
    # ===================================================================
    # TIER 5: Open-weights frontier (API only - locally unrannable) 
    # ===================================================================  
  
    # {
    #     "name": "DeepSeek V3.2",
    #     "litellm_model": "deepseek/deepseek-chat",
    #     "api_key_env_var": "DEEPSEEK_API_KEY",
    #     "api_base": None,
    #     "instructor_mode": None,
    #     "tier": 3,
    #     # $0.28/M in, $0.42/M out. 671B MoE / 37B active, MIT licensed.
    #     # ~30x cheaper than Sonnet 4.6; cheapest open-weights frontier reference.
    #     # WARNING: API routes through CN servers — do not send sensitive PTM data.
    # },
    # {
    #     "name": "Kimi K2 Thinking",
    #     "litellm_model": "openai/kimi-k2-thinking",
    #     "api_key_env_var": "MOONSHOT_API_KEY",
    #     "api_base": "https://api.moonshot.ai/v1",
    #     "instructor_mode": None,
    #     "tier": 5,
    #     # 1T MoE / 32B active. First open-weights model to match closed frontier
    #     # (HLE 44.9%, SWE-Bench 71.3%). Set via OpenAI-compatible endpoint.
    #     # Same CN-routing caveat as DeepSeek for sensitive data.
    # },
    
  
  
  


]



