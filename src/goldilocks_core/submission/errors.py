from goldilocks_core.failures import ExpectedFailure


class SubmissionError(ExpectedFailure, ValueError):
    """A submission-script writer was asked to translate something it
    cannot -- wrong scheduler, no steps, or a step this scheduler cannot
    place. Same pattern as ``generation/errors.py``'s ``GenerationError``,
    kept as its own class rather than reused: a monitoring/API consumer
    reading ``kind`` should be able to tell "the QE input was wrong" apart
    from "the batch script could not be written", and the two packages
    are already split at the directory level for the same reason
    (goldilocks-core-design.md:1261-1271)."""

    kind = "submission_error"
