from odoo import models, fields, api


class HrDepartment(models.Model):
    _inherit = "hr.department"

    # # ── DEPRECATED: department_score — điểm tổng hợp kiểu cũ (α×dept + β×avg_individual) ──
    # # Giữ trong DB để backward compatible. Ẩn khỏi mọi view.
    # department_score = fields.Float(
    #     compute="_compute_department_score_custom",
    #     string="Department KPI Score (latest period)",
    #     deprecated=True,
    #     groups="base.group_no_one",
    # )
    #
    # # ── DEPRECATED: department_level — xếp loại dựa trên department_score cũ ──
    # department_level = fields.Selection(
    #     [("excellent", "Excellent"), ("pass", "Pass"), ("fail", "Fail")],
    #     compute="_compute_department_score_custom",
    #     string="Performance Level",
    #     deprecated=True,
    #     groups="base.group_no_one",
    # )

    dept_kpi_score = fields.Float(
        string="Department KPI Score",
        compute="_compute_dept_kpi_score",
        help="Latest department KPI score from department performance evaluations.",
    )

    department_evaluation_ids = fields.One2many(
        "hr.department.performance.evaluation",
        "department_id",
        string="Department Evaluations",
    )

    # def _compute_department_score_custom(self):
    #     """Giữ nguyên logic cũ để không break dữ liệu đang lưu trong DB.
    #     Các field này đã được đánh dấu deprecated và ẩn khỏi UI.
    #     """
    #     for rec in self:
    #         eval_record = self.env["hr.department.performance.evaluation"].search(
    #             [("department_id", "=", rec.id), ("state", "=", "approved")],
    #             order="end_date desc",
    #             limit=1,
    #         )
    #
    #         if eval_record:
    #             rec.department_score = eval_record.department_score
    #             rec.department_level = eval_record.department_level
    #         else:
    #             rec.department_score = 0.0
    #             rec.department_level = False

    @api.depends(
        "department_evaluation_ids.dept_kpi_score",
        "department_evaluation_ids.end_date",
        "department_evaluation_ids.start_date",
        "department_evaluation_ids.state",
    )
    def _compute_dept_kpi_score(self):
        for dept in self:
            evaluation = self.env["hr.department.performance.evaluation"].search(
                [
                    ("department_id", "=", dept.id),
                    ("state", "!=", "cancel"),
                ],
                order="end_date desc, start_date desc, id desc",
                limit=1,
            )
            dept.dept_kpi_score = (
                evaluation.get_dept_kpi_score() if evaluation else 0.0
            )

    def action_department_score_view(self):
        """Open department KPI evaluations related to the current department."""
        self.ensure_one()
        return {
            "name": "Department KPI Score",
            "domain": [("department_id", "=", self.id)],
            "res_model": "hr.department.performance.evaluation",
            "type": "ir.actions.act_window",
            "view_id": False,
            "view_mode": "list,form",
            "help": """<p class="oe_view_nocontent_create">
                        Click to create a new department performance evaluation.
                       </p>""",
            "limit": 80,
            "context": {"default_department_id": self.id},
        }
