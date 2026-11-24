class WorkflowFailed(Exception):
    """A clean, user-visible failure. The message goes to the model."""


class WorkflowSuspended(Exception):
    def __init__(self, resume_at):
        super().__init__(f"suspended until {resume_at}")
        self.resume_at = resume_at


class WaitTimeout(WorkflowFailed):
    pass


class RunCancelled(Exception):
    pass


class AmbiguousStep(WorkflowFailed):
    """A step that changes SAP was interrupted; it is not repeated automatically."""
