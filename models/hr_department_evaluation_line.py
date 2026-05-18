import json

from odoo import models, fields, api, _


class HrDepartmentEvaluationLine(models.Model):
    _name = "hr.department.evaluation.line"
    _description = "Department Evaluation Line"

    evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation", ondelete="cascade"
    )
    department_kpi_line_id = fields.Many2one("hr.department.kpi.line")

    name = fields.Char()
    kpi_type = fields.Selection(
        [
            ("quantitative", "Quantitative"),
            ("binary", "Binary"),
            ("rating", "Rating"),
            ("score", "Score"),
        ], string=_("KPI Type")
    )
    target = fields.Float()
    target_type = fields.Selection([("value", "Value"), ("percentage", "Percentage")])
    direction = fields.Selection(
        [("higher_better", "Higher is better"), ("lower_better", "Lower is better")]
    )
    actual = fields.Float()
    unit_label = fields.Char(
        string="Unit",
        default="",
        help="Display unit for Target/Actual, e.g. %, tasks, days, score.",
    )
    weight = fields.Float()
    is_auto = fields.Boolean()
    data_source = fields.Selection(
        [
            ("manual", "Manual"),
            # ("dept_task_completion", "Tỷ lệ hoàn thành task phòng ban"),
            # ("dept_attendance_rate", "Tỷ lệ chuyên cần phòng ban"),
            # ("dept_avg_individual", "TB điểm cá nhân (auto-aggregated)"),
            ("child_kpi_average", "Tự động tổng hợp từ KPI con"),
        ],
        default="manual",
    )
    is_section = fields.Boolean()
    description = fields.Html(
        string="Description",
        sanitize=True,
    )
    sequence = fields.Integer(default=10)

    system_score = fields.Float(compute="_compute_system_score", store=True)
    final_score = fields.Float(compute="_compute_final_score", store=True)
    # Technical field used by the UI to colorize final_score as a badge.
    final_score_badge_class = fields.Char(
        string="Final Rating Badge Class",
        compute="_compute_final_score_badge_class",
        store=False,
    )
    # Always-formatted text for UI badge rendering (keeps 0.0 visible).
    final_score_badge_text = fields.Char(
        string="Final Rating",
        compute="_compute_final_score_badge_text",
        store=False,
    )

    _BINARY_YN = [("yes", "Yes"), ("no", "No")]
    manager_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Manager Rating (Binary)",
    )

    _RATING_0_5 = [
        ("0", "0"),
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ]
    manager_rating_selection = fields.Selection(
        selection=_RATING_0_5,
        string="Manager Rating (0-5)",
        default="0",
    )

    manager_rating_score = fields.Integer(
        string="Manager Rating (Score)",
        default=0,
    )

    manager_comment = fields.Text()

    # Formatted Target value for display(shows % when Target Type is Percentage).
    target_display = fields.Char(
        string="Target",
        compute="_compute_display",
        store=False,
    )
    # Formatted Actual value for display(shows % when Target Type is Percentage).
    actual_display = fields.Char(
        string="Actual",
        compute="_compute_display",
        store=False,
    )
    child_evaluation_line_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "parent_dept_evaluation_line_id",
        string="Child KPI Lines",
        readonly=True,
    )
    child_evaluation_line_count = fields.Integer(
        string="Child KPI Count",
        compute="_compute_child_line_trace",
        store=False,
    )
    child_line_rows_json = fields.Text(
        string="Child KPI Rows JSON",
        compute="_compute_child_line_trace",
        store=False,
    )

    @api.depends(
        "child_evaluation_line_ids",
        "child_evaluation_line_ids.kpi_line_id",
        "child_evaluation_line_ids.key_performance_area",
        "child_evaluation_line_ids.final_rating",
        "child_evaluation_line_ids.weight",
        "child_evaluation_line_ids.evaluation_id",
        "child_evaluation_line_ids.evaluation_id.name",
        "child_evaluation_line_ids.evaluation_id.employee_id",
        "child_evaluation_line_ids.evaluation_id.employee_id.name",
    )
    def _compute_child_line_trace(self):
        for line in self:
            child_lines = line.child_evaluation_line_ids.filtered(
                lambda l: not l.is_section
            ).sorted(
                key=lambda l: (
                    l.key_performance_area or "",
                    l.evaluation_id.employee_id.name or "",
                    l.sequence or 0,
                    l.id or 0,
                )
            )
            line.child_evaluation_line_count = len(child_lines)
            if not child_lines:
                line.child_line_rows_json = "[]"
                continue
            child_rows = []
            for child_line in child_lines:
                evaluation = child_line.evaluation_id
                employee = evaluation.employee_id
                child_rows.append(
                    {
                        "employee": employee.name or "",
                        "employee_id": employee.id or False,
                        "child_kpi": child_line.key_performance_area or "",
                        "child_kpi_id": child_line.kpi_line_id.id or False,
                        "weight": child_line.weight or 0.0,
                        "final_rating": child_line.final_rating or 0.0,
                        "evaluation": evaluation.display_name or evaluation.name or "",
                        "evaluation_id": evaluation.id or False,
                    }
                )
            line.child_line_rows_json = json.dumps(child_rows, ensure_ascii=False)

    @api.depends(
        "actual",
        "target",
        "kpi_type",
        "direction",
        "target_type",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
    )
    def _compute_system_score(self):
        for line in self:
            if line.is_section:
                line.system_score = 0.0
                continue

            score = 0.0
            actual = line.actual or 0.0
            target = line.target or 0.0

            if line.kpi_type == "quantitative":
                if line.direction == "higher_better":
                    score = (actual / target) * 100.0 if target > 0 else 100.0
                else:
                    score = (target / actual) * 100.0 if actual > 0 else 100.0
            elif line.kpi_type == "binary":
                val = line.manager_rating_binary
                score = 100.0 if val == "yes" else 0.0
            elif line.kpi_type == "rating":
                raw = line.manager_rating_selection or "0"
                rating = float(raw)
                score = (rating / 5.0) * 100.0
            elif line.kpi_type == "score":
                val = line.manager_rating_score or 0
                score = float(val)

            line.system_score = max(0.0, min(score, 100.0))

    @api.depends("system_score")
    def _compute_final_score(self):
        for line in self:
            # scale 10
            line.final_score = line.system_score / 10

    # Thay thế hàm hiện tại bằng đoạn code này:
    @api.depends("target", "actual", "target_type", "kpi_type", "unit_label")
    def _compute_display(self):
        for rec in self:
            if rec.kpi_type != "quantitative":
                rec.target_display = ""
                rec.actual_display = ""
                continue

            # Format 2 chữ số thập phân, cắt bỏ số 0 và dấu chấm thừa ở đuôi
            target_str = f"{(rec.target or 0.0):.2f}".rstrip("0").rstrip(".")
            actual_str = f"{(rec.actual or 0.0):.2f}".rstrip("0").rstrip(".")

            if rec.target_type == "percentage":
                rec.target_display = f"{target_str}%"
                rec.actual_display = f"{actual_str}%"
            else:
                rec.target_display = (
                    f"{target_str} {rec.unit_label}" if rec.unit_label else target_str
                )
                rec.actual_display = (
                    f"{actual_str} {rec.unit_label}" if rec.unit_label else actual_str
                )

    @api.depends("final_score")
    def _compute_final_score_badge_class(self):
        excellent, passed = self.env["res.config.settings"].get_thresholds()
        for line in self:
            score = line.final_score or 0.0
            if score >= excellent:
                line.final_score_badge_class = "o_kpi_badge_excellent"
            elif score >= passed:
                line.final_score_badge_class = "o_kpi_badge_pass"
            else:
                line.final_score_badge_class = "o_kpi_badge_fail"

    @api.depends("final_score")
    def _compute_final_score_badge_text(self):
        for line in self:
            score = line.final_score or 0.0

            # An toàn: Làm tròn score về 2 chữ số trước khi xét để tránh lỗi floating point
            rounded_score = round(score, 2)

            # Nếu là số nguyên (ví dụ 0.0, 10.0, 8.0) thì in ra số nguyên cho gọn
            if rounded_score.is_integer():
                line.final_score_badge_text = str(int(rounded_score))
            # Nếu có phần lẻ (ví dụ 8.5) thì in ra kèm phần thập phân
            else:
                line.final_score_badge_text = f"{rounded_score:.2f}".rstrip("0").rstrip(
                    "."
                )

    def action_open_popup(self):
        self.ensure_one()
        return {
            "name": _("Edit KPI Line"),
            "type": "ir.actions.act_window",
            "res_model": "hr.department.evaluation.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_adecsol_hr_performance_evaluator.view_hr_department_evaluation_line_form_popup"
            ).id,
            "target": "new",
        }
