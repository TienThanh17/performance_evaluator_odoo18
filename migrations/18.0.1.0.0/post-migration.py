import re

from odoo import api, SUPERUSER_ID


TABLES = [
    "hr_kpi_line",
    "hr_department_kpi_line",
    "hr_performance_evaluation_line",
    "hr_department_evaluation_line",
]

DEFAULT_UNITS = {
    "%": ("percent", "%"),
    "điểm": ("score", "điểm"),
    "ngày": ("day", "ngày"),
    "task": ("task", "task"),
}


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def _slug(value):
    code = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return code or "unit"


def _get_or_create_unit(env, legacy_value):
    Unit = env["hr.kpi.unit"].sudo()
    legacy_value = (legacy_value or "").strip()
    if not legacy_value:
        return Unit.browse()

    code, name = DEFAULT_UNITS.get(legacy_value, (_slug(legacy_value), legacy_value))
    unit = Unit.search(["|", ("code", "=", code), ("name", "=", name)], limit=1)
    if unit:
        return unit

    base_code = code
    suffix = 2
    while Unit.search([("code", "=", code)], limit=1):
        code = f"{base_code}_{suffix}"
        suffix += 1
    return Unit.create({"name": name, "code": code})


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    for legacy_value, (code, name) in DEFAULT_UNITS.items():
        unit = env["hr.kpi.unit"].sudo().search([("code", "=", code)], limit=1)
        if not unit:
            env["hr.kpi.unit"].sudo().create({"name": name, "code": code})

    for table in TABLES:
        if not _column_exists(cr, table, "unit_label_legacy") or not _column_exists(cr, table, "unit"):
            continue
        cr.execute(
            f"""
            SELECT DISTINCT unit_label_legacy
              FROM {table}
             WHERE unit_label_legacy IS NOT NULL
               AND btrim(unit_label_legacy) != ''
            """
        )
        for (legacy_value,) in cr.fetchall():
            unit = _get_or_create_unit(env, legacy_value)
            if not unit:
                continue
            cr.execute(
                f"""
                UPDATE {table}
                   SET unit = %s
                 WHERE unit IS NULL
                   AND unit_label_legacy = %s
                """,
                (unit.id, legacy_value),
            )
