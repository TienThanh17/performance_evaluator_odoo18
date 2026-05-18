import json

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrDepartmentKpiLine(models.Model):
    _name = "hr.department.kpi.line"
    _description = "Department KPI Line"

    name = fields.Char(string="Tên Tiêu Chí", required=True)
    kpi_type = fields.Selection(
        [
            ("quantitative", "Quantitative"),
            ("binary", "Binary"),
            ("rating", "Rating"),
            ("score", "Score"),
        ],
        required=True,
        default="quantitative",
    )
    description = fields.Html(
        string="Description",
        sanitize=True,
        help="Additional guidance for employees/managers about how this KPI should be evaluated.",
    )

    target = fields.Float(default=0.0)
    target_type = fields.Selection(
        [("value", "Value"), ("percentage", "Percentage")], default="value"
    )
    direction = fields.Selection(
        [("higher_better", "Higher is better"), ("lower_better", "Lower is better")],
        default="higher_better",
    )
    weight = fields.Float(default=1.0)
    is_auto = fields.Boolean(
        default=False,
        compute="_compute_auto",
        store=True,
        help="Enable to let the system automatically compute Actual values from the selected Data Source.",
    )
    target_display = fields.Char(
        string="Target", compute="_compute_display", store=False
    )
    unit_label = fields.Char(
        string="Unit",
        default="",
        help="Display unit for Target/Actual, e.g. %, tasks, days, score.",
    )

    data_source = fields.Selection(
        [
            ("manual", "Manual"),
            # ('dept_task_completion', 'Tỷ lệ hoàn thành task phòng ban'),
            # ('dept_attendance_rate', 'Tỷ lệ chuyên cần phòng ban'),
            # ('dept_avg_individual', 'TB điểm cá nhân (auto-aggregated)'),
            ("child_kpi_average", "Tự động tổng hợp từ KPI con"),
        ],
        default="manual",
    )

    is_section = fields.Boolean(default=False)
    sequence = fields.Integer(default=10)
    department_kpi_id = fields.Many2one("hr.department.kpi", ondelete="cascade")
    child_template_line_ids = fields.One2many(
        "hr.kpi.line",
        "parent_dept_line_id",
        string="Child KPI Template Lines",
        readonly=True,
    )
    child_template_line_count = fields.Integer(
        string="Child KPI Template Count",
        compute="_compute_child_template_line_trace",
        store=False,
    )
    child_template_rows_json = fields.Text(
        string="Child KPI Template Rows JSON",
        compute="_compute_child_template_line_trace",
        store=False,
    )

    @api.depends(
        "child_template_line_ids",
        "child_template_line_ids.kpi_id",
        "child_template_line_ids.kpi_id.name",
        "child_template_line_ids.kpi_id.job_id",
        "child_template_line_ids.kpi_id.job_id.name",
        "child_template_line_ids.key_performance_area",
        "child_template_line_ids.weight",
        "child_template_line_ids.target",
        "child_template_line_ids.target_type",
        "child_template_line_ids.unit_label",
        "child_template_line_ids.is_section",
    )
    def _compute_child_template_line_trace(self):
        for line in self:
            child_lines = line.child_template_line_ids.filtered(
                lambda child: not child.is_section
            ).sorted(
                key=lambda child: (
                    child.kpi_id.name or "",
                    child.sequence or 0,
                    child.key_performance_area or "",
                    child.id or 0,
                )
            )
            line.child_template_line_count = len(child_lines)
            if not child_lines:
                line.child_template_rows_json = "[]"
                continue

            child_rows = []
            for child_line in child_lines:
                kpi_template = child_line.kpi_id
                job = kpi_template.job_id
                child_rows.append(
                    {
                        "kpi_template_id": kpi_template.id or False,
                        "kpi_template": kpi_template.name or "",
                        "job_name": job.name or "",
                        "child_kpi_id": child_line.id or False,
                        "child_kpi": child_line.key_performance_area or "",
                        "weight": child_line.weight or 0.0,
                        "target_display": child_line.target_display or "",
                    }
                )
            line.child_template_rows_json = json.dumps(child_rows, ensure_ascii=False)

    @api.constrains("kpi_type", "target")
    def _check_numeric_target(self):
        for rec in self:
            if rec.is_section:
                continue
            if rec.kpi_type == "quantitative" and (rec.target or 0.0) < 0.0:
                raise ValidationError(
                    "For Quantitative KPI type, Target must be greater than or equal 0."
                )

    def _get_default_unit_label(self):
        self.ensure_one()
        if self.target_type == "percentage":
            return "%"
        return {
            "dept_task_completion": "task",
            "dept_attendance_rate": "%",
            "dept_avg_individual": "điểm",
            "child_kpi_average": "điểm",
        }.get(self.data_source or "manual", "")

    @api.onchange("target_type", "data_source")
    def _onchange_unit_label(self):
        for rec in self:
            rec.unit_label = rec._get_default_unit_label()

    @api.depends("target", "target_type", "kpi_type", "unit_label")
    def _compute_display(self):
        for rec in self:
            if rec.is_section:
                rec.target_display = ""
                continue
            if rec.kpi_type != "quantitative":
                rec.target_display = ""
                continue

            if rec.target_type == "percentage":
                # hiển thị 90% thay vì 90.0
                rec.target_display = f"{(rec.target or 0.0):g}%"
            else:
                target = f"{(rec.target or 0.0):g}"
                rec.target_display = (
                    f"{target} {rec.unit_label}" if rec.unit_label else target
                )

    @api.depends("kpi_type", "data_source")
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(
                rec.kpi_type == "quantitative" and rec.data_source != "manual"
            )
