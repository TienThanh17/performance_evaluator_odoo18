import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class HrKpiScoringFormula(models.Model):
    _name = "hr.kpi.scoring.formula"
    _description = "KPI Scoring Formula"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()
    formula_type = fields.Selection(
        [
            ("linear", "Tuyến tính"),
            ("step_table", "Bảng bậc thang"),
            ("penalty", "Trừ điểm"),
            # ("expression", "Biểu thức tùy chỉnh"),
        ],
        required=True,
        default="linear",
    )

    linear_direction = fields.Selection(
        [
            ("higher_better", "Càng cao càng tốt"),
            ("lower_better", "Càng thấp càng tốt"),
        ],
        default="higher_better",
    )
    linear_allow_exceed = fields.Boolean(
        default=False,
        string="Cho phép vượt điểm tối đa (bonus)",
    )

    step_table_json = fields.Text(default="[]")
    step_out_of_range = fields.Selection(
        [
            ("zero", "Trả về 0 điểm"),
            ("nearest", "Lấy điểm của bậc gần nhất"),
        ],
        default="zero",
        required=True,
        string="Xử lý ngoài bảng",
    )

    penalty_deduct_per_unit = fields.Float(
        default=10.0,
        string="Điểm trừ mỗi đơn vị vi phạm",
    )
    penalty_floor = fields.Float(
        default=0.0,
        string="Điểm tối thiểu",
    )

    expression_code = fields.Char(
        string="Biểu thức",
        help=(
            "Biểu thức Python một dòng. Biến dùng được: actual, target, max_score. "
            "Ví dụ: min(actual / target * max_score, max_score) if target else 0"
        ),
    )

    preview_expression = fields.Char(
        compute="_compute_preview_expression",
        string="Biểu thức tổng hợp",
    )
    kpi_line_count = fields.Integer(
        compute="_compute_kpi_line_count",
        string="KPI đang dùng",
    )
    score_scale_base = fields.Float(
        compute="_compute_score_scale_base",
        string="Score Scale Base",
    )

    @api.depends()
    def _compute_score_scale_base(self):
        score_base = self.get_score_scale_base()
        for rec in self:
            rec.score_scale_base = score_base

    @api.depends(
        "formula_type",
        "linear_direction",
        "linear_allow_exceed",
        "penalty_deduct_per_unit",
        "penalty_floor",
        "expression_code",
    )
    def _compute_preview_expression(self):
        for rec in self:
            scale = "max_score"
            if rec.formula_type == "linear":
                if rec.linear_direction == "higher_better":
                    expr = f"actual / target * {scale}"
                else:
                    expr = f"target / actual * {scale}"
                if not rec.linear_allow_exceed:
                    expr = f"min({expr}, {scale})"
                rec.preview_expression = expr
            elif rec.formula_type == "step_table":
                rec.preview_expression = "lookup(actual, step_table)"
            elif rec.formula_type == "penalty":
                rec.preview_expression = (
                    f"max({scale} - actual * "
                    f"{rec.penalty_deduct_per_unit:g}, {rec.penalty_floor:g})"
                )
            elif rec.formula_type == "expression":
                rec.preview_expression = rec.expression_code or ""
            else:
                rec.preview_expression = ""

    def _compute_kpi_line_count(self):
        employee_lines = self.env["hr.kpi.template.line"].with_context(active_test=False)
        department_lines = self.env["hr.department.kpi.template.line"].with_context(
            active_test=False
        )
        for rec in self:
            rec.kpi_line_count = employee_lines.search_count(
                [("scoring_formula_id", "=", rec.id)]
            ) + department_lines.search_count(
                [("scoring_formula_id", "=", rec.id)]
            )

    @api.constrains("formula_type", "step_table_json")
    def _check_step_table(self):
        for rec in self:
            if rec.formula_type != "step_table":
                continue
            if not rec.step_table_json:
                raise ValidationError(_("Bảng bậc thang không được để trống."))
            try:
                steps = json.loads(rec.step_table_json)
            except (json.JSONDecodeError, TypeError):
                raise ValidationError(_("step_table_json không phải JSON hợp lệ."))
            if not isinstance(steps, list) or not steps:
                raise ValidationError(_("Bảng bậc thang phải có ít nhất 1 bậc."))
            for index, step in enumerate(steps, start=1):
                if not all(key in step for key in ("from", "to", "score")):
                    raise ValidationError(
                        _(
                            "Bậc thang %(index)s thiếu key 'from', 'to' hoặc 'score'."
                        )
                        % {"index": index}
                    )
                lower = step.get("from")
                upper = step.get("to")
                try:
                    lower = float(lower)
                except (TypeError, ValueError):
                    raise ValidationError(
                        _("Bậc thang %(index)s có giá trị 'from' không hợp lệ.")
                        % {"index": index}
                    )
                if upper is not None:
                    try:
                        upper = float(upper)
                    except (TypeError, ValueError):
                        raise ValidationError(
                            _("Bậc thang %(index)s có giá trị 'to' không hợp lệ.")
                            % {"index": index}
                        )
                    if upper <= lower:
                        raise ValidationError(
                            _("Bậc thang %(index)s: 'to' phải lớn hơn 'from'.")
                            % {"index": index}
                        )

    @api.constrains("formula_type", "expression_code")
    def _check_expression(self):
        blocked_words = ["env", "self", "import", "open", "exec", "eval", "__"]
        for rec in self:
            if rec.formula_type != "expression":
                continue
            if not rec.expression_code:
                raise ValidationError(_("Biểu thức không được để trống."))
            expression = rec.expression_code or ""
            for blocked in blocked_words:
                if blocked in expression:
                    raise ValidationError(
                        _("Biểu thức không được chứa '%(blocked)s'.")
                        % {"blocked": blocked}
                    )
            try:
                compile(expression, "<kpi_expr>", "eval")
            except SyntaxError as exc:
                raise ValidationError(
                    _("Cú pháp biểu thức không hợp lệ: %(error)s")
                    % {"error": exc}
                )

    def get_score_scale_base(self):
        return self.env["res.config.settings"].get_score_scale_base()

    def _clamp_score(self, score, max_score, allow_exceed=False):
        score = float(score or 0.0)
        if allow_exceed:
            return round(max(score, 0.0), 4)
        return round(min(max(score, 0.0), max_score), 4)

    def compute_score(self, actual, target, max_score=None):
        self.ensure_one()
        max_score = (
            float(max_score)
            if max_score is not None
            else float(self.get_score_scale_base() or 0.0)
        )
        actual = float(actual or 0.0)
        target = float(target or 0.0)

        if self.formula_type == "linear":
            return self._score_linear(actual, target, max_score)
        if self.formula_type == "step_table":
            return self._score_step_table(actual, max_score)
        if self.formula_type == "penalty":
            return self._score_penalty(actual, max_score)
        if self.formula_type == "expression":
            return self._score_expression(actual, target, max_score)
        return 0.0

    def _score_linear(self, actual, target, max_score):
        self.ensure_one()
        if not target:
            return 0.0
        if self.linear_direction == "higher_better":
            score = (actual / target) * max_score
        else:
            score = (target / actual) * max_score if actual else max_score
        return self._clamp_score(
            score,
            max_score,
            allow_exceed=bool(self.linear_allow_exceed),
        )

    def _score_step_table(self, actual, max_score):
        self.ensure_one()
        try:
            steps = json.loads(self.step_table_json or "[]")
        except Exception:
            return 0.0

        matched = None
        sorted_steps = sorted(steps, key=lambda row: row.get("from", 0))
        for step in sorted_steps:
            low = float(step.get("from", 0.0))
            high = step.get("to")
            if high is None:
                if actual >= low:
                    matched = step
                    break
            else:
                high = float(high)
                if low <= actual <= high:
                    matched = step
                    break

        if matched:
            return self._clamp_score(float(matched.get("score", 0.0)), max_score)

        if self.step_out_of_range == "zero":
            return 0.0
        if not sorted_steps:
            return 0.0

        def midpoint(step):
            low = float(step.get("from", 0.0))
            high = step.get("to")
            high = float(high) if high is not None else low + 1.0
            return (low + high) / 2.0

        nearest = min(sorted_steps, key=lambda row: abs(midpoint(row) - actual))
        return self._clamp_score(float(nearest.get("score", 0.0)), max_score)

    # Tính điểm kiểu penalty luôn bắt đầu từ thang điểm chuẩn runtime rồi trừ theo actual.
    def _score_penalty(self, actual, max_score):
        self.ensure_one()
        deduct_per_unit = float(self.penalty_deduct_per_unit or 0.0)
        floor = float(self.penalty_floor or 0.0)
        score = float(max_score) - (actual * deduct_per_unit)
        return round(max(score, floor), 4)

    def _score_expression(self, actual, target, max_score):
        self.ensure_one()
        local_vars = {
            "actual": actual,
            "target": target,
            "max_score": max_score,
            "min": min,
            "max": max,
            "abs": abs,
            "round": round,
        }
        try:
            result = safe_eval(self.expression_code or "0", local_vars)
            return self._clamp_score(float(result), max_score)
        except Exception as exc:
            _logger.warning(
                "KPI expression '%s' failed: %s | actual=%s target=%s",
                self.expression_code,
                exc,
                actual,
                target,
            )
            return 0.0

    def action_test_formula(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "hr.kpi.scoring.formula.test.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_formula_id": self.id},
        }

    def action_view_kpi_lines(self):
        self.ensure_one()
        employee_count = self.env["hr.kpi.template.line"].search_count(
            [("scoring_formula_id", "=", self.id)]
        )
        department_count = self.env["hr.department.kpi.template.line"].search_count(
            [("scoring_formula_id", "=", self.id)]
        )
        message = _(
            "Employee KPI lines: %(employee)s | Department KPI lines: %(department)s"
        ) % {
            "employee": employee_count,
            "department": department_count,
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.name,
                "message": message,
                "sticky": False,
                "type": "info",
            },
        }
