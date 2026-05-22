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


def migrate(cr, version):
    for table in TABLES:
        if not _column_exists(cr, table, "unit_label"):
            continue
        if _column_exists(cr, table, "unit_label_legacy"):
            cr.execute(
                f"""
                UPDATE {table}
                   SET unit_label_legacy = COALESCE(unit_label_legacy, unit_label)
                 WHERE unit_label IS NOT NULL
                """
            )
            continue
        cr.execute(f'ALTER TABLE {table} RENAME COLUMN unit_label TO unit_label_legacy')
