# core/contracts/validation.py — Schema validation for phase outputs

from typing import Optional, Type

from pydantic import BaseModel, ValidationError

from core.kernel.state import Phase
from core.contracts.schemas import PHASE_SCHEMAS


def get_schema_for_phase(phase: Phase) -> Optional[Type[BaseModel]]:
    """Return the expected Pydantic schema for a phase, or None if unstructured."""
    return PHASE_SCHEMAS.get(phase.name)


def validate_phase_output(phase: Phase, data) -> BaseModel:
    """Validate output against the expected schema for a phase.

    If data is already an instance of the expected schema, returns it directly.
    If data is a dict, attempts to construct the schema from it.
    Raises ValidationError on failure, ValueError if no schema exists.
    """
    schema = get_schema_for_phase(phase)
    if schema is None:
        raise ValueError(f"No schema defined for phase {phase.name}")

    if isinstance(data, schema):
        return data

    if isinstance(data, dict):
        return schema(**data)

    raise ValidationError.from_exception_data(
        title=schema.__name__,
        line_errors=[],
    )
