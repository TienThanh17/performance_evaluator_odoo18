from odoo import _, api, fields, models


class HrEvaluation3PSummary(models.Model):
    _name = "hr.evaluation.3p.summary"
    _description = "Department 3P Summary"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_id desc, department_id, id desc"

    name = fields.Char(required=True, tracking=True, default="New")
    department_id = fields.Many2one(
        "hr.department",
        required=True,
        ondelete="restrict",
        tracking=True,
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        required=True,
        ondelete="restrict",
        tracking=True,
    )
    start_date = fields.Date(tracking=True)
    end_date = fields.Date(tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")],
        default="draft",
        tracking=True,
    )
    line_ids = fields.One2many(
        "hr.evaluation.3p.summary.line",
        "summary_id",
        string="Summary Lines",
    )
    line_count = fields.Integer(compute="_compute_line_count")

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.onchange("period_id")
    def _onchange_period_id(self):
        for rec in self:
            if rec.period_id:
                rec.start_date = rec.period_id.date_start
                rec.end_date = rec.period_id.date_end

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("period_id") and not vals.get("start_date"):
                period = self.env["hr.kpi.period"].browse(vals["period_id"])
                vals.setdefault("start_date", period.date_start)
                vals.setdefault("end_date", period.date_end)
            if not vals.get("name") or vals.get("name") == "New":
                vals["name"] = self._build_default_name(
                    vals.get("department_id"), vals.get("period_id")
                )
        return super().create(vals_list)

    @api.model
    def _build_default_name(self, department_id, period_id):
        department = self.env["hr.department"].browse(department_id) if department_id else False
        period = self.env["hr.kpi.period"].browse(period_id) if period_id else False
        if department and period:
            return _("3P Summary - %(department)s - %(period)s") % {
                "department": department.display_name,
                "period": period.display_name,
            }
        return _("3P Summary")

    def action_set_draft(self):
        self.write({"state": "draft"})
        return True

    # Find or create the summary header for a department and KPI period.
    @api.model
    def get_or_create_summary(self, department, period):
        department_id = department.id if hasattr(department, "id") else department
        period_id = period.id if hasattr(period, "id") else period
        summary = self.search(
            [
                ("department_id", "=", department_id),
                ("period_id", "=", period_id),
            ],
            order="id desc",
            limit=1,
        )
        if summary:
            return summary

        period_record = period if hasattr(period, "date_start") else self.env["hr.kpi.period"].browse(period_id)
        return self.create(
            {
                "department_id": department_id,
                "period_id": period_id,
                "start_date": period_record.date_start,
                "end_date": period_record.date_end,
            }
        )

    # Ensure the summary exists and refresh its lines from current evaluations.
    @api.model
    def ensure_summary_for_period(self, department, period):
        summary = self.get_or_create_summary(department, period)
        summary.action_aggregate()
        return summary

    def _get_department_evaluation(self):
        self.ensure_one()
        dept_eval = self.env["hr.department.performance.evaluation"].search(
            [
                ("department_id", "=", self.department_id.id),
                ("period_id", "=", self.period_id.id),
                ("state", "not in", ["draft", "cancel"]),
            ],
            order="id desc",
            limit=1,
        )
        return dept_eval

    # Chuẩn bị dữ liệu một dòng tổng hợp 3P từ đánh giá nhân viên và KPI phòng ban liên quan.
    def _prepare_summary_line_vals(self, evaluation, dept_evaluation):
        linked_dept_eval = evaluation.dept_evaluation_id or dept_evaluation
        p2_1_score = evaluation.get_weighted_score_by_pillar_code("p2_1")
        p2_2_score = evaluation.get_weighted_score_by_pillar_code("p2_2")
        p3_individual_score = evaluation.get_weighted_score_by_pillar_code(
            "p3_individual"
        )
        p3_department_score = (
            linked_dept_eval.dept_kpi_score if linked_dept_eval else 0.0
        )

        return {
            "employee_id": evaluation.employee_id.id,
            "job_id": evaluation.job_id.id,
            "evaluation_id": evaluation.id,
            "dept_evaluation_id": linked_dept_eval.id if linked_dept_eval else False,
            "p1_base_salary": 0.0,
            "p1_allowance": 0.0,
            "p2_1_score_raw": p2_1_score,
            "p2_2_score_raw": p2_2_score,
            "p3_individual_score": p3_individual_score,
            "p3_department_score": p3_department_score,
        }

    def action_aggregate(self):
        SummaryLine = self.env["hr.evaluation.3p.summary.line"]
        for summary in self:
            dept_evaluation = summary._get_department_evaluation()
            evaluations = self.env["hr.performance.evaluation"].search(
                [
                    ("department_id", "=", summary.department_id.id),
                    ("period_id", "=", summary.period_id.id),
                    ("state", "!=", "cancel"),
                ],
                order="employee_id, id",
            )
            commands = [fields.Command.clear()]
            for evaluation in evaluations:
                linked_dept_evaluation = evaluation.dept_evaluation_id or dept_evaluation
                commands.append(
                    fields.Command.create(
                        summary._prepare_summary_line_vals(
                            evaluation, linked_dept_evaluation
                        )
                    )
                )
            summary.write(
                {
                    "line_ids": commands,
                    "state": "done",
                }
            )
        return True


class HrEvaluation3PSummaryLine(models.Model):
    _name = "hr.evaluation.3p.summary.line"
    _description = "Department 3P Summary Line"
    _order = "employee_id, id"

    summary_id = fields.Many2one(
        "hr.evaluation.3p.summary",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="restrict",
    )
    job_id = fields.Many2one(
        "hr.job",
        ondelete="set null",
    )
    evaluation_id = fields.Many2one(
        "hr.performance.evaluation",
        ondelete="set null",
    )
    dept_evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation",
        ondelete="set null",
    )
    p1_base_salary = fields.Float(
        string="P1.1 - Position Salary",
        digits=(16, 0),
        default=0.0,
        help="Base salary for the employee's position. Filled by accounting.",
    )
    p1_allowance = fields.Float(
        string="P1.2 - Title or Professional Allowance",
        digits=(16, 0),
        default=0.0,
        help="Responsibility or professional allowance. Filled by accounting.",
    )
    p2_1_score_raw = fields.Float(string="P2.1")
    p2_2_score_raw = fields.Float(string="P2.2")
    p3_individual_score = fields.Float(string="P3.1.1")
    p3_department_score = fields.Float(string="P3.1.2")
