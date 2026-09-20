"""Public planning failures never include upstream URLs, tokens or SQL details."""


class PlanningError(Exception):
    def __init__(self, code: str, status: int = 422, **details):
        self.code = code
        self.status = status
        self.details = details
        super().__init__(code)
