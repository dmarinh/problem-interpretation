"""
Translation API endpoint.

Main endpoint for translating natural language food safety queries
into structured model inputs and predictions.
"""

from datetime import datetime

from fastapi import APIRouter, status

from app.api.schemas.translation import (
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
from app.models.metadata import ValueSource, BiasType


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
async def translate_query(request: TranslationRequest) -> TranslationResponse:
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