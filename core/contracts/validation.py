# core/contracts/validation.py — Schema validation for phase outputs
#
# Phase 7.0: Accepts optional phase_schemas dict from WorkflowTemplate.
# Falls back to the global PHASE_SCHEMAS for backward compatibility.

from typing import Dict, Optional, Type

from pydantic import BaseModel, ValidationError

from core.contracts.schemas import PHASE_SCHEMAS


def get_schema_for_phase(
    phase: str,
    *,
    phase_schemas: Optional[Dict[str, Type[BaseModel]]] = None,
) -> Optional[Type[BaseModel]]:
    """Return the expected Pydantic schema for a phase, or None if unstructured.

    Looks up by phase name string. Accepts Phase enum members (str,Enum)
    or plain strings. Uses the provided phase_schemas dict if given,
    otherwise falls back to the global PHASE_SCHEMAS.
    """
    schemas = phase_schemas if phase_schemas is not None else PHASE_SCHEMAS
    # Phase enum members have a .name attribute, but since Phase is str,Enum
    # the member itself IS the string. Use it directly.
    key = phase.name if hasattr(phase, 'name') else phase
    return schemas.get(key)


def validate_phase_output(
    phase: str,
    data,
    *,
    phase_schemas: Optional[Dict[str, Type[BaseModel]]] = None,
) -> BaseModel:
    """Validate output against the expected schema for a phase.

    If data is already an instance of the expected schema, returns it directly.
    If data is a dict, attempts to construct the schema from it.
    Raises ValidationError on failure, ValueError if no schema exists.
    """
    schema = get_schema_for_phase(phase, phase_schemas=phase_schemas)
    if schema is None:
        name = phase.name if hasattr(phase, 'name') else phase
        raise ValueError(f"No schema defined for phase {name}")

    if isinstance(data, schema):
        return data

    if isinstance(data, dict):
        return schema(**data)

    raise ValidationError.from_exception_data(
        title=schema.__name__,
        line_errors=[],
    )
