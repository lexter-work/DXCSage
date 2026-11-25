"""Pure helpers for the add-on uninstall guide: component names, risk, and the Basis work order text."""
import re

COMPONENT_RE = re.compile(r"^[A-Z][A-Z0-9_/-]{0,29}$")
PATCH_TYPES = ("AOI", "AOX", "AOS", "AOU", "CVD")     # install, upgrade, supplement, update, CVD: not a deinstall package
# Component dependencies: one row per "COMPONENT requires EXT_COMPONENT". Table and field names are NOT verified on a system:
# if they are wrong the workflow reports that the dependencies could not be read, and these two lines are the place to fix.
DEP_TABLE, DEP_FIELDS = "CVERS_REF", ["COMPONENT", "RELEASE", "EXT_COMPONENT", "EXT_RELEASE"]
CATEGORIES = {"sap_core": "Part of the SAP core or a technical base", "industry_solution": "SAP industry or line-of-business solution",
              "sap_optional": "Optional SAP add-on", "partner_or_customer": "Partner or customer add-on", "unknown": "Could not be told"}


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


def dependents(rows: list[dict], target: str, installed: dict[str, str]) -> tuple[list[str], list[str]]:
    """(installed components that require the target, components the target requires) from the dependency rows."""
    by = sorted({r["COMPONENT"].strip().upper() for r in rows if r["EXT_COMPONENT"].strip().upper() == target and r["COMPONENT"].strip().upper() in installed} - {target})
    needs = sorted({r["EXT_COMPONENT"].strip().upper() for r in rows if r["COMPONENT"].strip().upper() == target and r["EXT_COMPONENT"].strip()} - {target})
    return by, needs


def risk(custom_objects: int, required_by: list[str] = (), category: str = "") -> tuple[str, list[str]]:
    """What this workflow can see: custom (Z*) objects inside the component's packages, installed components that require
    this one, and the category the model gave it (a judgment: it can only raise the level)."""
    level = "HIGH" if custom_objects > 50 else "MEDIUM" if custom_objects > 10 else "LOW"
    factors = ([f"{custom_objects} custom object(s) sit in the packages of this component"] if custom_objects
               else ["No custom objects found in the packages of this component"])
    if required_by:
        level = "HIGH"
        factors.append(f"{len(required_by)} installed component(s) require it: {', '.join(required_by)}")
    if category == "sap_core":
        level = "HIGH"
        factors.append("Classified as part of the SAP core or a technical base (AI judgment)")
    elif category == "industry_solution" and level == "LOW":
        level = "MEDIUM"
        factors.append("Classified as an SAP industry or line-of-business solution (AI judgment)")
    return level, factors


def _deps_text(checked: bool, required_by: list[str], needs: list[str]) -> str:
    if not checked:
        return "Dependencies on other components could NOT be read from this system. Maintenance Planner calculates them (step 3)."
    return ("Components that require it: " + (", ".join(required_by) + ". They must be removed or kept compatible first." if required_by else "none found.") +
            "\nComponents it requires: " + (", ".join(needs) if needs else "none found.") + "\nMaintenance Planner calculates the final result (step 3).")


def work_order(component: str, sid: str, release: str, patch: str, deletable: bool, level: str, factors: list[str], custom_in_use: int,
               checked: bool = False, required_by: list[str] = (), needs: list[str] = (), category: str = "", reason: str = "") -> str:
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

{'Classification (AI judgment, not a fact): ' + CATEGORIES[category] + (' - ' + reason if reason else '') if category else 'Classification: none given.'}
{_deps_text(checked, list(required_by), list(needs))}

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
