"""Pure helpers for the add-on uninstall guide: component names, risk, and the Basis work order text."""
import re

COMPONENT_RE = re.compile(r"^[A-Z][A-Z0-9_/-]{0,29}$")
PATCH_TYPES = ("AOI", "AOX", "AOS", "AOU", "CVD")     # install, upgrade, supplement, update, CVD: not a deinstall package


def normalize(component: str) -> str:
    c = component.strip().upper() if isinstance(component, str) else ""
    if not COMPONENT_RE.fullmatch(c):
        raise ValueError(f"Invalid component name '{component}'. Use 1-30 characters: a leading letter, then letters, digits, - _ /.")
    return c


def current_patch(rows: list[dict], release: str) -> str:
    """The component's current patch as SAINT reads it: newest install or update row of this release, by (TO_REL, PATCH)."""
    cand = [r for r in rows if r["COMP_REL"].strip() == release]
    cand.sort(key=lambda r: (r["TO_REL"].strip(), r["PATCH"].strip()), reverse=True)
    return cand[0]["PATCH"].strip() if cand else ""


def risk(custom_objects: int) -> tuple[str, list[str]]:
    """Only what this workflow can see: custom (Z*) objects inside the component's packages. Dependencies between
    components are not read from the system (no reliable table), so they are not part of the risk."""
    level = "HIGH" if custom_objects > 50 else "MEDIUM" if custom_objects > 10 else "LOW"
    return level, ([f"{custom_objects} custom object(s) sit in the packages of this component"] if custom_objects
                   else ["No custom objects found in the packages of this component"])


def work_order(component: str, sid: str, release: str, patch: str, deletable: bool, level: str, factors: list[str], custom_in_use: int) -> str:
    bar, line = "=" * 70, "-" * 70
    return f"""{bar}
  SAP ADD-ON UNINSTALLATION - WORK ORDER
{bar}

Target system: {sid}
Component: {component} (release {release}, current patch {patch or 'not found'})
Uninstallable by SAINT (PAT08 DEINSTALL_ALLOWED): {'YES' if deletable else 'NO - not confirmed, verify before you plan anything'}
Impact: {level}
{chr(10).join('  - ' + f for f in factors)}
Custom objects in the component's packages: {custom_in_use}

Dependencies on other components are NOT determined by this guide. Maintenance Planner calculates them (step 3).

{line}
BASIS ACTIONS
{line}

1. Review the impact above together with the object list of this component.

2. In SAP for Me, open Maintenance Planner (https://apps.support.sap.com/maintenanceplanner)
   and select system {sid} from the landscape.

3. Plan the removal of {component} as a maintenance activity for {sid}. Let Maintenance
   Planner calculate and generate the Stack XML. Do not use a hand-written or AI-generated
   Stack XML. If Maintenance Planner offers no deinstallation item for this component, go to
   step 5 and use the component list of SAINT.

4. Download the Stack XML that Maintenance Planner generates.

5. Log into SAP GUI for {sid} (user with SAP_ALL or equivalent), open transaction /SAINT, click
   "Uninstallable components", and upload the Stack XML (Installation Package > Stack XML File >
   Upload). Check that {component} is the only component selected, then click Start.

6. SAINT runs the removal in phases (prerequisite check, shadow import, modification adjustment,
   activation, cleanup). Watch the SAINT log. The system may need restarts between phases.

{line}
IMPORTANT
{line}
- Plan a maintenance window: the system is in import mode.
- Make sure no users are logged in.
- Back up the system first (at least a database snapshot).
- Plan 30 to 120 minutes per component.
- If an error occurs, do not cancel. Check the SAP Note given in the SAINT message.
{bar}
"""
