from markupsafe import Markup

from dateutil.relativedelta import relativedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrDepartmentKpiGenerateWizard(models.TransientModel):
    _name = "hr.department.kpi.generate.wizard"
    _description = "Generate Department Performance Evaluations"

    department_kpi_id = fields.Many2one(
        "hr.department.kpi.template",
        string="Department KPI Template",
        required=True,
        default=lambda self: self.env.context.get("default_department_kpi_id"),
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="department_kpi_id.department_id",
        readonly=True,
    )
    kpi_template_id = fields.Many2one(
        "hr.kpi.template",
        string="Fallback Employee KPI Template",
        help="Optional generic KPI template used when an employee does not have a job-specific KPI template in this department.",
    )
    period_type = fields.Selection(
        related="department_kpi_id.period_type",
        string="Period Type",
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        string="KPI Period",
        required=True,
        domain="[('period_type', '=', period_type)]",
    )
    start_date = fields.Date(
        related="period_id.date_start",
        string="Start Date",
        readonly=True,
        store=True,
    )
    end_date = fields.Date(
        related="period_id.date_end",
        string="End Date",
        readonly=True,
        store=True,
    )
    deadline = fields.Date(string="Deadline", required=True)

    # Lấy toàn bộ template KPI nhân viên cùng phòng ban/cùng kỳ để map theo vị trí.
    def _get_department_template_candidates(self):
        self.ensure_one()
        if not self.department_id or not self.period_id:
            return self.env["hr.kpi.template"]

        # Gom theo đúng phòng ban và chu kỳ trước, sau đó wizard sẽ tự chọn template tốt nhất cho từng nhân viên.
        return self.env["hr.kpi.template"].search(
            [
                ("department_id", "=", self.department_id.id),
                ("period_type", "=", self.period_id.period_type),
            ]
        )

    # Tính độ ưu tiên template cho từng nhân viên; template theo vị trí và đúng parent KPI được ưu tiên trước.
    def _get_template_priority(self, template, employee):
        self.ensure_one()

        # Ưu tiên template thuộc đúng Department KPI Template hiện tại trước.
        if template.department_kpi_id == self.department_kpi_id:
            parent_rank = 0
        elif not template.department_kpi_id:
            parent_rank = 1
        else:
            parent_rank = 2

        # Template gắn job cụ thể phải thắng template dùng chung của cả phòng ban.
        job_rank = 0 if template.job_id else 1

        # Trong nhóm template có job scope, template áp cho ít vị trí hơn sẽ đặc hiệu hơn.
        job_scope_rank = len(template.job_id) if template.job_id else 9999

        # Nếu người dùng chọn một fallback template trong wizard thì ưu tiên nó khi cùng mức đặc hiệu.
        fallback_rank = 0 if self.kpi_template_id and template == self.kpi_template_id else 1
        return (parent_rank, job_rank, job_scope_rank, fallback_rank, template.id)

    # Chọn đúng KPI template cho từng nhân viên trong cùng phòng ban dựa trên vị trí hiện tại.
    def _get_employee_template(self, employee, template_candidates):
        self.ensure_one()

        # Chỉ giữ những template thực sự match với phòng ban/vị trí của nhân viên.
        matching_templates = template_candidates.filtered(
            lambda template: template.matches_employee(employee)
        )
        if not matching_templates:
            return self.env["hr.kpi.template"]

        # Sắp xếp theo mức ưu tiên để lấy ra template phù hợp nhất cho nhân viên này.
        ranked_templates = sorted(
            matching_templates,
            key=lambda template: self._get_template_priority(template, employee),
        )
        best_template = ranked_templates[0]
        best_priority = self._get_template_priority(best_template, employee)[:-1]

        # Nếu có hơn một template cùng mức ưu tiên cao nhất thì dữ liệu đang mơ hồ và phải chặn generate.
        ambiguous_templates = matching_templates.filtered(
            lambda template: self._get_template_priority(template, employee)[:-1]
            == best_priority
        )
        if len(ambiguous_templates) > 1:
            raise ValidationError(
                _(
                    "Multiple KPI templates match employee '%(employee)s'. Please keep only one template for the same department, period, parent department KPI template, and job position scope."
                )
                % {"employee": employee.name}
            )
        return best_template

    # Gom template theo từng nhân viên và báo lỗi sớm nếu còn thiếu cấu hình theo vị trí.
    def _get_employee_template_map(self, employees):
        self.ensure_one()
        template_candidates = self._get_department_template_candidates()
        employee_template_map = {}
        missing_employees = []

        for employee in employees:
            # Resolve template riêng cho từng nhân viên thay vì dùng một template chung cho cả phòng ban.
            employee_template = self._get_employee_template(employee, template_candidates)
            if employee_template:
                employee_template_map[employee.id] = employee_template
                continue

            # Ghi nhận các nhân viên chưa có template để trả lỗi cấu hình một lần, dễ xử lý dữ liệu hơn.
            job_name = employee.job_id.name or _("No Job Position")
            missing_employees.append(f"{employee.name} ({job_name})")

        if missing_employees:
            raise ValidationError(
                _(
                    "Please configure an employee KPI template for the following employees: %(employees)s."
                )
                % {"employees": ", ".join(missing_employees)}
            )
        return employee_template_map

    @api.onchange("department_kpi_id", "period_id")
    def _onchange_department_kpi_id(self):
        if not self.department_kpi_id or not self.department_id or not self.period_id:
            self.kpi_template_id = False
            return

        # Chỉ prefill template fallback dùng chung cho cả phòng ban; template theo vị trí sẽ được tự map khi generate.
        fallback_candidates = self.env["hr.kpi.template"].search(
            [
                ("department_id", "=", self.department_id.id),
                ("period_type", "=", self.period_id.period_type),
                ("job_id", "=", False),
                "|",
                ("department_kpi_id", "=", self.department_kpi_id.id),
                ("department_kpi_id", "=", False),
            ]
        )

        # Ưu tiên template generic gắn đúng parent KPI hiện tại nếu nó là duy nhất.
        preferred_fallbacks = fallback_candidates.filtered(
            lambda template: template.department_kpi_id == self.department_kpi_id
        )
        if len(preferred_fallbacks) == 1:
            self.kpi_template_id = preferred_fallbacks
            return

        # Nếu không có template generic theo parent nhưng chỉ có đúng 1 fallback tổng quát thì dùng nó.
        self.kpi_template_id = fallback_candidates if len(fallback_candidates) == 1 else False

    @api.onchange("period_id")
    def _onchange_period_set_dates(self):
        if not self.period_id:
            return
        self.deadline = self.period_id.date_end + relativedelta(days=5)

    # Ensure the 3P summary exists and is refreshed from the exact department evaluation being used.
    def _ensure_3p_summary(self, department_evaluation):
        self.ensure_one()
        return self.env["hr.evaluation.3p.summary"].ensure_summary_for_department_evaluation(
            department_evaluation
        )

    # Generate department and individual evaluations, then build the matching 3P summary.
    def action_generate(self):
        self.ensure_one()
        if not self.department_kpi_id:
            raise ValidationError(_("Please select a Department KPI Template."))
        if not self.department_id:
            raise ValidationError(
                _("The Department KPI Template must have a Department assigned.")
            )
        if self.kpi_template_id and self.kpi_template_id.period_type != self.period_id.period_type:
            raise ValidationError(
                _("The fallback Employee KPI Template period type must match the selected Department KPI period type.")
            )

        employees = self.env["hr.employee"].search(
            [("active", "=", True), ("department_id", "=", self.department_id.id)]
        )
        if not employees:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Warning",
                    "message": _("No active employees found in this department."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        DeptEvaluation = self.env["hr.department.performance.evaluation"]
        exists_dept_eval = DeptEvaluation.search(
            [
                ("department_id", "=", self.department_id.id),
                ("department_kpi_id", "=", self.department_kpi_id.id),
                ("period_id", "=", self.period_id.id),
                ("start_date", "=", self.start_date),
                ("end_date", "=", self.end_date),
            ],
            limit=1,
        )
        if exists_dept_eval:
            # Nếu phiếu phòng ban đã tồn tại thì summary cũng phải bám chính record đó,
            # không được tạo mới thủ công theo department/period chung chung.
            self._ensure_3p_summary(exists_dept_eval)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No New Data"),
                    "message": _(
                        "A department performance evaluation already exists for this period. The 3P summary has been refreshed."
                    ),
                    "type": "warning",
                    "sticky": False,
                },
            }

        # Resolve template theo từng nhân viên trước khi tạo bất kỳ record nào để tránh generate dở dang.
        employee_template_map = self._get_employee_template_map(employees)

        report = self.env["hr.performance.report"].sudo().create(
            {
                "period_id": self.period_id.id,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "deadline": self.deadline,
                "department_id": self.department_id.id,
                "employee_id": [(6, 0, employees.ids)],
            }
        )

        scratch_dept = DeptEvaluation.new(
            {
                "department_kpi_id": self.department_kpi_id.id,
                "period_id": self.period_id.id,
            }
        )
        dept_line_cmds = scratch_dept._prepare_evaluation_line_commands_from_template(
            self.department_kpi_id
        )
        dept_eval = DeptEvaluation.create(
            {
                "department_id": self.department_id.id,
                "department_kpi_id": self.department_kpi_id.id,
                "period_id": self.period_id.id,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "deadline": self.deadline,
                "performance_report_id": report.id,
                "evaluation_line_ids": dept_line_cmds,
            }
        )

        count = 0
        individual_evals = self.env["hr.performance.evaluation"]
        Evaluation = self.env["hr.performance.evaluation"]
        valid_employees = self.env["hr.employee"]
        valid_employee_templates = {}
        for employee in employees:
            # Lấy template đã resolve theo job_id của từng nhân viên trong phòng ban.
            employee_template = employee_template_map.get(employee.id)
            if not employee_template:
                continue

            # Chặn tạo trùng nhiều evaluation cho cùng một nhân viên trong cùng kỳ.
            exists = Evaluation.search(
                [
                    ("employee_id", "=", employee.id),
                    ("period_id", "=", self.period_id.id),
                    ("start_date", "=", self.start_date),
                    ("end_date", "=", self.end_date),
                ],
                limit=1,
            )
            if exists:
                continue

            valid_employees |= employee
            valid_employee_templates[employee.id] = employee_template

        if valid_employees:
            report.employee_id = [(6, 0, valid_employees.ids)]

        for employee in valid_employees:
            employee_template = valid_employee_templates[employee.id]

            # Dùng template riêng của nhân viên để dựng line tree đúng với vị trí công việc hiện tại.
            scratch = Evaluation.new(
                {
                    "kpi_id": employee_template.id,
                    "period_id": self.period_id.id,
                }
            )
            line_cmds = scratch._prepare_evaluation_line_commands_from_template(
                employee_template,
            )
            evaluation = Evaluation.create(
                {
                    "employee_id": employee.id,
                    "kpi_id": employee_template.id,
                    "period_id": self.period_id.id,
                    "start_date": self.start_date,
                    "end_date": self.end_date,
                    "deadline": self.deadline,
                    "evaluation_line_ids": line_cmds,
                    "performance_report_id": report.id,
                    "dept_evaluation_id": dept_eval.id,
                }
            )
            self.send_notification(employee, evaluation)
            individual_evals |= evaluation
            count += 1

        if individual_evals:
            individual_evals._compute_pillar_totals()
            individual_evals._compute_performance_level()

        # Summary chỉ được tạo/làm mới sau khi phiếu phòng ban đã tồn tại và
        # toàn bộ phiếu cá nhân của cùng kỳ đã sẵn sàng cho bước aggregate.
        self._ensure_3p_summary(dept_eval)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _(
                    "Created 1 Department Evaluation, %(count)s Individual Evaluations, and refreshed the 3P summary for the %(period)s period."
                )
                % {"count": count, "period": self.period_id.name},
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def send_notification(self, emp, evaluation):
        if emp.user_id and emp.user_id.partner_id:
            period_str = self.period_id.name if self.period_id else ""
            start_str = self.start_date.strftime("%d/%m/%Y")
            end_str = self.end_date.strftime("%d/%m/%Y")
            base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
            record_url = (
                f"{base_url}/web#id={evaluation.id}&model=hr.performance.evaluation&view_type=form"
            )
            msg_body = _(
                """
                <div style="margin: 0; padding: 0;">
                    <p>Hello <b>%s</b>,</p>
                    <p>A new KPI evaluation has been created for you in the system.</p>
                    <ul>
                        <li><b>Evaluation Period:</b> %s</li>
                        <li><b>Standard Time:</b> From %s to %s</li>
                    </ul>
                    <p>Please click the button below to view details and complete your self-assessment (if applicable).</p>

                    <div style="margin-top: 20px; margin-bottom: 20px;">
                        <a href="%s" 
                           style="background-color: #714B67; padding: 10px 20px; color: #FFFFFF; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            View Evaluation
                        </a>
                    </div>
                </div>
                """
            ) % (emp.name, period_str, start_str, end_str, record_url)

            emp.message_post(
                body=Markup(msg_body),
                subject=_("[Notification] You have a new KPI evaluation"),
                partner_ids=[emp.user_id.partner_id.id],
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
