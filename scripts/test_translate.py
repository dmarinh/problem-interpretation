"""
Manual test script for multi-step (multiple temperatures) pipeline translation.

Tests a scenario where food passes through several temperature stages, verifying
that the orchestrator correctly extracts a multi-step time-temperature profile
and accumulates log growth across each step.

Usage:
    python scripts/test_translate.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()


def _sep(label: str = "", width: int = 70) -> None:
    if label:
        print(f"  {'─' * 4} {label} {'─' * max(0, width - len(label) - 7)}")
    else:
        print("  " + "─" * (width - 2))


async def main():
    from app.core.log_config import setup_logging
    setup_logging()

    from app.core.orchestrator import get_orchestrator, reset_orchestrator
    from app.engines.combase.engine import get_combase_engine
    from app.rag.vector_store import get_vector_store

    print("=" * 70)
    print("MULTI-STEP TEMPERATURE PIPELINE TEST")
    print("=" * 70)
    print()

    engine = get_combase_engine()
    csv_path = Path("data/combase_models.csv")
    if not csv_path.exists():
        print(f"✗ ComBase models not found at {csv_path}")
        return
    count = engine.load_models(csv_path)
    print(f"✓ Loaded {count} ComBase models")

    store = get_vector_store()
    store.initialize()
    print(f"✓ Vector store initialized ({store.get_count()} documents)")
    print()

    reset_orchestrator()
    orchestrator = get_orchestrator()

    test_cases = [
        {
            "query": (
                "A slice of white bread was kept at 25 °C for 4 hours. Predict Bacillus cereus growth."
            ),
            "description": "",
        },
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"TEST {i}: {test['description']}")
        print(f"Query: \"{test['query']}\"")
        print("-" * 70)

        try:
            result = await orchestrator.translate(user_input=test["query"])
            state = result.state

            # ── STATUS ────────────────────────────────────────────────────────
            print(f"  Status : {'SUCCESS' if result.success else 'FAILED'}")
            if result.error:
                print(f"  Error  : {result.error}")

            # ── INTENT ────────────────────────────────────────────────────────
            _sep("INTENT")
            print(f"  type               : {state.intent_type}")
            if state.intent:
                intent = state.intent
                print(f"  is_prediction      : {intent.is_prediction_request}")
                print(f"  is_information     : {intent.is_information_query}")
                print(f"  requires_clarif.   : {intent.requires_clarification}")
                if intent.reasoning:
                    print(f"  reasoning          : {intent.reasoning}")

            # ── EXTRACTED SCENARIO ────────────────────────────────────────────
            if state.extracted_scenario:
                s = state.extracted_scenario
                _sep("EXTRACTED SCENARIO")
                print(f"  food_description   : {s.food_description}")
                print(f"  food_state         : {s.food_state}")
                print(f"  pathogen_mentioned : {s.pathogen_mentioned}")
                print(f"  concern_type       : {s.concern_type}")
                print(f"  additional_context : {s.additional_context}")
                print(f"  is_multi_step      : {s.is_multi_step}")
                print(f"  is_cooking_scenario: {s.is_cooking_scenario}")
                print(f"  is_storage_scenario: {s.is_storage_scenario}")
                print(f"  is_non_thermal     : {s.is_non_thermal_treatment}")
                print(f"  implied_model_type : {s.implied_model_type}")

                if s.is_multi_step and s.time_temperature_steps:
                    print(f"  time_temp_steps ({len(s.time_temperature_steps)}):")
                    for step in s.time_temperature_steps:
                        t = step.temperature
                        d = step.duration
                        temp_str = (
                            f"{t.value_celsius}°C"
                            if t.value_celsius is not None
                            else t.description or "?"
                        )
                        dur_str = (
                            f"{d.value_minutes:.0f} min"
                            if d.value_minutes is not None
                            else d.description or "?"
                        )
                        print(
                            f"    [{step.sequence_order}] {step.description or ''}: "
                            f"{temp_str} for {dur_str}"
                        )
                else:
                    t = s.single_step_temperature
                    d = s.single_step_duration
                    temp_str = (
                        f"{t.value_celsius}°C"
                        if t.value_celsius is not None
                        else t.description or "not set"
                    )
                    dur_str = (
                        f"{d.value_minutes:.0f} min"
                        if d.value_minutes is not None
                        else d.description or "not set"
                    )
                    print(f"  single_step_temp   : {temp_str}")
                    print(f"  single_step_dur    : {dur_str}")

                env = s.environmental_conditions
                env_parts = []
                if env.ph_value is not None:
                    env_parts.append(f"pH={env.ph_value}")
                if env.water_activity is not None:
                    env_parts.append(f"aw={env.water_activity}")
                if env.salt_percent is not None:
                    env_parts.append(f"salt={env.salt_percent}%")
                if env.co2_percent is not None:
                    env_parts.append(f"CO2={env.co2_percent}%")
                if env.nitrite_ppm is not None:
                    env_parts.append(f"nitrite={env.nitrite_ppm}ppm")
                if env.lactic_acid_ppm is not None:
                    env_parts.append(f"lactic={env.lactic_acid_ppm}ppm")
                if env.acetic_acid_ppm is not None:
                    env_parts.append(f"acetic={env.acetic_acid_ppm}ppm")
                if env.atmosphere_description:
                    env_parts.append(f"atm={env.atmosphere_description}")
                if env.ph_description:
                    env_parts.append(f"pH_desc={env.ph_description}")
                if env.salt_description:
                    env_parts.append(f"salt_desc={env.salt_description}")
                print(f"  env_conditions     : {', '.join(env_parts) or 'none'}")

            # ── GROUNDED VALUES ───────────────────────────────────────────────
            if state.grounded_values:
                _sep("GROUNDED VALUES")
                for k, v in state.grounded_values.items():
                    print(f"  {k:<28}: {v}")

            # ── EXECUTION PAYLOAD ─────────────────────────────────────────────
            if state.execution_payload:
                ep = state.execution_payload
                _sep("EXECUTION PAYLOAD")
                ms = ep.model_selection
                p = ep.parameters
                print(f"  model_type         : {ep.model_type}")
                print(f"  organism           : {ms.organism}")
                print(f"  factor4_type       : {ms.factor4_type}")
                print(f"  temperature        : {p.temperature_celsius}°C")
                print(f"  pH                 : {p.ph}")
                print(f"  water_activity     : {p.water_activity}")
                if p.factor4_type.value != "none":
                    print(f"  factor4_value      : {p.factor4_value}")
                profile = ep.time_temperature_profile
                print(f"  profile.is_multi   : {profile.is_multi_step}")
                print(f"  profile.total_dur  : {profile.total_duration_minutes:.0f} min ({profile.total_duration_minutes/60:.2f} h)")
                for step in profile.steps:
                    print(
                        f"    Step {step.step_order}: "
                        f"{step.temperature_celsius}°C for {step.duration_minutes:.0f} min"
                    )

            # ── EXECUTION RESULT ──────────────────────────────────────────────
            if result.execution_result:
                er = result.execution_result
                mr = er.model_result
                _sep("EXECUTION RESULT")
                print(f"  total_log_increase : {er.total_log_increase:.4f} log CFU")
                if er.total_log_increase > 0:
                    print(f"  fold_increase      : ~{10 ** er.total_log_increase:.1f}x")
                print(f"  mu_max             : {mr.mu_max:.4f} 1/h")
                if mr.doubling_time_hours is not None:
                    print(f"  doubling_time      : {mr.doubling_time_hours:.2f} h")
                print(f"  organism           : {mr.organism}")
                print(f"  temp_used          : {mr.temperature_used}°C")
                print(f"  ph_used            : {mr.ph_used}")
                print(f"  aw_used            : {mr.aw_used}")
                if mr.factor4_type_used.value != "none":
                    print(f"  factor4_used       : {mr.factor4_type_used} = {mr.factor4_value_used}")
                if er.step_predictions:
                    print(f"  step_predictions ({len(er.step_predictions)}):")
                    for sp in er.step_predictions:
                        print(
                            f"    Step {sp.step_order} "
                            f"({sp.temperature_celsius}°C, {sp.duration_minutes:.0f} min): "
                            f"μ_max={sp.mu_max:.4f} 1/h, Δlog={sp.log_increase:.4f}"
                        )
                if er.warnings:
                    for w in er.warnings:
                        print(f"  engine_warning     : {w}")

            # ── METADATA ──────────────────────────────────────────────────────
            if result.metadata:
                md = result.metadata
                _sep("METADATA")
                print(f"  session_id         : {md.session_id}")
                print(f"  status             : {md.status}")
                print(f"  created_at         : {md.created_at.strftime('%H:%M:%S.%f')[:-3]}")
                if md.completed_at:
                    print(f"  completed_at       : {md.completed_at.strftime('%H:%M:%S.%f')[:-3]}")

                if md.provenance:
                    print(f"  provenance ({len(md.provenance)} fields):")
                    for field, prov in md.provenance.items():
                        orig = (
                            f", orig={prov.original_value}"
                            if prov.original_value is not None
                            else ""
                        )
                        transform = (
                            f", tx={prov.transformation_applied}"
                            if prov.transformation_applied
                            else ""
                        )
                        method = (
                            f", method={prov.extraction_method}"
                            if prov.extraction_method
                            else ""
                        )
                        raw = (
                            f", raw=\"{prov.raw_match}\""
                            if prov.raw_match
                            else ""
                        )
                        rng = (
                            f", range={prov.parsed_range}"
                            if prov.parsed_range
                            else ""
                        )
                        print(
                            f"    {field:<24}: {prov.source.value}"
                            f"{orig}{transform}{method}{raw}{rng}"
                        )

                if md.bias_corrections:
                    print(f"  bias_corrections ({len(md.bias_corrections)}):")
                    for bc in md.bias_corrections:
                        print(
                            f"    {bc.field_name}: {bc.original_value} → {bc.corrected_value}"
                            f" [{bc.bias_type.value}] — {bc.correction_reason}"
                        )

                if md.range_clamps:
                    print(f"  range_clamps ({len(md.range_clamps)}):")
                    for rc in md.range_clamps:
                        print(
                            f"    {rc.field_name}: {rc.original_value} → {rc.clamped_value}"
                            f" (valid [{rc.valid_min}, {rc.valid_max}]) — {rc.reason}"
                        )

                if md.retrievals:
                    print(f"  retrievals ({len(md.retrievals)}):")
                    for r in md.retrievals:
                        fallback = " [fallback]" if r.fallback_used else ""
                        emb = f", emb={r.embedding_score:.3f}" if r.embedding_score is not None else ""
                        rerank = f", rerank={r.rerank_score:.3f}" if r.rerank_score is not None else ""
                        print(
                            f"    \"{r.query[:50]}\"{emb}{rerank}{fallback}"
                        )
                        if r.source_document:
                            print(f"      source_document: {r.source_document}")
                        if r.chunk_id:
                            print(f"      chunk_id       : {r.chunk_id}")
                        if r.retrieved_text:
                            preview = r.retrieved_text[:120].replace("\n", " ")
                            ellipsis = "…" if len(r.retrieved_text) > 120 else ""
                            print(f"      retrieved_text : \"{preview}{ellipsis}\"")
                        if r.source_ids:
                            print(f"      source_ids     : {r.source_ids}")
                        if r.full_citations:
                            for sid, cit in r.full_citations.items():
                                print(f"      [{sid}] {cit}")
                        if r.runners_up:
                            print(f"      runners_up ({len(r.runners_up)}):")
                            for ru in r.runners_up:
                                ru_emb = f", emb={ru.embedding_score:.3f}" if ru.embedding_score is not None else ""
                                ru_rerank = f", rerank={ru.rerank_score:.3f}" if ru.rerank_score is not None else ""
                                preview = (ru.content_preview or "")[:80]
                                print(f"        {ru.doc_id}{ru_emb}{ru_rerank}: \"{preview}\"")

                if md.defaults_imputed:
                    print(f"  defaults_imputed ({len(md.defaults_imputed)}):")
                    for d in md.defaults_imputed:
                        print(f"    {d}")

                if md.combase_model:
                    cm = md.combase_model
                    _sep("COMBASE MODEL AUDIT")
                    print(f"  organism           : {cm.organism}")
                    print(f"  model_type         : {cm.model_type}")
                    print(f"  model_id           : {cm.model_id}")
                    print(f"  selection_reason   : {cm.selection_reason}")
                    if cm.valid_ranges:
                        for field, (lo, hi) in cm.valid_ranges.items():
                            print(f"  valid_{field:<14}: [{lo}, {hi}]")
                    if cm.coefficients_str:
                        coeffs = cm.coefficients_str.split(";")
                        truncated = cm.coefficients_str[:80]
                        suffix = "..." if len(cm.coefficients_str) > 80 else ""
                        print(f"  coefficients ({len(coeffs)}): {truncated}{suffix}")

                if md.system:
                    sys_ = md.system
                    _sep("SYSTEM AUDIT")
                    print(f"  ptm_version        : {sys_.ptm_version}")
                    print(f"  combase_csv_hash   : {sys_.combase_model_table_hash}")
                    print(f"  rag_store_hash     : {sys_.rag_store_hash}")
                    print(f"  rag_ingested_at    : {sys_.rag_ingested_at}")
                    print(f"  source_csv_audit   : {sys_.source_csv_audit_date}")

                if md.clarifications:
                    print(f"  clarifications ({len(md.clarifications)}):")
                    for cl in md.clarifications:
                        print(f"    [{cl.turn_number}] {cl.reason.value}: \"{cl.question_asked}\"")
                        if cl.user_response:
                            print(f"      response     : \"{cl.user_response}\"")
                        if cl.default_used:
                            print(f"      default_used : True")

                if md.warnings:
                    print(f"  warnings ({len(md.warnings)}):")
                    for w in md.warnings:
                        print(f"    {w}")

                if md.notes:
                    print(f"  notes ({len(md.notes)}):")
                    for n in md.notes:
                        print(f"    {n}")

        except Exception as e:
            import traceback
            print(f"✗ Exception: {e}")
            traceback.print_exc()

        print()

    print("=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
