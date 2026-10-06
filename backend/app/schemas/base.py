from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for every API shape. Response fields that have a default are still always present, so
    the OpenAPI schema (and the generated TypeScript types) should say they are required."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
