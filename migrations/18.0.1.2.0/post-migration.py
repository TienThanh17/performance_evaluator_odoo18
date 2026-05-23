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


def _alter_score_column_to_float(cr, table, column):
    if not _column_exists(cr, table, column):
        return
    cr.execute(
        """
        SELECT data_type
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table, column),
    )
    row = cr.fetchone()
    if row and row[0] not in ("double precision", "numeric"):
        cr.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN {column} TYPE double precision
            USING {column}::double precision
            """
        )


def migrate(cr, version):
    cr.execute(
        """
        INSERT INTO ir_config_parameter (key, value)
        VALUES ('custom_adecsol_hr_performance_evaluator.kpi_score_scale', '10')
        ON CONFLICT (key) DO NOTHING
        """
    )
    _alter_score_column_to_float(cr, "hr_performance_evaluation_line", "employee_rating_score")
    _alter_score_column_to_float(cr, "hr_performance_evaluation_line", "manager_rating_score")
    _alter_score_column_to_float(cr, "hr_department_evaluation_line", "manager_rating_score")
