from odoo import models, fields, api

class HrKpiEngineDeptExt(models.AbstractModel):
    _name = 'hr.kpi.engine'
    _inherit = 'hr.kpi.engine'

    @api.model
    def compute_for_department(self, department, dept_kpi_line, date_from, date_to):
        if not dept_kpi_line.is_auto:
            return 0.0

        if dept_kpi_line.dept_source_type == 'data_source' and dept_kpi_line.data_source_id:
            return dept_kpi_line.data_source_id.execute(
                employee=False,
                start_date=date_from,
                end_date=date_to,
                department=department,
                line=dept_kpi_line,
            )

        return 0.0
