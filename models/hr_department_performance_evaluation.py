from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

from .kpi_type_utils import NORMALIZED_3P_PILLAR_CODES

_logger = logging.getLogger(__name__)


class HrDepartmentPerformanceEvaluation(models.Model):
    """Department Performance Evaluation.

    This model handles the assessment of department KPIs during a specific evaluation period,
    linking individual employees' performance to the department's overall achievements.
    """

    _name = "hr.department.performance.evaluation"
    _description = "Department Performance Evaluation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_date desc, end_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    department_id = fields.Many2one("hr.department", required=True, tracking=True)
    department_kpi_id = fields.Many2one(
        "hr.department.kpi.template",
        required=True,
        string="Department KPI Template",
        tracking=True,
    )
    pillar_p3_dept_name = fields.Char(compute="_compute_dynamic_pillar_names")

    performance_report_id = fields.Many2one(
        "hr.performance.report",
        ondelete="cascade",
        tracking=True,
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        string="KPI Period",
        compute="_compute_period_id",
        store=True,
        readonly=False,
        tracking=True,
    )
    period_type = fields.Selection(
        related="period_id.period_type",
        string="Period Type",
        store=True,
        readonly=True,
    )
    active = fields.Boolean(string="Active", default=True, tracking=True)

    start_date = fields.Date(required=True, tracking=True)
    end_date = fields.Date(required=True, tracking=True)
    deadline = fields.Date(tracking=True)
    period_status = fields.Selection(
        [
            ("upcoming", "Sắp diễn ra"),
            ("ongoing", "Đang diễn ra"),
            ("closed", "Đã kết thúc"),
        ],
        string="Period Status",
        compute="_compute_period_status",
        store=False,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
    )

    evaluation_line_ids = fields.One2many(
        "hr.department.evaluation.line", "evaluation_id"
    )

    dept_kpi_score = fields.Float(
        compute="_compute_dept_kpi_score",
        store=True,
        help="Điểm KPI phòng ban",
    )

    has_binary_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_rating_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_score_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)
    is_manager = fields.Boolean(
        compute="_compute_role",
        store=False,
    )
    is_hr = fields.Boolean(
        compute="_compute_role",
        store=False,
    )
    is_admin = fields.Boolean(
        compute="_compute_role",
        store=False,
    )
    is_department_manager = fields.Boolean(
        compute="_compute_is_department_manager",
        store=False,
    )

    def _compute_dynamic_pillar_names(self):
        pillars = self.env['hr.evaluation.pillar'].sudo().search([
            ('code', 'in', ['p3_department'])
        ])
        self.pillar_p3_dept_name = pillars.name or ""

    @api.depends("performance_report_id.period_id")
    def _compute_period_id(self):
        for rec in self:
            rec.period_id = rec.performance_report_id.period_id

    # Xác định role của user hiện tại để form phòng ban khóa/mở field theo đúng nghiệp vụ.
    @api.depends_context("uid")
    def _compute_role(self):
        # Kiểm tra group một lần cho toàn bộ batch để tránh lặp truy vấn không cần thiết.
        is_manager = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_manager"
        )
        is_hr = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_hr"
        )
        is_admin = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_admin"
        )

        for rec in self:
            # Gán cờ kỹ thuật cho view dùng trong readonly/invisible expression.
            rec.is_manager = is_manager
            rec.is_hr = is_hr
            rec.is_admin = is_admin

    # Kiểm tra user hiện tại có phải quản lý trực tiếp của phòng ban trên phiếu hay không.
    @api.depends("department_id.manager_id.user_id")
    @api.depends_context("uid")
    def _compute_is_department_manager(self):
        for rec in self:
            # So sánh trực tiếp record user để tránh xử lý thủ công theo id.
            manager_user = rec.department_id.manager_id.user_id
            rec.is_department_manager = bool(
                manager_user and manager_user == self.env.user
            )

    # Detect which manual scoring widgets must stay visible in the department grid.
    @api.depends(
        "evaluation_line_ids.kpi_type",
        "evaluation_line_ids.manual_scoring_type",
    )
    def _compute_kpi_types(self):
        for rec in self:
            manual_lines = rec.evaluation_line_ids.filtered(
                lambda line: line.kpi_type == "manual"
            )
            manual_types = manual_lines.mapped("manual_scoring_type")
            rec.has_binary_kpi = "binary" in manual_types
            rec.has_rating_kpi = "rating" in manual_types
            rec.has_score_kpi = "score" in manual_types

    @api.depends("start_date", "end_date")
    def _compute_period_status(self):
        for rec in self:
            if not rec.start_date or not rec.end_date:
                rec.period_status = False
                continue
            today = fields.Date.context_today(rec)
            if today < rec.start_date:
                rec.period_status = "upcoming"
            elif today > rec.end_date:
                rec.period_status = "closed"
            else:
                rec.period_status = "ongoing"

    @api.depends("department_id", "start_date", "end_date")
    def _compute_name(self):
        for rec in self:
            if rec.department_id and rec.start_date and rec.end_date:
                rec.name = (
                    f"KPI-{rec.department_id.name} ({rec.start_date} to {rec.end_date})"
                )
            else:
                rec.name = "New Dept KPI"

    @api.depends(
        "evaluation_line_ids.final_score",
        "evaluation_line_ids.weight",
        "evaluation_line_ids.parent_line_id",
    )
    def _compute_dept_kpi_score(self):
        for rec in self:
            rec.dept_kpi_score = rec._compute_weighted_score_from_lines(
                rec._get_top_level_scorable_lines()
            )

    # Return the root scoring nodes used by normalized 3P and legacy KPI trees.
    def _get_top_level_scorable_lines(self, pillar_code=None):
        self.ensure_one()
        lines = self.evaluation_line_ids.filtered(
            lambda line: (
                not line.parent_line_id
                and (
                    line.pillar_code in NORMALIZED_3P_PILLAR_CODES
                    or not line.is_section
                )
            )
        )
        if pillar_code:
            lines = lines.filtered(lambda line: line.pillar_code == pillar_code)
        return lines

    def _compute_weighted_score_from_lines(self, lines):
        self.ensure_one()
        if not lines:
            return 0.0
        total_weight = sum(lines.mapped("weight"))
        if total_weight > 0:
            return sum(line.final_score * line.weight for line in lines) / total_weight
        return sum(lines.mapped("final_score")) / len(lines)

    # Trả về thang điểm chuẩn duy nhất của phiếu KPI phòng ban.
    def _get_evaluation_score_base(self):
        self.ensure_one()
        return self.env["res.config.settings"].get_score_scale_base()

    # Đồng bộ weight section và chỉ giữ lại validate weight âm cho evaluation line.
    def _refresh_evaluation_line_weight_structure(self):
        line_records = self.mapped("evaluation_line_ids")
        if line_records:
            line_records._refresh_weight_structure()

    def action_compute_auto_kpi(self):
        engine = self.env["hr.kpi.engine"]
        for evaluation in self:
            if evaluation.state in ["cancel", "approved"]:
                continue
            if not evaluation.department_id or not evaluation.department_kpi_id:
                continue
            for line in evaluation.evaluation_line_ids:
                if not line.is_auto or line.child_line_ids:
                    continue
                actual = engine.with_context(
                    department_evaluation_line=line.id
                ).compute_for_department(
                    evaluation.department_id,
                    line,
                    evaluation.start_date,
                    evaluation.end_date,
                )
                line.actual = actual

    def _cron_compute_auto_kpi(self):
        """Cron wrapper: tính toán KPI tự động cho tất cả department evaluation
        đang trong kỳ hiện tại (ongoing) và chưa ở trạng thái approved/cancel.
        Chạy mỗi tối qua ir.cron.
        """
        today = fields.Date.context_today(self)
        evaluations = self.search(
            [
                ("state", "not in", ["approved", "cancel"]),
                ("start_date", "<=", today),
                ("end_date", ">=", today),
            ]
        )
        if evaluations:
            evaluations.with_context(
                skip_line_chatter_audit=True
            ).action_compute_auto_kpi()

    def action_submit(self):
        self.write({"state": "submitted"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_open_department_dashboard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "name": _("KPI Department Dashboard"),
            "tag": "kpi_department_dashboard",
            "context": {
                "default_department_id": self.department_id.id,
                "default_evaluation_id": self.id,
            },
        }

    def _sync_active_to_report_batch(self, active):
        """Đồng bộ trạng thái lưu trữ sang report batch và phiếu KPI cá nhân."""
        for evaluation in self.with_context(active_test=False):
            report = evaluation.performance_report_id.with_context(active_test=False)
            if not report:
                continue
            # Tránh report.write() sync ngược lại department evaluations lần nữa.
            report.with_context(skip_department_active_sync=True).write(
                {"active": active}
            )
            report.evaluation_ids.with_context(active_test=False).write(
                {"active": active}
            )

    def write(self, vals):
        if "evaluation_line_ids" in vals and not self.env.context.get(
            "skip_normalized_3p_weight_validation"
        ):
            res = super(
                HrDepartmentPerformanceEvaluation,
                self.with_context(skip_normalized_3p_weight_validation=True),
            ).write(vals)
            self._rebuild_line_hierarchy_from_template()
            self._refresh_evaluation_line_weight_structure()
            self._recompute_line_scores_after_hierarchy_rebuild()
        else:
            res = super().write(vals)
        if "active" in vals and not self.env.context.get("skip_report_active_sync"):
            # boolean_toggle trên list view chỉ gọi write(active), nên sync phải nằm ở đây.
            self._sync_active_to_report_batch(vals["active"])
        return res

    def unlink(self):
        reports = self.mapped("performance_report_id")
        res = super().unlink()
        if reports:
            reports.unlink()
        return res

    def _set_active_with_report(self, active):
        """Archive/unarchive department KPI and the linked report batch together.

        Báo cáo batch là nơi quản lý các phiếu KPI cá nhân trong cùng kỳ. Vì vậy
        khi archive/unarchive phiếu KPI phòng ban từ màn hình này, report và các
        phiếu cá nhân bên trong report cũng phải đi theo để UI không lệch trạng thái.
        """
        self.with_context(active_test=False).write({"active": active})

    def action_archive_with_report(self):
        self._set_active_with_report(False)
        return True

    def action_unarchive_with_report(self):
        self._set_active_with_report(True)
        return True

    # ── Public interface for Phase 3 (hr.performance.evaluation) ─────────────
    def get_dept_kpi_score(self):
        """
        Return the current dept_kpi_score regardless of approval state.
        Called by hr.performance.evaluation when reading linked department KPI data.

        Business rules:
        - draft / submitted : return current dept_kpi_score (provisional value).
        - approved          : return dept_kpi_score (official value).
        - cancel            : return 0.0 (evaluation is void — do not use).

        Returns: float
        """
        self.ensure_one()
        if self.state == "cancel":
            return 0.0
        return self.dept_kpi_score or 0.0

    @api.onchange("department_kpi_id")
    def _onchange_kpi_id(self):
        # if not self.kpi_id:
        #     return
        #
        #     # GUARD: Chỉ rebuild khi kpi_id thực sự được user thay đổi.
        #     # _origin.kpi_id là giá trị đang lưu trong DB.
        #     # Nếu bằng nhau → onchange đang fire spuriously (lúc save/reload) → bỏ qua.
        # if self._origin.kpi_id and self._origin.kpi_id.id == self.kpi_id.id:
        #     return

        if self.department_kpi_id:
            self.evaluation_line_ids = (
                self._prepare_evaluation_line_commands_from_template(
                    self.department_kpi_id
                )
            )

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _prepare_evaluation_line_commands_from_template(self, kpi):
        """Build one2many commands for evaluation_line_ids from KPI template lines.

        - Preserves hierarchy preorder from the template tree.
        - Preserves section/note lines.
        """
        self.ensure_one()
        if not kpi:
            return []

        # Lấy template lines theo preorder đã chuẩn hoá để evaluation tree giữ nguyên hình dạng.
        template_lines = kpi.get_hierarchy_ordered_lines()

        # Sử dụng : list[tuple] để Type Checker không hiểu lầm là danh sách chỉ chứa tuple 3 số nguyên.
        # fields.Command.clear() tương đương với lệnh (5, 0, 0) để xóa sạch các dòng cũ trước khi thêm mới.
        commands: list[tuple] = [fields.Command.clear()]
        score_unit = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.kpi_unit_score",
            raise_if_not_found=False,
        )
        score_base = self.env["res.config.settings"].get_score_scale_base()
        for line in template_lines:
            # Kiểm tra nếu dòng hiện tại là một Section (tiêu đề nhóm) dựa trên thuộc tính.
            is_section = bool(getattr(line, "is_section", False))
            if is_section:
                # fields.Command.create({...}) tương đương với lệnh (0, 0, {...}) để tạo mới một dòng.
                commands.append(
                    fields.Command.create(
                        {
                            "department_kpi_line_id": line.id,
                            "parent_template_line_id": line.parent_line_id.id,
                            "sequence": line.sequence,
                            "is_section": True,
                            "name": line.name,
                            "pillar_id": line.pillar_id.id,
                            "description": getattr(line, "description", False),
                            # Safe defaults for required KPI fields on section rows
                            "kpi_type": "auto",
                            "manual_scoring_type": False,
                            "target": 0.0,
                            "unit": False,
                            "weight": line.weight,
                            "wipeout_if_child_zero": bool(
                                line.wipeout_if_child_zero
                            ),
                            "dept_source_type": "manual",
                            "data_source_id": False,
                            "scoring_formula_id": False,
                            "is_auto": False,
                        }
                    )
                )
                continue

            commands.append(
                fields.Command.create(
                    {
                        "department_kpi_line_id": line.id,
                        "parent_template_line_id": line.parent_line_id.id,
                        "sequence": line.sequence,
                        "name": line.name,
                        "pillar_id": line.pillar_id.id,
                        "description": getattr(line, "description", False),
                        "kpi_type": line.kpi_type,
                        "manual_scoring_type": line.manual_scoring_type,
                        "target": line.target,
                        "unit": line.unit.id or False,
                        "weight": line.weight,
                        "wipeout_if_child_zero": bool(line.wipeout_if_child_zero),
                        "dept_source_type": line.dept_source_type or "manual",
                        "data_source_id": line.data_source_id.id or False,
                        "scoring_formula_id": line.scoring_formula_id.id or False,
                        "is_auto": bool(line.is_auto),
                    }
                )
            )
        return commands

    def _rebuild_line_hierarchy_from_template(self):
        for evaluation in self:
            line_by_template = {
                line.department_kpi_line_id.id: line
                for line in evaluation.evaluation_line_ids
                if line.department_kpi_line_id
            }
            for line in evaluation.evaluation_line_ids:
                parent_line = (
                    line_by_template.get(line.parent_template_line_id.id)
                    if line.parent_template_line_id
                    else False
                )
                if line.parent_line_id != parent_line:
                    line.with_context(
                        skip_line_chatter_audit=True,
                        skip_score_tree_recompute=True,
                    ).write(
                        {"parent_line_id": parent_line.id if parent_line else False}
                    )

    # Tính lại toàn bộ cây KPI từ lá lên gốc sau khi rebuild hierarchy để section có điểm ngay.
    def _recompute_line_scores_after_hierarchy_rebuild(self):
        for evaluation in self:
            if evaluation.evaluation_line_ids:
                evaluation.evaluation_line_ids._recompute_score_tree()
                continue
            evaluation._compute_dept_kpi_score()

    @api.model_create_multi
    def create(self, vals_list):
        records = super(
            HrDepartmentPerformanceEvaluation,
            self.with_context(skip_normalized_3p_weight_validation=True),
        ).create(vals_list)
        records._rebuild_line_hierarchy_from_template()
        records._refresh_evaluation_line_weight_structure()
        records._recompute_line_scores_after_hierarchy_rebuild()
        return records

    def get_dashboard_data(self):
        # Dựng toàn bộ payload dashboard phòng ban từ chính phiếu KPI phòng ban,
        # không phụ thuộc vào helper của hr.performance.report nữa.
        self.ensure_one()
        chart_service = self.env["hr.kpi.dashboard.chart.service"]

        employees = (
            self.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("department_id", "=", self.department_id.id),
                    ("active", "=", True),
                ],
                order="name asc",
            )
        )

        user_ids = employees.mapped("user_id").ids
        Task = self.env["project.task"].sudo()
        period_tasks = (
            Task.search(
                [
                    ("user_ids", "in", user_ids),
                    # ('date_deadline', '>=', self.start_date),
                    # ('date_deadline', '<=', self.end_date),
                    ("project_id", "!=", False),
                ]
            )
            if user_ids
            else Task.browse()
        )

        # Lấy ID các dự án liên quan
        project_ids = period_tasks.mapped("project_id").ids
        # Tự build payload roster/report charts ngay trên model phòng ban.
        report_dashboard = self._build_report_dashboard_payload()
        report_dashboard = self._enrich_report_dashboard_with_3p_summary_snapshot(
            report_dashboard
        )

        period_label = (
            self.period_id.name
            if self.period_id
            else (str(self.start_date) if self.start_date else "")
        )
        quantitative_table = self._get_quantitative_table_data()
        macro_sections = []

        result = {
            "department_name": self.department_id.name or "",
            "period_id": self.period_id.id if self.period_id else False,
            "period_name": self.period_id.name if self.period_id else "",
            "period_type": self.period_type or "",
            "score_scale": {
                **self.env["res.config.settings"].get_score_scale_info(),
                "base": self._get_evaluation_score_base(),
                "suffix": f" / {int(self._get_evaluation_score_base())}",
            },
            "dynamic_charts": chart_service.build_dynamic_charts(
                self, dashboard_kind="department"
            ),
            "macro_sections": macro_sections,
            "report_dashboard": report_dashboard,
            # "manager_name": (
            #     self.department_id.manager_id.name
            #     if self.department_id.manager_id
            #     else "—"
            # ),
            "project_count": len(project_ids),
            "employee_count": len(employees),
            "dept_kpi_score": round(float(self.dept_kpi_score or 0.0), 2),
            # "department_score": round(float(self.department_score or 0.0), 2),
            # "department_level": self.department_level or "fail",
            "employees": [{"id": e.id, "name": e.name} for e in employees],
            "task_summary_by_employee": self._dashboard_task_summary_by_employee(),
            "project_progress": self._dashboard_project_progress(),
            "attendance_count": self._dashboard_attendance_count(),
            "bug_count_by_employee": self._dashboard_bug_count_by_employee(),
            "score_trend": self._dashboard_score_trend(),
            "quantitative_table": quantitative_table,
        }
        return result

    # Dựng 1 chart item theo đúng contract frontend của report dashboard.
    def _build_report_chart_item(
        self,
        key,
        sequence,
        measure_field,
        default_title,
        badge,
        badge_tone,
        dot_tone,
    ):
        return {
            "section_type": "chart_item",
            "widget_id": 0,
            "key": key,
            "sequence": sequence,
            "measure_field": measure_field,
            "title": default_title,
            "badge": badge,
            "badge_tone": badge_tone,
            "dot_tone": dot_tone,
        }

    # Gom nhiều chart item thành một hàng hiển thị trong report dashboard.
    def _build_report_chart_row(self, items, layout):
        # Loại bỏ các item rỗng để frontend không phải tự phòng thủ thêm.
        active_items = [item for item in items if item]
        if not active_items:
            return False
        return {
            "section_type": "chart_row",
            "layout": layout,
            "sequence": min(item["sequence"] for item in active_items),
            "key": "report_row_%s" % "_".join(item["key"] for item in active_items),
            "items": active_items,
        }

    # Build cấu trúc section mà OWL dashboard phòng ban đang render lại.
    def _build_report_sections(self, context_data):
        sections = []

        # Dựng hàng biểu đồ đầu tiên: điểm KPI cá nhân và task summary.
        sections_row_top = self._build_report_chart_row(
            [
                self._build_report_chart_item(
                    "report_score_bar",
                    120,
                    "report_score_bar",
                    _("Individual KPI Score by Employee"),
                    "Bar",
                    "blue",
                    "blue",
                ),
                self._build_report_chart_item(
                    "report_task_summary",
                    130,
                    "report_task_summary",
                    _("Completed Tasks by Employee"),
                    _("Stacked Bar"),
                    "green",
                    "green",
                ),
            ],
            "2col",
        )
        if sections_row_top:
            sections.append(sections_row_top)

        # Dựng hàng biểu đồ thứ hai: attendance và late count.
        sections_row_bottom = self._build_report_chart_row(
            [
                self._build_report_chart_item(
                    "report_attendance",
                    140,
                    "report_attendance",
                    _("Attendance — Days Present"),
                    "Doughnut",
                    "blue",
                    "blue",
                ),
                self._build_report_chart_item(
                    "report_late_summary",
                    150,
                    "report_late_summary",
                    _("Punctuality — Late Count by Employee"),
                    "Line",
                    "red",
                    "red",
                ),
            ],
            "13col",
        )
        if sections_row_bottom:
            sections.append(sections_row_bottom)

        # Giữ nguyên section KPI định tính để frontend không cần đổi template.
        if context_data["qualitative_charts"]:
            sections.append(
                {
                    "section_type": "qualitative_grid",
                    "widget_id": 0,
                    "key": "report_qualitative",
                    "sequence": 160,
                    "measure_field": "report_qualitative",
                    "title": _("Qualitative KPIs — Employee Comparison"),
                    "charts": context_data["qualitative_charts"],
                }
            )

        return sorted(
            sections,
            key=lambda section: (
                section.get("sequence", 0),
                section.get("widget_id", 0),
                section.get("key", ""),
            ),
        )

    # Lấy tập phiếu KPI cá nhân dùng cho report dashboard của phòng ban.
    def _get_report_dashboard_evaluations(self):
        self.ensure_one()
        Evaluation = self.env["hr.performance.evaluation"].sudo().with_context(
            active_test=False
        )
        domain = [
            ("department_id", "=", self.department_id.id),
            ("start_date", "=", self.start_date),
            ("end_date", "=", self.end_date),
            ("state", "!=", "cancel"),
        ]

        # Nếu có performance report thì thêm điều kiện để payload bám đúng batch hiện có.
        if self.performance_report_id:
            domain.append(
                ("performance_report_id", "=", self.performance_report_id.id)
            )

        evaluations = Evaluation.search(domain, order="employee_id asc, id asc")

        # Ưu tiên các phiếu đã link trực tiếp vào dept_evaluation hiện tại.
        linked_evaluations = evaluations.filtered(
            lambda evaluation: evaluation.dept_evaluation_id == self
        )
        if linked_evaluations:
            # Bổ sung thêm các phiếu chưa được backfill dept_evaluation_id để dashboard
            # cũ không bị thiếu người khi dữ liệu lịch sử chưa được chuẩn hóa hết.
            fallback_evaluations = evaluations.filtered(
                lambda evaluation: not evaluation.dept_evaluation_id
            )
            return (linked_evaluations | fallback_evaluations).sorted(
                key=lambda evaluation: (
                    evaluation.employee_id.name or "",
                    evaluation.id,
                )
            )

        return evaluations

    # Chuẩn hóa danh sách nhân viên và roster rows cho report dashboard.
    def _get_report_dashboard_employee_rows(self, evaluations):
        self.ensure_one()
        employees = []
        evaluation_rows = []

        for evaluation in evaluations:
            # Build payload gọn cho biểu đồ điểm KPI cá nhân.
            employees.append(
                {
                    "id": evaluation.employee_id.id if evaluation.employee_id else 0,
                    "name": evaluation.employee_id.name if evaluation.employee_id else "?",
                    "score": round(float(evaluation.total_p3_individual or 0.0), 2),
                    "level": evaluation.performance_level or "fail",
                    "eval_id": evaluation.id,
                }
            )

            # Giữ nguyên schema roster row để frontend hiện tại không cần đổi.
            evaluation_rows.append(
                {
                    "id": evaluation.id,
                    "employee_id": (
                        [evaluation.employee_id.id, evaluation.employee_id.name]
                        if evaluation.employee_id
                        else False
                    ),
                    "job_id": (
                        [evaluation.job_id.id, evaluation.job_id.name]
                        if evaluation.job_id
                        else False
                    ),
                    "total_p3_individual": round(
                        float(evaluation.total_p3_individual or 0.0),
                        2,
                    ),
                    "performance_level": evaluation.performance_level or False,
                    "state": evaluation.state or False,
                    "name": evaluation.name or "",
                    "comment_count": evaluation.get_comment_count(),
                }
            )

        return employees, evaluation_rows

    # Tổng hợp số task completed/pending theo từng nhân viên trong roster.
    def _get_report_dashboard_task_summary(self, evaluations, employee_names):
        self.ensure_one()
        task_summary = {
            "names": employee_names,
            "total_tasks": [],
            "done_tasks": [],
        }
        Task = self.env["project.task"].sudo()

        for evaluation in evaluations:
            # Chỉ dùng KPI auto thực sự có dòng dữ liệu để suy ra task metrics.
            auto_lines = evaluation.evaluation_line_ids.filtered(
                lambda line: not line.is_section and line.kpi_type == "auto"
            )
            if (
                not auto_lines
                or not evaluation.employee_id
                or not evaluation.start_date
                or not evaluation.end_date
            ):
                task_summary["total_tasks"].append(0)
                task_summary["done_tasks"].append(0)
                continue

            # Không có user nội bộ thì không thể map sang project.task.
            user = evaluation.employee_id.user_id
            if not user:
                task_summary["total_tasks"].append(0)
                task_summary["done_tasks"].append(0)
                continue

            # Đếm task theo cùng rule cũ để giữ số liệu nhất quán với dashboard legacy.
            base_domain = [
                ("user_ids", "in", user.id),
                ("date_deadline", ">=", evaluation.start_date),
                ("date_deadline", "<=", evaluation.end_date),
                ("project_id", "!=", False),
            ]
            total_tasks = Task.search_count(base_domain)
            done_tasks = Task.search_count(
                base_domain + [("stage_id.is_done_stage", "=", True)]
            )
            task_summary["total_tasks"].append(total_tasks)
            task_summary["done_tasks"].append(done_tasks)

        return task_summary

    # Tổng hợp attendance theo từng nhân viên trong roster.
    def _get_report_dashboard_attendance_summary(self, evaluations, employee_names):
        self.ensure_one()
        attendance_summary = {
            "names": employee_names,
            "worked_days": [],
            "expected_work_days": 0,
        }
        engine = self.env["hr.kpi.engine"]

        for evaluation in evaluations:
            # Attendance chỉ có ý nghĩa khi phiếu có KPI auto và đủ mốc kỳ đánh giá.
            auto_lines = evaluation.evaluation_line_ids.filtered(
                lambda line: not line.is_section and line.kpi_type == "auto"
            )
            if not auto_lines or not evaluation.start_date or not evaluation.end_date:
                attendance_summary["worked_days"].append(0)
                continue

            # Lấy metrics attendance cùng rule đang dùng ở report dashboard cũ.
            metrics = engine.get_attendance_period_metrics(
                evaluation.employee_id,
                auto_lines[0],
                evaluation.start_date,
                evaluation.end_date,
            )
            metrics = metrics or {}
            attendance_summary["worked_days"].append(
                float(metrics.get("worked_days", 0))
            )

            # Mọi nhân viên trong cùng kỳ dùng chung expected_work_days nên chỉ cần
            # ghi nhận một lần đầu tiên có dữ liệu.
            if not attendance_summary["expected_work_days"]:
                attendance_summary["expected_work_days"] = float(
                    metrics.get("expected_work_days", 0)
                )

        return attendance_summary

    # Tổng hợp số lần đi trễ theo từng nhân viên trong roster.
    def _get_report_dashboard_late_summary(self, evaluations, employee_names):
        self.ensure_one()
        late_summary = {"names": employee_names, "late_count": []}
        engine = self.env["hr.kpi.engine"]

        for evaluation in evaluations:
            # Late count dùng cùng KPI auto context với dashboard legacy.
            auto_lines = evaluation.evaluation_line_ids.filtered(
                lambda line: not line.is_section and line.kpi_type == "auto"
            )
            if not auto_lines or not evaluation.start_date or not evaluation.end_date:
                late_summary["late_count"].append(0)
                continue

            # Tính số lần đi trễ theo khoảng kỳ của từng nhân viên.
            late_value = engine.compute(
                evaluation.employee_id,
                auto_lines[0],
                evaluation.start_date,
                evaluation.end_date,
            )
            late_summary["late_count"].append(int(late_value or 0))

        return late_summary

    # Dựng danh sách chart KPI định tính theo nhóm KPI name/khu vực hiệu suất.
    def _get_report_dashboard_qualitative_charts(self, evaluations):
        self.ensure_one()
        qualitative_map = {}

        for evaluation in evaluations:
            # Gom tất cả KPI manual theo tên KPI để dashboard so sánh giữa nhân viên.
            employee_name = evaluation.employee_id.name if evaluation.employee_id else "?"
            rating_lines = evaluation.evaluation_line_ids.filtered(
                lambda line: not line.is_section and line.kpi_type == "manual"
            )
            for line in rating_lines:
                kpi_name = line.key_performance_area or line.name or "KPI"
                if kpi_name not in qualitative_map:
                    qualitative_map[kpi_name] = {}
                qualitative_map[kpi_name][employee_name] = round(
                    float(line.final_rating or 0.0),
                    2,
                )

        qualitative_charts = []
        for kpi_name, employee_scores in qualitative_map.items():
            qualitative_charts.append(
                {
                    "kpi_name": kpi_name,
                    "labels": list(employee_scores.keys()),
                    "scores": list(employee_scores.values()),
                }
            )

        return qualitative_charts

    # Tự build payload report dashboard ngay trên model phòng ban.
    def _build_report_dashboard_payload(self):
        self.ensure_one()
        settings = self.env["res.config.settings"]
        score_scale = settings.get_score_scale_info()
        threshold_excellent, threshold_pass = settings.get_thresholds()
        evaluations = self._get_report_dashboard_evaluations()
        employees, evaluation_rows = self._get_report_dashboard_employee_rows(
            evaluations
        )
        employee_names = [employee["name"] for employee in employees]
        total_employees = len(evaluations)
        avg_score = (
            round(
                sum(
                    float(evaluation.total_p3_individual or 0.0)
                    for evaluation in evaluations
                )
                / total_employees,
                2,
            )
            if total_employees
            else 0.0
        )

        # Đếm số nhân viên đạt pass/excellent theo cùng rule cũ.
        pass_count = sum(
            1
            for evaluation in evaluations
            if evaluation.performance_level in ("pass", "excellent")
        )

        # Dựng các khối dữ liệu chart/roster mà frontend đang tiêu thụ.
        task_summary = self._get_report_dashboard_task_summary(
            evaluations,
            employee_names,
        )
        attendance_summary = self._get_report_dashboard_attendance_summary(
            evaluations,
            employee_names,
        )
        late_summary = self._get_report_dashboard_late_summary(
            evaluations,
            employee_names,
        )
        qualitative_charts = self._get_report_dashboard_qualitative_charts(
            evaluations
        )
        report_sections = self._build_report_sections(
            {
                "avg_score": avg_score,
                "pass_count": pass_count,
                "total_employees": total_employees,
                "period_label": self.period_id.name if self.period_id else "",
                "evaluations": evaluation_rows,
                "qualitative_charts": qualitative_charts,
            }
        )

        return {
            "report_id": self.performance_report_id.id if self.performance_report_id else False,
            "department_id": self.department_id.id if self.department_id else False,
            "department_name": self.department_id.name or "",
            "period_id": self.period_id.id if self.period_id else False,
            "period_name": self.period_id.name if self.period_id else "",
            "period_type": self.period_type or "",
            "start_date": str(self.start_date) if self.start_date else False,
            "end_date": str(self.end_date) if self.end_date else False,
            "deadline": str(self.deadline) if self.deadline else False,
            "active": bool(self.active),
            "score_scale": score_scale,
            "thresholds": {
                "excellent": threshold_excellent,
                "pass": threshold_pass,
            },
            "total_employees": total_employees,
            "avg_score": avg_score,
            "pass_count": pass_count,
            "employees": employees,
            "evaluations": evaluation_rows,
            "task_summary": task_summary,
            "attendance_summary": attendance_summary,
            "late_summary": late_summary,
            "qualitative_charts": qualitative_charts,
            "report_sections": report_sections,
        }

    # Bơm thêm các cột snapshot 3P vào Team Roster payload của dashboard phòng ban.
    def _enrich_report_dashboard_with_3p_summary_snapshot(self, report_dashboard):
        self.ensure_one()

        # Nếu chưa có report payload hoặc chưa có roster evaluations thì không cần
        # làm gì thêm.
        if not report_dashboard or not report_dashboard.get("evaluations"):
            return report_dashboard

        Summary = self.env["hr.evaluation.3p.summary"].sudo()
        summary_line_map = {}

        # Tìm bản summary mới nhất đang neo trực tiếp vào phiếu KPI phòng ban này
        # để roster hiển thị đúng snapshot aggregate của cùng kỳ.
        if self.id:
            latest_summary = Summary.search(
                [("department_evaluation_id", "=", self.id)],
                order="id desc",
                limit=1,
            )
            if latest_summary:
                # Dùng evaluation_id làm khóa để map từng dòng roster với snapshot
                # line tương ứng. Chỉ lấy các line thật sự gắn với evaluation.
                summary_line_map = {
                    line.evaluation_id.id: line
                    for line in latest_summary.line_ids.filtered("evaluation_id")
                }

        normalized_dashboard = dict(report_dashboard)
        normalized_rows = []

        for row in report_dashboard.get("evaluations", []):
            normalized_row = dict(row)
            summary_line = summary_line_map.get(normalized_row.get("id"))

            # Nếu thiếu snapshot line thì để False để frontend render dấu "—"
            # thay vì âm thầm rơi về live score.
            normalized_row.update(
                {
                    "p2_1_score_raw": (
                        round(float(summary_line.p2_1_score_raw or 0.0), 2)
                        if summary_line
                        else False
                    ),
                    "p2_2_score_raw": (
                        round(float(summary_line.p2_2_score_raw or 0.0), 2)
                        if summary_line
                        else False
                    ),
                    "p3_individual_score": (
                        round(float(summary_line.p3_individual_score or 0.0), 2)
                        if summary_line
                        else False
                    ),
                    "p3_department_score": (
                        round(float(summary_line.p3_department_score or 0.0), 2)
                        if summary_line
                        else False
                    ),
                    "p3_1_score": (
                        round(float(summary_line.p3_1_score or 0.0), 2)
                        if summary_line
                        else False
                    ),
                }
            )
            normalized_rows.append(normalized_row)

        normalized_dashboard["evaluations"] = normalized_rows
        return normalized_dashboard

    # Chuẩn bị dữ liệu bảng KPI định lượng của phòng ban theo cùng cấu trúc với dashboard cá nhân.
    def _get_quantitative_table_data(self):
        self.ensure_one()
        # Chỉ lấy các KPI auto thực sự là dòng dữ liệu để hiển thị trong bảng chi tiết.
        lines = self.evaluation_line_ids.filtered(
            lambda l: not l.is_section and l.kpi_type == "auto"
        )
        rows = []
        for line in lines:
            # Chuẩn hóa giá trị gốc trước khi format để các chỉ số trong bảng dùng chung một nguồn dữ liệu.
            target = float(line.target or 0.0)
            actual = float(line.actual or 0.0)
            final = float(line.final_score or 0.0)
            unit_text = line.unit.name if line.unit else ""
            # Giữ target/actual ở dạng số gọn để frontend render theo cùng quy ước của dashboard cá nhân.
            target_text = f"{target:g}"
            actual_text = f"{actual:g}"
            rows.append(
                {
                    "name": line.name or "",
                    "unit_measure": unit_text,
                    "target": target_text,
                    "actual": actual_text,
                    "final_score": round(final, 2),
                }
            )
        return rows

    def _dashboard_task_summary_by_employee(self):
        """
        Trả về task summary (total/done/pending) theo từng nhân viên
        trong cùng phòng ban, cùng kỳ đánh giá.

        Returns:
            list[dict]: [
                {
                    'employee_id': int,
                    'name': str,
                    'total': int,
                    'done': int,
                    'pending': int,
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        # Lấy tất cả nhân viên trong phòng ban
        employees = (
            self.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("department_id", "=", self.department_id.id),
                    ("active", "=", True),
                ]
            )
        )
        if not employees:
            return []

        user_ids = employees.mapped("user_id").ids
        if not user_ids:
            return []

        Task = self.env["project.task"].sudo()

        # Query tất cả tasks trong kỳ một lần (tránh N+1 queries)
        all_tasks = Task.search(
            [
                ("user_ids", "in", user_ids),
                ("date_deadline", ">=", self.start_date),
                ("date_deadline", "<=", self.end_date),
                ("project_id", "!=", False),
            ]
        )

        # Group tasks by user_id
        # Một task có thể assign nhiều user → đếm cho từng user
        tasks_by_user = {}
        for task in all_tasks:
            for user in task.user_ids:
                if user.id not in tasks_by_user:
                    tasks_by_user[user.id] = {"total": [], "done": []}
                tasks_by_user[user.id]["total"].append(task)
                if task.stage_id and task.stage_id.is_done_stage:
                    tasks_by_user[user.id]["done"].append(task)

        result = []
        for emp in employees:
            if not emp.user_id:
                continue
            uid = emp.user_id.id
            bucket = tasks_by_user.get(uid, {"total": [], "done": []})
            total = len(bucket["total"])
            done = len(bucket["done"])
            result.append(
                {
                    "employee_id": emp.id,
                    "name": emp.name,
                    "total": total,
                    "done": done,
                    "pending": total - done,
                }
            )

        # Sắp xếp theo tên
        result.sort(key=lambda x: x["name"])
        return result

    def _dashboard_project_progress(self):
        """
        Tính % tiến độ các dự án mà nhân viên trong phòng ban tham gia,
        trong kỳ đánh giá (dựa trên date_deadline của task).

        Returns:
            list[dict]: [
                {
                    'project_id': int,
                    'name': str,
                    'total_tasks': int,
                    'done_tasks': int,
                    'progress_pct': float,  # 0.0 - 100.0
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        # Lấy user_ids của nhân viên trong phòng ban
        employees = (
            self.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("department_id", "=", self.department_id.id),
                    ("active", "=", True),
                ]
            )
        )
        user_ids = employees.mapped("user_id").ids
        if not user_ids:
            return []

        # Lấy tất cả tasks trong kỳ có assign nhân viên phòng ban
        Task = self.env["project.task"].sudo()
        all_tasks = Task.search(
            [
                ("user_ids", "in", user_ids),
                # ('date_deadline', '>=', self.start_date),
                # ('date_deadline', '<=', self.end_date),
                ("project_id", "!=", False),
            ]
        )
        if not all_tasks:
            return []

        # # Lấy các dự án mà phòng ban có tham gia trong kỳ này  (gemini solution)
        # Task = self.env["project.task"].sudo()
        # period_tasks = Task.search([
        #     ('user_ids', 'in', user_ids),
        #     ('date_deadline', '>=', self.start_date),
        #     ('date_deadline', '<=', self.end_date),
        #     ('project_id', '!=', False),
        # ])
        #
        # if not period_tasks:
        #     return []
        #
        # # Lấy ID các dự án liên quan
        # project_ids = period_tasks.mapped('project_id').ids
        #
        # # Truy vấn TẤT CẢ tasks của các dự án này (không giới hạn thời gian)
        # all_tasks = Task.search([
        #     ('project_id', 'in', project_ids)
        #     # Bỏ bộ lọc date_deadline đi
        # ])

        # Group theo project
        tasks_by_project = {}
        for task in all_tasks:
            pid = task.project_id.id
            pname = task.project_id.name
            if pid not in tasks_by_project:
                tasks_by_project[pid] = {"name": pname, "total": 0, "done": 0}
            tasks_by_project[pid]["total"] += 1
            if task.stage_id and task.stage_id.is_done_stage:
                tasks_by_project[pid]["done"] += 1

        result = []
        for pid, info in tasks_by_project.items():
            total = info["total"]
            done = info["done"]
            result.append(
                {
                    "project_id": pid,
                    "name": info["name"],
                    "total_tasks": total,
                    "done_tasks": done,
                    "progress_pct": round(done / total * 100, 1) if total > 0 else 0.0,
                }
            )

        # Sắp xếp theo % giảm dần
        result.sort(key=lambda x: x["progress_pct"], reverse=True)
        return result

    def _dashboard_attendance_count(self):
        """
        Đếm số lần chấm công (số attendance record) theo từng nhân viên
        trong kỳ đánh giá.

        Returns:
            list[dict]: [
                {
                    'employee_id': int,
                    'name': str,
                    'attendance_count': int,
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        employees = (
            self.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("department_id", "=", self.department_id.id),
                    ("active", "=", True),
                ],
                order="name asc",
            )
        )
        if not employees:
            return []

        # Query tất cả attendance trong kỳ, 1 lần duy nhất
        attendances = (
            self.env["hr.attendance"]
            .sudo()
            .search(
                [
                    ("employee_id", "in", employees.ids),
                    ("check_in", ">=", str(self.start_date) + " 00:00:00"),
                    ("check_in", "<=", str(self.end_date) + " 23:59:59"),
                ]
            )
        )

        # Group by employee_id
        count_by_emp = {}
        for att in attendances:
            eid = att.employee_id.id
            count_by_emp[eid] = count_by_emp.get(eid, 0) + 1

        result = []
        for emp in employees:
            result.append(
                {
                    "employee_id": emp.id,
                    "name": emp.name,
                    "attendance_count": count_by_emp.get(emp.id, 0),
                }
            )

        return result

    def _dashboard_bug_count_by_employee(self):
        """
        Đếm số task có task_type = 'bug' được assign cho từng nhân viên
        trong kỳ đánh giá.

        Returns:
            list[dict]: [
                {
                    'employee_id': int,
                    'name': str,
                    'bug_count': int,
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        employees = (
            self.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("department_id", "=", self.department_id.id),
                    ("active", "=", True),
                ],
                order="name asc",
            )
        )
        if not employees:
            return []

        user_ids = employees.mapped("user_id").ids
        if not user_ids:
            return []

        # Query 1 lần tất cả bug tasks trong kỳ
        # 1. Kiểm tra xem field 'task_type' có tồn tại trong model project.task hay không
        if "task_type" in self.env["project.task"]._fields:
            bug_tasks = (
                self.env["project.task"]
                .sudo()
                .search(
                    [
                        ("task_type", "=", "bug"),
                        ("user_ids", "in", user_ids),
                        ("date_deadline", ">=", self.start_date),
                        ("date_deadline", "<=", self.end_date),
                        ("project_id", "!=", False),
                    ]
                )
            )
        else:
            # 2. Nếu không có field, trả về một recordset rỗng của model đó
            bug_tasks = self.env["project.task"].browse()

        # Group by user_id — 1 task nhiều user → đếm cho từng user
        count_by_user = {}
        for task in bug_tasks:
            for user in task.user_ids:
                count_by_user[user.id] = count_by_user.get(user.id, 0) + 1

        result = []
        for emp in employees:
            if not emp.user_id:
                continue
            result.append(
                {
                    "employee_id": emp.id,
                    "name": emp.name,
                    "bug_count": count_by_user.get(emp.user_id.id, 0),
                }
            )

        return result

    def _dashboard_score_trend(self, limit=6):
        """Lấy xu hướng điểm KPI phòng ban qua các kỳ gần nhất của cùng phòng ban."""
        self.ensure_one()
        if not self.department_id:
            return {"labels": [], "scores": []}

        history = self.search(
            [
                ("department_id", "=", self.department_id.id),
                ("state", "!=", "cancel"),
            ],
            order="start_date desc, id desc",
            limit=limit,
        )
        history = history.sorted(
            key=lambda rec: (rec.start_date or fields.Date.today(), rec.id)
        )

        labels = []
        scores = []
        for rec in history:
            label = rec.period_id.name or (
                rec.start_date.strftime("%m/%Y") if rec.start_date else rec.name
            )
            labels.append(label)
            scores.append(round(float(rec.dept_kpi_score or 0.0), 2))

        return {
            "labels": labels,
            "scores": scores,
        }

    @api.model
    def get_kpi_tree_data(self, period_start=None, period_end=None):
        """Trả về toàn bộ dữ liệu cho KPI Tree Dashboard theo một RPC duy nhất.

        Quy ước quan trọng: toàn bộ điểm trong payload này giữ nguyên theo thang điểm cấu hình.
        Frontend chỉ format lại cách hiển thị, không tự nhân sang thang 100.
        """
        try:
            Evaluation = self.env["hr.performance.evaluation"].sudo()
            DeptEvaluation = self.env["hr.department.performance.evaluation"].sudo()
            settings = self.env["res.config.settings"]
            score_scale = settings.get_score_scale_info()
            widgets = []

            # ── Thresholds theo thang điểm cấu hình ───────────────────────────
            threshold_excellent, threshold_pass = settings.get_thresholds()

            def _empty_response(period=None):
                """Tạo response rỗng nhưng đủ key để OWL không bị crash khi render."""
                return {
                    "period": period or {"start": "", "end": "", "label": ""},
                    "available_periods": available_periods,
                    "widgets": widgets,
                    "widget_map": {},
                    "score_scale": score_scale,
                    "company": {
                        "dept_kpi_score": 0.0,
                        "avg_total_p3_individual": 0.0,
                        "total_employees": 0,
                        "total_depts": 0,
                        "pass_employee_count": 0,
                    },
                    "departments": [],
                    "risk_lines": [],
                    "missing_data_lines": [],
                    "failed_evaluation_lines": [],
                    "risk_kpis": [],
                    "missing_data_kpis": [],
                    "failed_evaluations": [],
                    "logic_warnings": [],
                    "financial_kpis": [],
                    "ai_insights": [],
                    "trends": [],
                    "thresholds": {
                        "excellent": threshold_excellent,
                        "pass": threshold_pass,
                    },
                }

            # ── Available periods ─────────────────────────────────────────────
            # Lấy tối đa 12 kỳ có dữ liệu cá nhân hoặc phòng ban để dropdown không bỏ sót kỳ.
            self.env.cr.execute("""
                SELECT DISTINCT start_date, end_date FROM (
                    SELECT start_date, end_date
                    FROM hr_performance_evaluation
                    WHERE start_date IS NOT NULL AND end_date IS NOT NULL
                    UNION
                    SELECT start_date, end_date
                    FROM hr_department_performance_evaluation
                    WHERE start_date IS NOT NULL AND end_date IS NOT NULL
                ) AS kpi_periods
                ORDER BY start_date DESC
                LIMIT 12
            """)
            period_rows = self.env.cr.fetchall()

            available_periods = []
            for sd, ed in period_rows:
                label = sd.strftime("T%m/%Y") if sd else str(sd)
                available_periods.append(
                    {
                        "start": str(sd),
                        "end": str(ed),
                        "label": label,
                    }
                )

            if not available_periods:
                return _empty_response()

            # ── Xác định kỳ hiện tại ─────────────────────────────────────────
            if period_start and period_end:
                current_period = {"start": period_start, "end": period_end}
                # Tìm label tương ứng
                from datetime import datetime

                try:
                    sd_obj = datetime.strptime(period_start, "%Y-%m-%d")
                    current_period["label"] = sd_obj.strftime("T%m/%Y")
                except Exception:
                    current_period["label"] = period_start
            else:
                current_period = available_periods[0]
                period_start = current_period["start"]
                period_end = current_period["end"]

            # ── Lấy tất cả evaluations trong kỳ ─────────────────────────────
            evals = Evaluation.search(
                [
                    ("start_date", "=", period_start),
                    ("end_date", "=", period_end),
                    ("state", "!=", "cancel"),
                ]
            )

            # Lấy phiếu KPI phòng ban đúng kỳ, tránh dùng field latest-period trên hr.department.
            dept_evals = DeptEvaluation.search(
                [
                    ("start_date", "=", period_start),
                    ("end_date", "=", period_end),
                    ("state", "!=", "cancel"),
                ],
                order="end_date desc, start_date desc, id desc",
            )
            dept_eval_by_dept = {}
            for dept_eval in dept_evals:
                dept = dept_eval.department_id
                if dept and dept.id not in dept_eval_by_dept:
                    dept_eval_by_dept[dept.id] = dept_eval

            if not evals and not dept_eval_by_dept:
                return _empty_response(current_period)

            # ── Nhóm theo phòng ban ───────────────────────────────────────────
            dept_map = {}  # dept_id → {'dept': hr.department record, 'evals': list}
            for ev in evals:
                dept = ev.department_id
                if not dept:
                    continue
                if dept.id not in dept_map:
                    dept_map[dept.id] = {"dept": dept, "evals": []}
                dept_map[dept.id]["evals"].append(ev)

            # Thêm các phòng ban có phiếu KPI phòng ban nhưng chưa có phiếu cá nhân trong kỳ.
            for dept_id, dept_eval in dept_eval_by_dept.items():
                if dept_id not in dept_map:
                    dept_map[dept_id] = {
                        "dept": dept_eval.department_id,
                        "evals": [],
                    }

            # ── Build departments list ────────────────────────────────────────
            departments = []
            total_dept_kpi_scores = []
            total_p3_individual_scores = []
            total_pass_count = 0
            total_emp_count = 0

            for dept_id, info in dept_map.items():
                dept = info["dept"]
                employee_evals = info["evals"]
                dept_eval = dept_eval_by_dept.get(dept_id)
                dept_kpi = dept_eval.get_dept_kpi_score() if dept_eval else 0.0

                pass_count = sum(
                    1
                    for ev in employee_evals
                    if (ev.performance_level or "fail") != "fail"
                )
                total_pass_count += pass_count
                total_emp_count += len(employee_evals)
                total_dept_kpi_scores.append(dept_kpi)

                employees = []
                for ev in employee_evals:
                    # Lấy dữ liệu nhân viên và KPI phòng ban tương ứng để build node detail panel.
                    emp = ev.employee_id
                    emp_dept_eval = ev.dept_evaluation_id or dept_eval
                    emp_dept_kpi = (
                        emp_dept_eval.get_dept_kpi_score() if emp_dept_eval else 0.0
                    )
                    # Giữ nguyên điểm theo thang cấu hình để frontend chỉ việc format hiển thị.
                    total_p2_1 = float(ev.total_p2_1 or 0.0)
                    total_p2_2 = float(ev.total_p2_2 or 0.0)
                    total_p3_individual = float(ev.total_p3_individual or 0.0)
                    total_p3_individual_scores.append(total_p3_individual)
                    employees.append(
                        {
                            "id": ev.id,
                            "employee_id": emp.id,
                            "name": emp.name or "",
                            "job": emp.job_id.name if emp.job_id else "",
                            "avatar_url": f"/web/image/hr.employee/{emp.id}/image_128"
                            if emp.id
                            else "",
                            "total_p2_1": round(total_p2_1, 2),
                            "total_p2_2": round(total_p2_2, 2),
                            "total_p3_individual": round(total_p3_individual, 2),
                            "dept_kpi_score": round(float(emp_dept_kpi), 2),
                            "performance_level": ev.performance_level or "fail",
                            "state": ev.state or "",
                        }
                    )

                # Điểm trung bình cấp phòng ban dùng cho detail panel, cùng thang điểm cấu hình.
                avg_total_p3_individual = (
                    sum(ev.total_p3_individual or 0.0 for ev in employee_evals)
                    / len(employee_evals)
                    if employee_evals
                    else 0.0
                )

                departments.append(
                    {
                        "id": dept_id,
                        "name": dept.name or "",
                        "manager_name": dept.manager_id.name if dept.manager_id else "",
                        "dept_kpi_score": round(float(dept_kpi), 2),
                        "avg_total_p3_individual": round(
                            float(avg_total_p3_individual), 2
                        ),
                        "employee_count": len(employee_evals),
                        "employees": employees,
                    }
                )

            # Sort departments theo dept_kpi_score desc
            departments.sort(key=lambda d: d["dept_kpi_score"], reverse=True)

            # ── Company summary ───────────────────────────────────────────────
            company_dept_kpi = (
                sum(total_dept_kpi_scores) / len(total_dept_kpi_scores)
                if total_dept_kpi_scores
                else 0.0
            )
            company_avg_total_p3_individual = (
                sum(total_p3_individual_scores) / len(total_p3_individual_scores)
                if total_p3_individual_scores
                else 0.0
            )

            # ── Failed evaluations: phiếu cá nhân/phòng ban không đạt theo threshold pass
            # Nhân viên dùng total_p3_individual như điểm KPI cá nhân chuẩn.
            failed_evaluation_lines = []
            for ev in evals.filtered(
                lambda record: float(record.total_p3_individual or 0.0)
                < threshold_pass
            ):
                score = float(ev.total_p3_individual or 0.0)
                failed_evaluation_lines.append(
                    {
                        "source_type": "employee",
                        "source_label": "Cá nhân",
                        "record_model": "hr.performance.evaluation",
                        "record_id": ev.id,
                        "evaluation_name": ev.name or "",
                        "dept_name": ev.department_id.name if ev.department_id else "",
                        "employee_name": ev.employee_id.name if ev.employee_id else "",
                        "score": round(score, 2),
                        "score_label": "KPI cá nhân",
                        "state": ev.state or "",
                        "level": "fail",
                    }
                )
            for ev in dept_evals.filtered(
                lambda record: (
                    float(record.get_dept_kpi_score() or 0.0) < threshold_pass
                )
            ):
                score = float(ev.get_dept_kpi_score() or 0.0)
                failed_evaluation_lines.append(
                    {
                        "source_type": "department",
                        "source_label": "Phòng ban",
                        "record_model": "hr.department.performance.evaluation",
                        "record_id": ev.id,
                        "evaluation_name": ev.name or "",
                        "dept_name": ev.department_id.name if ev.department_id else "",
                        "employee_name": "",
                        "score": round(score, 2),
                        "score_label": "KPI phòng ban",
                        "state": ev.state or "",
                        "level": "fail",
                    }
                )
            failed_evaluation_lines.sort(
                key=lambda item: (
                    item.get("score") or 0.0,
                    item.get("source_type") or "",
                    item.get("record_id") or 0,
                )
            )
            failed_evaluations = failed_evaluation_lines[:5]

            # ── Risk KPIs: tất cả KPI cá nhân + phòng ban bị fail theo threshold pass
            EvalLine = self.env["hr.performance.evaluation.line"].sudo()
            DeptEvalLine = self.env["hr.department.evaluation.line"].sudo()
            employee_risk_line_records = EvalLine.search(
                [
                    ("evaluation_id", "in", evals.ids),
                    ("is_section", "=", False),
                    ("final_rating", "<", threshold_pass),
                ],
                order="final_rating asc, id asc",
            )
            department_risk_line_records = DeptEvalLine.search(
                [
                    ("evaluation_id", "in", dept_evals.ids),
                    ("is_section", "=", False),
                    ("final_score", "<", threshold_pass),
                ],
                order="final_score asc, id asc",
            )

            risk_lines = []
            for line in employee_risk_line_records:
                ev = line.evaluation_id
                score = float(line.final_rating or 0.0)
                risk_lines.append(
                    {
                        "source_type": "employee",
                        "source_label": "Cá nhân",
                        "line_model": "hr.performance.evaluation.line",
                        "line_id": line.id,
                        "evaluation_model": "hr.performance.evaluation",
                        "evaluation_id": ev.id,
                        "evaluation_name": ev.name or "",
                        "kpi_name": line.key_performance_area or "",
                        "dept_name": ev.department_id.name if ev.department_id else "",
                        "employee_name": ev.employee_id.name if ev.employee_id else "",
                        "score": round(score, 2),
                        "level": "fail",
                        "kpi_type": line.kpi_type or "",
                        "manual_scoring_type": line.manual_scoring_type or "",
                    }
                )
            for line in department_risk_line_records:
                ev = line.evaluation_id
                score = float(line.final_score or 0.0)
                risk_lines.append(
                    {
                        "source_type": "department",
                        "source_label": "Phòng ban",
                        "line_model": "hr.department.evaluation.line",
                        "line_id": line.id,
                        "evaluation_model": "hr.department.performance.evaluation",
                        "evaluation_id": ev.id,
                        "evaluation_name": ev.name or "",
                        "kpi_name": line.name or "",
                        "dept_name": ev.department_id.name if ev.department_id else "",
                        "employee_name": "",
                        "score": round(score, 2),
                        "level": "fail",
                        "kpi_type": line.kpi_type or "",
                        "manual_scoring_type": line.manual_scoring_type or "",
                    }
                )
            risk_lines.sort(
                key=lambda item: (
                    item.get("score") or 0.0,
                    item.get("source_type") or "",
                    item.get("line_id") or 0,
                )
            )
            risk_kpis = risk_lines[:5]

            # ── Missing data KPIs: KPI cá nhân + phòng ban thiếu dữ liệu actual
            employee_missing_line_records = EvalLine.search(
                [
                    ("evaluation_id", "in", evals.ids),
                    ("is_section", "=", False),
                    ("is_auto", "=", True),
                    ("is_special_scoring", "=", False),
                    ("kpi_type", "=", "auto"),
                    ("actual", "=", False),
                ],
                order="id asc",
            )
            department_missing_line_records = DeptEvalLine.search(
                [
                    ("evaluation_id", "in", dept_evals.ids),
                    ("is_section", "=", False),
                    ("is_auto", "=", True),
                    ("kpi_type", "=", "auto"),
                    ("actual", "=", False),
                ],
                order="id asc",
            )

            missing_data_lines = []
            for line in employee_missing_line_records:
                ev = line.evaluation_id
                missing_data_lines.append(
                    {
                        "source_type": "employee",
                        "source_label": "Cá nhân",
                        "line_model": "hr.performance.evaluation.line",
                        "line_id": line.id,
                        "evaluation_model": "hr.performance.evaluation",
                        "evaluation_id": ev.id,
                        "evaluation_name": ev.name or "",
                        "kpi_name": line.key_performance_area or "",
                        "dept_name": ev.department_id.name if ev.department_id else "",
                        "employee_name": ev.employee_id.name if ev.employee_id else "",
                        "kpi_type": line.kpi_type or "",
                        "manual_scoring_type": line.manual_scoring_type or "",
                    }
                )
            for line in department_missing_line_records:
                ev = line.evaluation_id
                missing_data_lines.append(
                    {
                        "source_type": "department",
                        "source_label": "Phòng ban",
                        "line_model": "hr.department.evaluation.line",
                        "line_id": line.id,
                        "evaluation_model": "hr.department.performance.evaluation",
                        "evaluation_id": ev.id,
                        "evaluation_name": ev.name or "",
                        "kpi_name": line.name or "",
                        "dept_name": ev.department_id.name if ev.department_id else "",
                        "employee_name": "",
                        "kpi_type": line.kpi_type or "",
                        "manual_scoring_type": line.manual_scoring_type or "",
                    }
                )
            missing_data_lines.sort(
                key=lambda item: (
                    item.get("source_type") or "",
                    item.get("dept_name") or "",
                    item.get("employee_name") or "",
                    item.get("line_id") or 0,
                )
            )
            missing_data_kpis = missing_data_lines[:5]

            return {
                "period": current_period,
                "available_periods": available_periods,
                "widgets": widgets,
                "widget_map": {},
                "score_scale": score_scale,
                "company": {
                    "dept_kpi_score": round(company_dept_kpi, 2),
                    "avg_total_p3_individual": round(
                        company_avg_total_p3_individual, 2
                    ),
                    "total_employees": total_emp_count,
                    "total_depts": len(departments),
                    "pass_employee_count": total_pass_count,
                },
                "departments": departments,
                "risk_lines": risk_lines,
                "missing_data_lines": missing_data_lines,
                "failed_evaluation_lines": failed_evaluation_lines,
                "risk_kpis": risk_kpis,
                "missing_data_kpis": missing_data_kpis,
                "failed_evaluations": failed_evaluations,
                "logic_warnings": [],
                "financial_kpis": [],
                "ai_insights": [],
                "trends": [],
                "thresholds": {
                    "excellent": threshold_excellent,
                    "pass": threshold_pass,
                },
            }

        except Exception as e:
            _logger.exception("get_kpi_tree_data failed: %s", str(e))
            return {
                "period": {"start": "", "end": "", "label": ""},
                "available_periods": [],
                "widgets": [],
                "widget_map": {},
                "score_scale": {
                    "base": 100.0,
                    "display_multiplier": 1,
                    "storage_base": 100.0,
                    "suffix": " / 100",
                },
                "company": {
                    "dept_kpi_score": 0.0,
                    "avg_total_p3_individual": 0.0,
                    "total_employees": 0,
                    "total_depts": 0,
                    "pass_employee_count": 0,
                },
                "departments": [],
                "risk_lines": [],
                "missing_data_lines": [],
                "failed_evaluation_lines": [],
                "risk_kpis": [],
                "missing_data_kpis": [],
                "failed_evaluations": [],
                "logic_warnings": [],
                "financial_kpis": [],
                "ai_insights": [],
                "trends": [],
                "thresholds": {"excellent": 90.0, "pass": 50.0},
            }
