from odoo import api, SUPERUSER_ID


TABLES = [
    "hr_kpi_line",
    "hr_department_kpi_line",
    "hr_performance_evaluation_line",
    "hr_department_evaluation_line",
]


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


def _get_percent_unit(env):
    Unit = env["hr.kpi.unit"].sudo()
    unit = Unit.search([("code", "=", "percent")], limit=1)
    if unit:
        return unit
    return Unit.create({"name": "%", "code": "percent"})


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    percent_unit = _get_percent_unit(env)
    if not percent_unit:
        return

    for table in TABLES:
        if not _column_exists(cr, table, "target_type") or not _column_exists(cr, table, "unit"):
            continue

        # Bảo toàn dữ liệu cũ: KPI từng được cấu hình là percentage sẽ tự dùng unit "%".
        cr.execute(
            f"""
            UPDATE {table}
               SET unit = %s
             WHERE unit IS NULL
               AND target_type = 'percentage'
            """,
            (percent_unit.id,),
        )
