"""Filing-event signal taxonomy shared by live alerts and the event study.

Each signal has an expected direction from the literature or common sense
("-" negative, "+" positive, "?" depends on content) and a severity (1-3) used
to rank alerts. Whether a signal actually predicts returns is what the event
study measures; the expected direction here is only a prior.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SignalDef:
    code: str
    label: str
    direction: str  # "-", "+", "?"
    severity: int  # 1 low .. 3 high
    why: str


# 8-K items. 7.01 (Reg FD), 8.01 (other) and 9.01 (exhibits) are too generic to be signals.
ITEM_SIGNALS: dict[str, SignalDef] = {
    "1.01": SignalDef("material_agreement", "Material agreement", "?", 1, "New contract, partnership or financing agreement"),
    "1.02": SignalDef("agreement_terminated", "Agreement terminated", "-", 2, "A material agreement was ended"),
    "1.03": SignalDef("bankruptcy", "Bankruptcy / receivership", "-", 3, "Chapter 11/7 filing or receivership"),
    "1.05": SignalDef("cyber_incident", "Cybersecurity incident", "-", 2, "Material cybersecurity incident disclosed"),
    "2.01": SignalDef("acquisition_completed", "Acquisition / disposal completed", "?", 1, "Completed buying or selling a significant business"),
    "2.02": SignalDef("earnings", "Earnings release", "?", 1, "Results of operations; direction depends on the numbers"),
    "2.03": SignalDef("new_debt", "New debt obligation", "?", 1, "Took on a material loan, note or lease"),
    "2.04": SignalDef("debt_acceleration", "Debt default / acceleration", "-", 3, "Triggering event that accelerates an obligation"),
    "2.05": SignalDef("restructuring", "Restructuring / layoffs", "-", 2, "Exit or disposal costs, often layoffs"),
    "2.06": SignalDef("impairment", "Asset impairment", "-", 2, "Material write-down of assets"),
    "3.01": SignalDef("delisting_notice", "Delisting notice", "-", 3, "Exchange says the company fails a listing rule (often price < $1)"),
    "3.02": SignalDef("unregistered_equity", "Unregistered share sale", "-", 2, "Sold shares privately: dilution, often at a discount"),
    "4.01": SignalDef("auditor_change", "Auditor change", "-", 2, "Auditor resigned or was dismissed"),
    "4.02": SignalDef("non_reliance", "Restatement (non-reliance)", "-", 3, "Past financial statements should no longer be relied on"),
    "5.01": SignalDef("control_change", "Change in control", "?", 2, "A new party controls the company"),
    "5.02": SignalDef("officer_change", "Executive / director change", "?", 1, "Departure or appointment of officers or directors"),
}

# Non-8-K forms that are events in themselves.
FORM_SIGNALS: dict[str, SignalDef] = {
    "424B4": SignalDef("offering_priced", "Offering priced (424B)", "-", 2, "Final prospectus: an offering was priced (dilutive if it is stock)"),
    "424B5": SignalDef("offering_priced", "Offering priced (424B)", "-", 2, "Final prospectus for a shelf takedown (dilutive if it is stock)"),
    "S-1": SignalDef("offering_registered", "Offering registered (S-1)", "-", 1, "Registered shares to sell later"),
    "S-3": SignalDef("shelf_registered", "Shelf registration (S-3)", "-", 1, "Can sell shares at any time in the next 3 years"),
    "SCHEDULE 13D": SignalDef("activist_stake", "5%+ activist stake", "+", 2, "An investor took a 5%+ stake with intent to influence"),
    "SC 13D": SignalDef("activist_stake", "5%+ activist stake", "+", 2, "An investor took a 5%+ stake with intent to influence"),
}

ALL_SIGNALS: dict[str, SignalDef] = {s.code: s for s in [*ITEM_SIGNALS.values(), *FORM_SIGNALS.values()]}

# Forms the live EDGAR source pulls (8-K handled separately via items)
EVENT_FORMS = ["8-K", "424B4", "424B5", "S-1", "S-3", "SCHEDULE 13D"]


def signals_for_filing(form: str, items: list[str]) -> list[SignalDef]:
    """Signals for one filing, most severe first, deduped by code."""
    base_form = form.removesuffix("/A")
    found: dict[str, SignalDef] = {}
    if base_form == "8-K":
        for item in items:
            if (sig := ITEM_SIGNALS.get(item)) is not None:
                found.setdefault(sig.code, sig)
    elif (sig := FORM_SIGNALS.get(base_form)) is not None:
        found[sig.code] = sig
    return sorted(found.values(), key=lambda s: -s.severity)


def signal_dict(sig: SignalDef) -> dict:
    return asdict(sig)
