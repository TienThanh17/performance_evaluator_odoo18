from odoo import api, models

class HrKpiEngineDeptExt(models.AbstractModel):
    _name = 'hr.kpi.engine'
    _inherit = 'hr.kpi.engine'

    # Tính actual cho KPI phòng ban chỉ khi line có data source và đang bật auto compute.
    @api.model
    def compute_for_department(self, department, dept_kpi_line, date_from, date_to):
        # Chặn sớm các line không thuộc luồng auto để tránh gọi data source thừa.
        if not dept_kpi_line.is_auto:
            return 0.0

        # Chỉ các line còn liên kết data source mới có thể lấy actual tự động.
        if dept_kpi_line.data_source_id:
            return dept_kpi_line.data_source_id.execute(
                employee=False,
                start_date=date_from,
                end_date=date_to,
                department=department,
                line=dept_kpi_line,
            )

        return 0.0
