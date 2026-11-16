"""Errors shared by the writers, kept apart so no provider module imports another."""


class WriterError(Exception):
    """The writer could not produce a draft: credentials, network, a refusal, a cut-off reply."""
