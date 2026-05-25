from odoo import models, fields, api

class HrKpiEngineDeptExt(models.AbstractModel):
    _name = 'hr.kpi.engine'
    _inherit = 'hr.kpi.engine'

    @api.model
    def compute_for_department(self, department, dept_kpi_line, date_from, date_to):
        if not dept_kpi_line.is_auto:
            return 0.0

        if dept_kpi_line.dept_source_type == 'child_kpi_average':
            return self._compute_child_kpi_average(department, dept_kpi_line, date_from, date_to)
        if dept_kpi_line.dept_source_type == 'data_source' and dept_kpi_line.data_source_id:
            return dept_kpi_line.data_source_id.execute(
                employee=False,
                start_date=date_from,
                end_date=date_to,
                department=department,
                line=dept_kpi_line,
            )

        return 0.0

    @api.model
    def _compute_child_kpi_average(self, department, dept_kpi_line, date_from, date_to):
        """Bottom-up category score from linked employee KPI child lines.

        Returns an actual category score on the configured KPI score scale.
        Department evaluation scoring compares this value with target=score_base.
        """
        dept_eval_line = self.env.context.get('department_evaluation_line')
        if dept_eval_line:
            dept_eval_line = self.env['hr.department.evaluation.line'].browse(dept_eval_line).exists()

        domain = [
            ('evaluation_id.employee_id.department_id', '=', department.id),
            ('evaluation_id.start_date', '>=', date_from),
            ('evaluation_id.end_date', '<=', date_to),
            ('is_section', '=', False),
        ]
        if dept_eval_line:
            domain.append(('parent_dept_evaluation_line_id', '=', dept_eval_line.id))
        else:
            domain.append(('parent_dept_line_id', '=', dept_kpi_line.id))

        child_lines = self.env['hr.performance.evaluation.line'].sudo().search(domain)
        if not child_lines:
            return 0.0

        scores_by_employee = {}
        for child_line in child_lines:
            employee = child_line.evaluation_id.employee_id
            if not employee:
                continue
            score = (child_line.final_rating or 0.0)
            weight = child_line.weight or 0.0
            if weight <= 0.0:
                continue
            bucket = scores_by_employee.setdefault(employee.id, {'weighted': 0.0, 'weight': 0.0})
            bucket['weighted'] += score * weight
            bucket['weight'] += weight

        employee_scores = [
            bucket['weighted'] / bucket['weight']
            for bucket in scores_by_employee.values()
            if bucket['weight'] > 0.0
        ]
        if not employee_scores:
            return 0.0

        return sum(employee_scores) / len(employee_scores)
