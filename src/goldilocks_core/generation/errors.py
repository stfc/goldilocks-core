from goldilocks_core.failures import ExpectedFailure


class GenerationError(ExpectedFailure, ValueError):
    kind = "generation_error"
