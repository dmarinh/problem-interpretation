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
    ExtractionAuditInfo,
    FieldAuditEntry,
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
from app.models.metadata import InterpretationMetadata, ValueSource, BiasType


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


def _build_provenance_list(result: TranslationResult) -> list[ProvenanceInfo]:
    """Build provenance info from translation result."""
    provenance = []
    
    if result.metadata and result.metadata.provenance:
        for field, prov in result.metadata.provenance.items():
            source_name = prov.source.value if isinstance(prov.source, ValueSource) else str(prov.source)
            
            notes = None
            if prov.transformation_applied:
                notes = prov.transformation_applied
            elif prov.original_text:
                notes = f"From: '{prov.original_text}'"
            
            provenance.append(ProvenanceInfo(
                field=field,
                value=str(prov.original_value) if prov.original_value else "N/A",
                source=source_name,
                confidence=prov.confidence,
                notes=notes,
            ))
    
    return provenance


def _build_warnings_list(result: TranslationResult) -> list[WarningInfo]:
    """Build warnings list from translation result."""
    warnings = []
    
    if result.metadata:
        # Add bias corrections as warnings
        for correction in result.metadata.bias_corrections:
            warnings.append(WarningInfo(
                type="bias_correction",
                message=correction.correction_reason,
                field=correction.field_name,
            ))
        
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


_NONE_APPLIED = ["(none applied)"]


def _build_audit_detail(result: TranslationResult) -> AuditDetail:
    """
    Build the full verbose audit payload from a completed TranslationResult.

    Every list-valued AuditSummary field uses ["(none applied)"] when empty
    so that consumers can distinguish "not requested" (null) from "nothing
    happened" (explicit sentinel).
    """
    metadata: InterpretationMetadata | None = result.metadata
    if metadata is None:
        # Shouldn't happen on a successful translation, but guard defensively.
        return AuditDetail(
            field_audit={},
            combase_model=None,
            audit=AuditSummary(
                bias_corrections=_NONE_APPLIED,
                range_clamps=_NONE_APPLIED,
                defaults_imputed=_NONE_APPLIED,
                warnings=_NONE_APPLIED,
                overall_confidence=0.0,
                confidence_formula=None,
            ),
            system=None,
        )

    # ── Index standardization corrections by field so we can join them below ──
    bias_by_field: dict[str, str] = {
        c.field_name: c.correction_reason for c in metadata.bias_corrections
    }
    clamp_by_field: dict[str, str] = {
        c.field_name: (
            f"clamped {c.original_value} → {c.clamped_value}"
            f" (valid range [{c.valid_min}, {c.valid_max}])"
        )
        for c in metadata.range_clamps
    }
    default_by_field: dict[str, str] = {}
    for d in metadata.defaults_imputed:
        # Format: "fieldname (defaulted to X)" — extract the field name prefix
        field_key = d.split(" (")[0].strip()
        default_by_field[field_key] = d

    # ── Index retrieval results by their query prefix for field matching ──
    # Each retrieval is associated with the grounding call that produced it;
    # the link is positional rather than by field name, so we just attach the
    # most relevant retrieval for each RAG-sourced field.
    rag_retrievals = {r.query: r for r in (metadata.retrievals or [])}

    # ── Per-field audit ────────────────────────────────────────────────────────
    field_audit: dict[str, FieldAuditEntry] = {}

    for field_name, prov in (metadata.provenance or {}).items():
        source_str = (
            prov.source.value if isinstance(prov.source, ValueSource) else str(prov.source)
        )

        # Retrieval block — only for RAG-sourced fields
        retrieval_info: RetrievalAuditInfo | None = None
        if prov.source == ValueSource.RAG_RETRIEVAL and rag_retrievals:
            # Pick the retrieval whose query best matches this field
            # (food-properties query for ph/aw, pathogen query for organism)
            r = next(iter(rag_retrievals.values()))  # closest match heuristic
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

        # Extraction block
        extraction_info: ExtractionAuditInfo | None = None
        if prov.extraction_method is not None or prov.raw_match is not None:
            extraction_info = ExtractionAuditInfo(
                method=prov.extraction_method,
                raw_match=prov.raw_match,
                parsed_range=prov.parsed_range,
            )

        # Standardization block — join bias/clamp/default for this field
        std_info = StandardizationAuditInfo(
            bias_correction=bias_by_field.get(field_name),
            range_clamp=clamp_by_field.get(field_name),
            default_imputed=default_by_field.get(field_name),
        )
        has_std = any([std_info.bias_correction, std_info.range_clamp, std_info.default_imputed])

        field_audit[field_name] = FieldAuditEntry(
            final_value=result.state.grounded_values.get(field_name) if result.state.grounded_values else None,
            source=source_str,
            field_confidence=prov.confidence,
            confidence_derivation=prov.confidence_derivation,
            retrieval=retrieval_info,
            extraction=extraction_info,
            standardization=std_info if has_std else None,
        )

    # ── Top-level audit summary ────────────────────────────────────────────────
    bias_list = [c.correction_reason for c in metadata.bias_corrections] or _NONE_APPLIED
    clamp_list = [
        f"{c.field_name}: {c.original_value} → {c.clamped_value}"
        for c in metadata.range_clamps
    ] or _NONE_APPLIED
    defaults_list = metadata.defaults_imputed or _NONE_APPLIED
    warnings_list = metadata.warnings or _NONE_APPLIED

    audit_summary = AuditSummary(
        bias_corrections=bias_list,
        range_clamps=clamp_list,
        defaults_imputed=defaults_list,
        warnings=warnings_list,
        overall_confidence=metadata.overall_confidence,
        confidence_formula=metadata.confidence_formula,
    )

    # ── ComBase model block ────────────────────────────────────────────────────
    cb_info: ComBaseModelAuditInfo | None = None
    if metadata.combase_model:
        cm = metadata.combase_model
        cb_info = ComBaseModelAuditInfo(
            organism=cm.organism,
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
        
        return TranslationResponse(
            success=result.success,
            session_id=result.state.session_id,
            status=result.state.status,
            created_at=result.state.created_at,
            completed_at=completed_at,
            original_query=request.query,
            prediction=prediction,
            provenance=_build_provenance_list(result),
            warnings=_build_warnings_list(result),
            overall_confidence=result.metadata.overall_confidence if result.metadata else None,
            error=result.error if not result.success else None,
            audit=_build_audit_detail(result) if verbose else None,
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