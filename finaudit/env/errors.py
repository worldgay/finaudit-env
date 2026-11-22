"""EnvError: единственный тип исключения, превращаемый в observation с ошибкой."""
from __future__ import annotations

ERROR_CODES = ("UNKNOWN_ACTION", "BAD_ARGS", "UNKNOWN_TABLE", "NOT_FOUND", "BAD_CURSOR",
               "LIMIT_TOO_LARGE", "BAD_EXPRESSION", "EPISODE_DONE", "INVALID_FINDINGS")


class EnvError(Exception):
    """Ошибка для агента: код из закрытого списка и короткое сообщение."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(code)
        super().__init__(message)
        self.code = code
        self.message = message[:120]
