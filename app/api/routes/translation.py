"""
Translation API endpoint.

Main endpoint for translating natural language food safety queries
into structured model inputs and predictions.
"""

from datetime import datetime

from fastapi import APIRouter, Query, status

from app.api.schemas.translation import (
    AuditDetail,
    AuditSummary,
    ComBaseModelAuditInfo,
    DefaultImputedInfo,
    ExtractionAuditInfo,
    FieldAuditEntry,
    RangeClampInfo,
    RetrievalAuditInfo,
    RetrievalTopMatchInfo,
    RunnerUpInfo,
    StandardizationAuditInfo,
    SystemAuditInfo,
    TranslationRequest,
    TranslationResponse,
    PredictionResult,
    ProvenanceInfo,
    StepInput,
    StepPrediction,
    WarningInfo,
)
from app.core.orchestrator import get_orchestrator, TranslationResult
from app.models.enums import SessionStatus
from app.models.metadata import InterpretationMetadata, RangeClamp, ValueSource


router = APIRouter(prefix="/translate", tags=["translation"])


def _format_growth_description(log_increase: float) -> str:
    """Generate human-readable growth description."""
    if log_increase < 0:
        reduction = abs(log_increase)
        if reduction >= 6:
            return f"Significant reduction: {reduction:.1f} log decrease (>99.9999% killed)"
        elif reduction >= 3:
            return f"Major reduction: {reduction:.1f} log decrease (>99.9% killed)"
        elif reduction >= 1:
            return f"Moderate reduction: {reduction:.1f} log decrease"
        else:
            return f"Minor reduction: {reduction:.2f} log decrease"
    elif log_increase < 0.3:
        return f"Minimal growth: {log_increase:.2f} log increase (<2x population)"
    elif log_increase < 1.0:
        fold = 10 ** log_increase
        return f"Moderate growth: {log_increase:.1f} log increase (~{fold:.0f}x population)"
    elif log_increase < 3.0:
        fold = 10 ** log_increase
        return f"Significant growth: {log_increase:.1f} log increase (~{fold:.0f}x population)"
    else:
        return f"Extensive growth: {log_increase:.1f} log increase (>1000x population)"


def _build_field_audit(result: TranslationResult) -> dict[str, FieldAuditEntry]:
    """
    Build the per-field audit map from a completed TranslationResult.

    Always called — even when verbose=False — so the legacy provenance list
    can be derived from it (see _build_provenance_list).

    The audit snapshot is post-standardization: final_value reflects the value
    that reached the ComBase model, not the pre-standardization placeholder
    stored in grounded_values.  This is correct because StandardizationService
    mutates ValueProvenance objects in-place (setting prov.standardization and
    clearing prov.range_pending), so by the time this function runs, the
    provenance objects in metadata already carry the post-standardization state.
    """
    metadata: InterpretationMetadata | None = result.metadata
    if metadata is None:
        return {}

    # ── Index standardization events by field ──────────────────────────────────
    # Used for final_value resolution and standardization block construction.
    clamp_by_field: dict[str, RangeClamp] = {
        c.field_name: c for c in (metadata.range_clamps or [])
    }

    # ── Index retrieval results by query for field matching ─────────────────────
    rag_retrievals = {r.query: r for r in (metadata.retrievals or [])}

    field_audit: dict[str, FieldAuditEntry] = {}

    # ── Fields that have grounding provenance ──────────────────────────────────
    for field_name, prov in (metadata.provenance or {}).items():
        source_str = (
            prov.source.value if isinstance(prov.source, ValueSource) else str(prov.source)
        )

        # ── final_value: post-standardization priority chain ──────────────────
        # 1. Clamped value (clamp is always the last operation)
        # 2. Range-bound-selected value (prov.standardization set in-place by std svc)
        # 3. Canonical organism display name (for the organism field)
        # 4. Pre-standardization grounded value (correct for explicit non-range fields)
        if field_name in clamp_by_field:
            final_value: float | str | None = clamp_by_field[field_name].clamped_value
        elif prov.standardization is not None:
            final_value = prov.standardization.after_value
        elif (
            field_name == "organism"
            and metadata.combase_model is not None
            and metadata.combase_model.organism_display_name is not None
        ):
            final_value = metadata.combase_model.organism_display_name
        else:
            final_value = result.state.grounded_values.get(field_name) if result.state.grounded_values else None

        # ── Retrieval block (RAG-sourced fields only) ─────────────────────────
        retrieval_info: RetrievalAuditInfo | None = None
        if prov.source == ValueSource.RAG_RETRIEVAL and rag_retrievals:
            r = next(iter(rag_retrievals.values()))
            if "pathogen" in field_name or field_name == "organism":
                r = next(
                    (v for k, v in rag_retrievals.items() if "pathogen" in k.lower()),
                    r,
                )
            elif field_name in ("ph", "water_activity"):
                r = next(
                    (v for k, v in rag_retrievals.items() if "ph" in k.lower() or "water" in k.lower()),
                    r,
                )
            top_match = RetrievalTopMatchInfo(
                doc_id=r.chunk_id,
                embedding_score=r.embedding_score,
                rerank_score=r.rerank_score,
                retrieved_text=r.retrieved_text,
                source_ids=r.source_ids,
                full_citations=r.full_citations,
            ) if r else None
            runners_up = [
                RunnerUpInfo(
                    doc_id=ru.doc_id,
                    content_preview=ru.content_preview,
                    embedding_score=ru.embedding_score,
                    rerank_score=ru.rerank_score,
                )
                for ru in (r.runners_up if r else [])
            ]
            retrieval_info = RetrievalAuditInfo(
                query=r.query if r else "",
                top_match=top_match,
                runners_up=runners_up,
            )

        # ── Extraction block ──────────────────────────────────────────────────
        extraction_info: ExtractionAuditInfo | None = None
        has_extraction = (
            prov.extraction_method is not None
            or prov.raw_match is not None
            or prov.matched_pattern is not None
        )
        if has_extraction:
            extraction_info = ExtractionAuditInfo(
                method=prov.extraction_method,
                raw_match=prov.raw_match,
                parsed_range=prov.parsed_range,
                matched_pattern=prov.matched_pattern,
                conservative=prov.rule_conservative,
                notes=prov.rule_notes,
                similarity=prov.embedding_similarity,
                canonical_phrase=prov.canonical_phrase,
            )

        # ── Standardization block ─────────────────────────────────────────────
        # Clamp takes precedence over range-bound selection when both fired.
        std_info: StandardizationAuditInfo | None = None
        if field_name in clamp_by_field:
            c = clamp_by_field[field_name]
            std_info = StandardizationAuditInfo(
                rule="range_clamp",
                before_value=c.original_value,
                after_value=c.clamped_value,
                reason=c.reason,
            )
        elif prov.standardization is not None:
            s = prov.standardization
            std_info = StandardizationAuditInfo(
                rule=s.rule,
                direction=s.direction,
                before_value=s.before_value,
                after_value=s.after_value,
                reason=s.reason,
            )

        field_audit[field_name] = FieldAuditEntry(
            final_value=final_value,
            source=source_str,
            retrieval=retrieval_info,
            extraction=extraction_info,
            standardization=std_info,
        )

    # ── Defaulted fields: absent from provenance but used by the model ─────────
    # StandardizationService imputes defaults for fields never grounded.
    # Add them to field_audit so it is the single complete map of every value
    # the model used, regardless of whether the value came from the user or
    # from conservative defaults.
    for d in (metadata.defaults_imputed or []):
        if d.field_name not in field_audit:
            field_audit[d.field_name] = FieldAuditEntry(
                final_value=d.imputed_value,
                source=ValueSource.CONSERVATIVE_DEFAULT.value,
                retrieval=None,
                extraction=None,
                standardization=StandardizationAuditInfo(
                    rule="default_imputed",
                    before_value=None,
                    after_value=d.imputed_value,
                    reason=d.reason,
                ),
            )

    return field_audit


def _build_provenance_list(
    result: TranslationResult,
    field_audit: dict[str, FieldAuditEntry],
) -> list[ProvenanceInfo]:
    """Derive the legacy provenance list from the pre-built field_audit map.

    Using field_audit as the single source of truth guarantees that
    final_value and notes are post-standardization — the old approach of
    reading raw provenance produced stale placeholder notes for range fields.
    """
    provenance = []

    for field, entry in field_audit.items():
        value_str = str(entry.final_value) if entry.final_value is not None else "N/A"

        # Build a human-readable notes string from the standardization block
        # or the extraction info — whichever is more informative.
        notes: str | None = None
        if entry.standardization is not None:
            std = entry.standardization
            if std.rule == "range_bound_selection":
                notes = (
                    f"Range {std.before_value} → selected {std.direction} bound "
                    f"{std.after_value} ({std.reason})"
                )
            elif std.rule == "range_clamp":
                notes = f"Clamped {std.before_value} → {std.after_value}: {std.reason}"
            else:
                notes = std.reason
        elif entry.extraction is not None and entry.extraction.notes:
            notes = entry.extraction.notes
        elif entry.extraction is not None and entry.extraction.method:
            notes = f"Extracted via {entry.extraction.method}"

        provenance.append(ProvenanceInfo(
            field=field,
            value=value_str,
            source=entry.source,
            notes=notes,
        ))

    return provenance


def _build_warnings_list(result: TranslationResult) -> list[WarningInfo]:
    """Build warnings list from translation result."""
    warnings = []

    if result.metadata:
        # Add range clamps as warnings
        for clamp in result.metadata.range_clamps:
            warnings.append(WarningInfo(
                type="range_clamp",
                message=f"Value {clamp.original_value} clamped to {clamp.clamped_value} (valid range: {clamp.valid_min}-{clamp.valid_max})",
                field=clamp.field_name,
            ))

        # Add general warnings
        for warning in result.metadata.warnings:
            warnings.append(WarningInfo(
                type="warning",
                message=warning,
            ))

    return warnings


def _build_audit_detail(
    result: TranslationResult,
    field_audit: dict[str, FieldAuditEntry],
) -> AuditDetail:
    """Assemble the full verbose AuditDetail from a pre-built field_audit map."""
    metadata: InterpretationMetadata | None = result.metadata
    if metadata is None:
        return AuditDetail(
            field_audit={},
            combase_model=None,
            audit=AuditSummary(),
            system=None,
        )

    # ── Top-level audit summary ────────────────────────────────────────────────
    clamp_list = [
        RangeClampInfo(
            field_name=c.field_name,
            original_value=c.original_value,
            clamped_value=c.clamped_value,
            valid_min=c.valid_min,
            valid_max=c.valid_max,
            reason=c.reason,
        )
        for c in metadata.range_clamps
    ]
    defaults_list = [
        DefaultImputedInfo(
            field_name=d.field_name,
            default_value=d.imputed_value,
            reason=d.reason,
        )
        for d in metadata.defaults_imputed
    ]
    audit_summary = AuditSummary(
        range_clamps=clamp_list,
        defaults_imputed=defaults_list,
        warnings=list(metadata.warnings),
    )

    # ── ComBase model block ────────────────────────────────────────────────────
    cb_info: ComBaseModelAuditInfo | None = None
    if metadata.combase_model:
        cm = metadata.combase_model
        cb_info = ComBaseModelAuditInfo(
            organism=cm.organism,
            organism_id=cm.organism_id,
            organism_display_name=cm.organism_display_name,
            model_type=cm.model_type,
            model_id=cm.model_id,
            coefficients_str=cm.coefficients_str,
            valid_ranges=cm.valid_ranges,
            selection_reason=cm.selection_reason,
        )

    # ── System block ───────────────────────────────────────────────────────────
    sys_info: SystemAuditInfo | None = None
    if metadata.system:
        s = metadata.system
        sys_info = SystemAuditInfo(
            rag_store_hash=s.rag_store_hash,
            rag_ingested_at=s.rag_ingested_at,
            source_csv_audit_date=s.source_csv_audit_date,
            ptm_version=s.ptm_version,
            combase_model_table_hash=s.combase_model_table_hash,
        )

    return AuditDetail(
        field_audit=field_audit,
        combase_model=cb_info,
        audit=audit_summary,
        system=sys_info,
    )


@router.post(
    "",
    response_model=TranslationResponse,
    status_code=status.HTTP_200_OK,
    summary="Translate a food safety query",
    description="""
    Translate a natural language food safety query into structured model inputs
    and return growth/inactivation predictions.
    
    The endpoint:
    1. Extracts food, pathogen, time, and temperature from the query
    2. Grounds values using RAG retrieval from scientific sources
    3. Applies conservative defaults for missing values
    4. Runs the appropriate predictive model
    5. Returns results with full provenance tracking
    """,
)
async def translate_query(
    request: TranslationRequest,
    verbose: bool = Query(default=False, description="Include full audit trail in response"),
) -> TranslationResponse:
    """
    Translate a natural language food safety query.
    """
    orchestrator = get_orchestrator()
    completed_at = datetime.utcnow()
    
    try:
        # Run translation
        result = await orchestrator.translate(
            user_input=request.query,
            model_type=request.model_type,
        )
        completed_at = datetime.utcnow()
        
        # Build response
        prediction = None
        if result.success and result.execution_result and result.state.execution_payload:
            exec_result = result.execution_result
            model_result = exec_result.model_result
            profile = result.state.execution_payload.time_temperature_profile

            prediction = PredictionResult(
                organism=model_result.organism.name if model_result.organism else "Unknown",
                model_type=model_result.model_type.value if model_result.model_type else "growth",
                engine=model_result.engine_type.value if model_result.engine_type else "unknown",
                temperature_celsius=model_result.temperature_used,
                duration_minutes=profile.total_duration_minutes,
                ph=model_result.ph_used,
                water_activity=model_result.aw_used,
                mu_max=model_result.mu_max,
                doubling_time_hours=model_result.doubling_time_hours,
                total_log_increase=exec_result.total_log_increase,
                is_multi_step=profile.is_multi_step,
                steps=[
                    StepInput(
                        step_order=s.step_order,
                        temperature_celsius=s.temperature_celsius,
                        duration_minutes=s.duration_minutes,
                    )
                    for s in profile.steps
                ],
                step_predictions=[
                    StepPrediction(
                        step_order=sp.step_order,
                        temperature_celsius=sp.temperature_celsius,
                        duration_minutes=sp.duration_minutes,
                        mu_max=sp.mu_max,
                        log_increase=sp.log_increase,
                    )
                    for sp in exec_result.step_predictions
                ],
                growth_description=_format_growth_description(exec_result.total_log_increase),
            )
        
        # Build field_audit once; both provenance list and verbose audit derive from it.
        field_audit = _build_field_audit(result)

        return TranslationResponse(
            success=result.success,
            session_id=result.state.session_id,
            status=result.state.status,
            created_at=result.state.created_at,
            completed_at=completed_at,
            original_query=request.query,
            prediction=prediction,
            provenance=_build_provenance_list(result, field_audit),
            warnings=_build_warnings_list(result),
            error=result.error if not result.success else None,
            audit=_build_audit_detail(result, field_audit) if verbose else None,
        )
        
    except Exception as e:
        return TranslationResponse(
            success=False,
            session_id="error",
            status=SessionStatus.FAILED,
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            original_query=request.query,
            error=str(e),
        )