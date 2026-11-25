"""Workflow reports. Each workflow has its own layout (reports/layouts.py); a workflow without one, a failed call and anything
unexpected fall back to the generic report in sage/report.py, so a download never fails because of a layout."""
import json
import logging

from sage.report import build_report
from sage.reports.kit import Report
from sage.reports.layouts import LAYOUTS

log = logging.getLogger("sage.reports")


def build(workflow: str, meta: dict, call_input: dict, output: str | None) -> bytes:
    layout = LAYOUTS.get(workflow)
    if layout and output and meta.get("status") == "ok":
        try:
            data = json.loads(output)
            if isinstance(data, dict):
                rep = Report(layout[0], meta, call_input, data)
                layout[1](rep)
                return rep.finish()
        except Exception:  # noqa: BLE001 - the generic report still answers the user
            log.exception("report layout of %s failed", workflow)
    return build_report(meta, call_input, output)
