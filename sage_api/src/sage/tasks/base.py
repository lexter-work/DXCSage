from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from sage.sap.requirements import Requirement
from sage.sap.rfc import SapRfc


@dataclass
class TaskContext:
    system_id: int | None
    rfc: SapRfc
    settings: Any
    binding: dict
    data_dir: Path | None
    system_label: str = ""
    ssh: Any = None            # SapSsh, for tasks that read files on the host of the system
    workflows: Any = None      # {name: Workflow class}; set for real runs so a workflow can inspect the installed ones


class Task(ABC):
    """One small independent operation. Knows nothing about which workflow calls it."""
    name: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel]]
    requirements: ClassVar[tuple[Requirement, ...]] = ()
    idempotent: ClassVar[bool] = True      # False = changes SAP; never re-run after an interrupted attempt

    @abstractmethod
    async def run(self, ctx: TaskContext, data: BaseModel) -> BaseModel: ...
