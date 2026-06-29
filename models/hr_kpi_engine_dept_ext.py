from odoo import api, models

class HrKpiEngineDeptExt(models.AbstractModel):
    _name = 'hr.kpi.engine'
    _inherit = 'hr.kpi.engine'

    # Lấy danh sách nhân viên active trực thuộc phòng ban để tổng hợp KPI cấp phòng.
    @api.model
    def _get_department_active_employees(self, department):
        # Chặn sớm khi chưa có phòng ban để tránh search thừa.
        if not department:
            return self.env["hr.employee"]

        # Chỉ lấy nhân viên đang active cùng phòng ban để bám đúng scope hiện tại.
        return self.env["hr.employee"].sudo().search(
            [("department_id", "=", department.id), ("active", "=", True)]
        )

    # Tính actual cho nguồn system của phòng ban bằng cách cộng kết quả từ từng nhân viên.
    @api.model
    def _compute_department_system_source(
        self, department, dept_kpi_line, date_from, date_to
    ):
        total_actual = 0.0

        # Duyệt từng nhân viên trong phòng để tái sử dụng đúng contract compute() hiện có.
        for employee in self._get_department_active_employees(department):
            total_actual += self.compute(employee, dept_kpi_line, date_from, date_to)

        return total_actual

    # Tính actual cho KPI phòng ban theo đúng loại data source của line.
    @api.model
    def compute_for_department(self, department, dept_kpi_line, date_from, date_to):
        # Chặn sớm các line không thuộc luồng auto để tránh gọi data source thừa.
        if (
            not department
            or not dept_kpi_line
            or not date_from
            or not date_to
            or not dept_kpi_line.is_auto
        ):
            return 0.0

        # Chỉ các line còn liên kết data source mới có thể lấy actual tự động.
        source = dept_kpi_line.data_source_id
        if not source:
            return 0.0

        # Nguồn system không đi qua source.execute(), nên cần aggregate riêng từ nhân viên.
        if source.source_type == "system":
            return self._compute_department_system_source(
                department, dept_kpi_line, date_from, date_to
            )

        # Các nguồn domain/python giữ nguyên cơ chế execute sẵn có của data source.
        return source.execute(
            employee=False,
            start_date=date_from,
            end_date=date_to,
            department=department,
            line=dept_kpi_line,
        )
