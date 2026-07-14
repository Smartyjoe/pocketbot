from pydantic import BaseModel, ConfigDict, field_validator


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    broker_name: str = "pocketoption"

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        stripped = v.strip().upper()
        if not stripped:
            raise ValueError("Symbol code must not be empty")
        return stripped

    def __str__(self) -> str:
        return self.code

    def __hash__(self) -> int:
        return hash((self.code, self.broker_name))
