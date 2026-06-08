from odoo import _


KPI_TYPE_SELECTION = [
    ("auto", "Auto"),
    ("manual", "Manual"),
]

MANUAL_SCORING_TYPE_SELECTION = [
    ("binary", "Binary"),
    ("rating", "Rating"),
    ("score", "Score"),
]

# Build a reusable validation message for manual KPI lines without a subtype.
def get_manual_scoring_type_required_message():
    return _("Please select a manual scoring type for manual KPI lines.")
