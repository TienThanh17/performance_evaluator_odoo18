import base64
import io
import json

import xlsxwriter
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext
from xlsxwriter.utility import xl_rowcol_to_cell


class HrEvaluation3PSummary(models.Model):
    _name = "hr.evaluation.3p.summary"
    _description = "Department 3P Summary"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_id desc, department_id, id desc"

    P2_1_EXPORT_COLUMN_COUNT = 5
    P2_2_EXPORT_COLUMN_COUNT = 16

    name = fields.Char(required=True, tracking=True, default="New")
    department_evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation",
        string="Department Evaluation",
        tracking=True,
        ondelete="cascade",
    )
    department_id = fields.Many2one(
        "hr.department",
        related="department_evaluation_id.department_id",
        store=True,
        readonly=True,
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        related="department_evaluation_id.period_id",
        store=True,
        readonly=True,
    )
    start_date = fields.Date(
        related="department_evaluation_id.start_date",
        store=True,
        readonly=True,
    )
    end_date = fields.Date(
        related="department_evaluation_id.end_date",
        store=True,
        readonly=True,
    )
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

    # Tìm phiếu KPI phòng ban phù hợp để summary luôn neo vào đúng bản ghi nguồn.
    @api.model
    def _resolve_department_evaluation(self, department, period):
        department_id = department.id if hasattr(department, "id") else department
        period_id = period.id if hasattr(period, "id") else period
        if not department_id or not period_id:
            return self.env["hr.department.performance.evaluation"]

        # Ưu tiên phiếu mới nhất của cùng phòng ban và kỳ để giữ hành vi nhất quán
        # với luồng generate summary hiện tại.
        return self.env["hr.department.performance.evaluation"].search(
            [
                ("department_id", "=", department_id),
                ("period_id", "=", period_id),
                ("state", "!=", "cancel"),
            ],
            order="id desc",
            limit=1,
        )

    # Chuẩn hóa vals create để bản summary mới luôn giữ liên kết Many2one với phiếu KPI phòng ban.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("department_evaluation_id"):
                department_evaluation = self._resolve_department_evaluation(
                    vals.get("department_id"),
                    vals.get("period_id"),
                )
                if department_evaluation:
                    vals["department_evaluation_id"] = department_evaluation.id

            # Chặn tạo summary mồ côi vì toàn bộ field chính nay phụ thuộc phiếu KPI phòng ban.
            if not vals.get("department_evaluation_id"):
                raise ValidationError(
                    _(
                        "Please select a Department Evaluation before creating the 3P summary."
                    )
                )

            if not vals.get("name") or vals.get("name") == "New":
                department_evaluation = self.env[
                    "hr.department.performance.evaluation"
                ].browse(vals["department_evaluation_id"])
                vals["name"] = self._build_default_name(
                    department_evaluation.department_id.id,
                    department_evaluation.period_id.id,
                )
        return super().create(vals_list)

    @api.model
    def _build_default_name(self, department_id, period_id):
        department = (
            self.env["hr.department"].browse(department_id) if department_id else False
        )
        period = self.env["hr.kpi.period"].browse(period_id) if period_id else False

        # Dùng placeholder theo vị trí để tránh lỗi KeyError khi bản dịch làm sai tên biến nội suy.
        if department and period:
            return _("3P Summary - %s - %s") % (
                department.display_name,
                period.display_name,
            )
        return _("3P Summary")

    def action_set_draft(self):
        self.write({"state": "draft"})
        return True

    # Find or create the summary header from a concrete department evaluation record.
    @api.model
    def get_or_create_summary_for_department_evaluation(self, department_evaluation):
        if not department_evaluation:
            raise UserError(
                _("A Department Evaluation is required before creating the 3P summary.")
            )

        if isinstance(department_evaluation, int):
            department_evaluation = self.env[
                "hr.department.performance.evaluation"
            ].browse(department_evaluation)

        # Ưu tiên bản summary đã neo trực tiếp vào phiếu KPI phòng ban.
        summary = self.search(
            [("department_evaluation_id", "=", department_evaluation.id)],
            order="id desc",
            limit=1,
        )
        if summary:
            return summary

        # Chỉ tạo summary khi đã có phiếu KPI phòng ban thật sự, đúng với nghiệp vụ generate.
        return self.create(
            {
                "department_evaluation_id": department_evaluation.id,
            }
        )

    # Find or create the summary header for a department and KPI period.
    @api.model
    def get_or_create_summary(self, department, period):
        department_evaluation = self._resolve_department_evaluation(department, period)
        if not department_evaluation:
            raise UserError(
                _(
                    "No active Department Evaluation was found for the selected department and period."
                )
            )
        return self.get_or_create_summary_for_department_evaluation(
            department_evaluation
        )

    # Ensure the summary exists and refreshes from a concrete department evaluation source.
    @api.model
    def ensure_summary_for_department_evaluation(self, department_evaluation):
        summary = self.get_or_create_summary_for_department_evaluation(
            department_evaluation
        )
        summary.action_aggregate()
        return summary

    # Làm mới toàn bộ summary 3P của các phiếu phòng ban bị ảnh hưởng trong cùng một batch.
    @api.model
    def refresh_summaries_for_department_evaluations(self, department_evaluations):
        department_evaluations = department_evaluations.filtered(
            lambda evaluation: evaluation and evaluation.state != "cancel"
        )
        for department_evaluation in department_evaluations:
            self.ensure_summary_for_department_evaluation(department_evaluation)
        return True

    # Ensure the summary exists and refresh its lines from current evaluations.
    @api.model
    def ensure_summary_for_period(self, department, period):
        summary = self.get_or_create_summary(department, period)
        summary.action_aggregate()
        return summary

    # Trả về phiếu KPI phòng ban đang liên kết trực tiếp với bản summary hiện tại.
    def _get_department_evaluation(self):
        self.ensure_one()
        return self.department_evaluation_id

    # Mở dashboard phòng ban đúng phiếu KPI đang gắn với summary để người dùng giữ nguyên ngữ cảnh kỳ đánh giá.
    def action_open_department_dashboard(self):
        self.ensure_one()

        # Chỉ cho phép mở dashboard khi summary đã liên kết với phiếu KPI phòng ban hợp lệ.
        if not self.department_evaluation_id:
            raise UserError(
                _("Please select a Department Evaluation before opening the dashboard.")
            )

        # Tái sử dụng action client hiện hữu của phiếu KPI phòng ban để frontend tự chọn đúng evaluation.
        return self.department_evaluation_id.action_open_department_dashboard()

    # Chuẩn hóa comment HTML thành plain text để snapshot export luôn ổn định.
    def _normalize_comment_text(self, value):
        plain_text = html2plaintext(value or "")
        return " ".join(plain_text.split()).strip()

    # Lấy danh sách root line của P2.1 và quy đổi sang điểm thô theo format Excel cũ.
    def _build_p2_1_export_rows(self, evaluation):
        p2_1_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: line.pillar_code == "p2_1" and not line.parent_line_id
        ).sorted(lambda line: (line.sequence or 0, line.id or 0))

        # Chặn xuất sai layout cố định nếu dữ liệu vượt quá số cột TC của mẫu Excel.
        if len(p2_1_lines) > self.P2_1_EXPORT_COLUMN_COUNT:
            raise UserError(
                _(
                    "P2.1 export expects at most %(count)s top-level rows, but found %(found)s for %(employee)s."
                )
                % {
                    "count": self.P2_1_EXPORT_COLUMN_COUNT,
                    "found": len(p2_1_lines),
                    "employee": evaluation.employee_id.display_name,
                }
            )

        rows = []
        for line in p2_1_lines:
            score = float(line.final_rating or 0.0)
            weight = float(line.weight or 0.0)

            # Excel cũ hiển thị điểm thô = score thang 100 nhân trọng số gốc rồi chia 100.
            rows.append(
                {
                    "name": line.key_performance_area or line.display_name or "",
                    "score": score,
                    "weight": weight,
                    "raw_score": round((score * weight) / 100.0, 2),
                }
            )
        return rows

    # Lấy toàn bộ line lá của P2.2 và quy đổi sang điểm thô theo format Excel cũ.
    def _build_p2_2_export_rows(self, evaluation):
        p2_2_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: line.pillar_code == "p2_2" and not line.is_section
        ).sorted(lambda line: (line.sequence or 0, line.id or 0))

        # Chặn xuất sai layout cố định nếu dữ liệu vượt quá số cột TC của mẫu Excel.
        if len(p2_2_lines) > self.P2_2_EXPORT_COLUMN_COUNT:
            raise UserError(
                _(
                    "P2.2 export expects at most %(count)s rows, but found %(found)s for %(employee)s."
                )
                % {
                    "count": self.P2_2_EXPORT_COLUMN_COUNT,
                    "found": len(p2_2_lines),
                    "employee": evaluation.employee_id.display_name,
                }
            )

        rows = []
        for line in p2_2_lines:
            score = float(line.final_rating or 0.0)
            weight = float(line.weight or 0.0)

            # Excel cũ hiển thị điểm thô = score thang 100 nhân trọng số gốc rồi chia 100.
            rows.append(
                {
                    "name": line.key_performance_area or line.display_name or "",
                    "score": score,
                    "weight": weight,
                    "raw_score": round((score * weight) / 100.0, 2),
                }
            )
        return rows

    # Tính tổng weight của các root section bị wipeout về 0 điểm cho P3.
    def _get_zero_weight_sum(self, lines, score_field):
        zero_weight_sum = 0.0
        for line in lines:
            score = round(float(getattr(line, score_field, 0.0) or 0.0), 2)

            # Chỉ cộng các section root đã bị triệt tiêu hoàn toàn về 0 điểm.
            if score == 0.0:
                zero_weight_sum += float(line.weight or 0.0)
        return round(zero_weight_sum, 2)

    # Gom toàn bộ manager comment thành list text để tái sử dụng cho cả sheet chính và mục III.
    def _build_manager_comment_texts(self, evaluation):
        comment_texts = []
        comment_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: (
                not line.is_section
                and self._normalize_comment_text(line.manager_comment)
            )
        ).sorted(lambda line: (line.sequence or 0, line.id or 0))

        # Giữ đúng thứ tự KPI để comment trên Excel khớp với phiếu đánh giá trong Odoo.
        for line in comment_lines:
            manager_comment = self._normalize_comment_text(line.manager_comment)
            kpi_title = line.key_performance_area or line.display_name or _("KPI")
            comment_texts.append(f"{kpi_title}: {manager_comment}")
        return comment_texts

    # Chốt snapshot detail dùng riêng cho export Excel để file luôn bám đúng lần aggregate gần nhất.
    def _build_excel_export_snapshot(self, evaluation, linked_dept_eval):
        p3_individual_root_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: (
                line.pillar_code == "p3_individual"
                and line.is_section
                and not line.parent_line_id
            )
        ).sorted(lambda line: (line.sequence or 0, line.id or 0))

        # Chỉ đọc P3.1.2 từ phiếu phòng ban đã được liên kết tại thời điểm aggregate.
        p3_department_root_lines = self.env["hr.department.evaluation.line"]
        if linked_dept_eval:
            p3_department_root_lines = linked_dept_eval.evaluation_line_ids.filtered(
                lambda line: (
                    line.pillar_code == "p3_department"
                    and line.is_section
                    and not line.parent_line_id
                )
            ).sorted(lambda line: (line.sequence or 0, line.id or 0))

        return {
            "p2_1": self._build_p2_1_export_rows(evaluation),
            "p2_2": self._build_p2_2_export_rows(evaluation),
            "p3_individual": {
                "zero_weight_sum": self._get_zero_weight_sum(
                    p3_individual_root_lines, "final_rating"
                )
            },
            "p3_department": {
                "zero_weight_sum": self._get_zero_weight_sum(
                    p3_department_root_lines, "final_score"
                )
            },
            "comments": self._build_manager_comment_texts(evaluation),
        }

    # Đọc snapshot JSON của summary line và chặn export nếu dữ liệu cũ chưa được aggregate lại.
    def _load_excel_export_snapshot(self, summary_line):
        snapshot_text = summary_line.excel_export_snapshot or ""
        if not snapshot_text:
            raise UserError(
                _(
                    "Please run Aggregate before exporting because the summary line for %(employee)s does not contain the Excel snapshot yet."
                )
                % {"employee": summary_line.employee_id.display_name}
            )

        # Chỉ chấp nhận JSON hợp lệ để tránh xuất file sai ngầm khi dữ liệu snapshot bị hỏng.
        try:
            return json.loads(snapshot_text)
        except ValueError as exc:
            raise UserError(
                _(
                    "The Excel snapshot for %(employee)s is invalid. Please run Aggregate again before exporting."
                )
                % {"employee": summary_line.employee_id.display_name}
            ) from exc

    # Chuẩn hóa tên file export để không vướng ký tự cấm của hệ điều hành.
    def _sanitize_export_name_part(self, value):
        sanitized = (value or "").strip()
        for char in ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]:
            sanitized = sanitized.replace(char, "-")
        return sanitized.replace(" ", "_") or "Unknown"

    # Dựng tên file động theo phòng ban và kỳ đánh giá hiện tại.
    def _build_export_file_name(self):
        period_label = self.period_id.display_name or (
            f"{self.start_date}_{self.end_date}"
            if self.start_date and self.end_date
            else "Period"
        )
        department_label = self.department_id.display_name or "Department"
        return (
            "3P_Summary_"
            f"{self._sanitize_export_name_part(department_label)}_"
            f"{self._sanitize_export_name_part(period_label)}.xlsx"
        )

    # Trả về chuỗi tháng/kỳ đánh giá để ghi ở phần thông tin chung trên Excel.
    def _get_export_period_label(self):
        if self.period_id and self.period_id.display_name:
            return self.period_id.display_name
        if self.start_date and self.end_date:
            return f"{self.start_date} - {self.end_date}"
        return ""

    # Tính trước giá trị hệ số P3 để ghi kèm với công thức Excel giúp preview ổn định hơn.
    def _compute_p3_coefficient_value(self, total_weight_value):
        if total_weight_value >= 1:
            return 1
        if total_weight_value >= 0.9:
            return 0.8
        if total_weight_value >= 0.8:
            return 0.7
        if total_weight_value >= 0.7:
            return 0.5
        return 0

    # Chuẩn bị bộ field hệ thống cần recompute cho một dòng tổng hợp 3P.
    def _prepare_summary_line_system_vals(
        self,
        evaluation,
        dept_evaluation,
        p3_individual_weight,
        p3_department_weight,
    ):
        linked_dept_eval = evaluation.dept_evaluation_id or dept_evaluation
        export_snapshot = self._build_excel_export_snapshot(
            evaluation, linked_dept_eval
        )

        # Lấy điểm thành phần của từng pillar trực tiếp từ phiếu KPI cá nhân hiện tại.
        p2_1_score = evaluation.get_weighted_score_by_pillar_code("p2_1")
        p2_2_score = evaluation.get_weighted_score_by_pillar_code("p2_2")
        p3_individual_score = evaluation.get_weighted_score_by_pillar_code(
            "p3_individual"
        )

        # Điểm KPI phòng ban dùng từ phiếu liên kết nếu có, ngược lại rơi về 0.
        p3_department_score = (
            linked_dept_eval.dept_kpi_score if linked_dept_eval else 0.0
        )
        # Tính tổng trọng số P3.1 trước khi quy đổi sang hệ số cuối cùng.
        p3_total_weight = (
            (p3_individual_score * (p3_individual_weight/100))
            + (p3_department_score * (p3_department_weight/100))
        ) / 100
        # Quy đổi theo rule hệ số chuẩn, sau đó nhân 100 để Odoo hiển thị theo thang 100.
        p3_1_score = self._compute_p3_coefficient_value(p3_total_weight) * 100

        # Chỉ trả về các field phát sinh từ evaluation để action_aggregate có thể write an toàn
        # mà không ghi đè các field kế toán nhập tay.
        return {
            "employee_id": evaluation.employee_id.id,
            "job_id": evaluation.job_id.id,
            "evaluation_id": evaluation.id,
            "dept_evaluation_id": linked_dept_eval.id if linked_dept_eval else False,
            "p2_1_score_raw": p2_1_score,
            "p2_2_score_raw": p2_2_score,
            "p3_individual_score": p3_individual_score,
            "p3_department_score": p3_department_score,
            "p3_1_score": p3_1_score,
            "excel_export_snapshot": json.dumps(export_snapshot, ensure_ascii=False),
        }

    # Chuẩn bị dữ liệu đầy đủ cho line mới, gồm field hệ thống và default manual ban đầu từ hr.job.
    def _prepare_summary_line_create_vals(
        self,
        evaluation,
        dept_evaluation,
        p3_individual_weight,
        p3_department_weight,
    ):
        # Dựng phần dữ liệu hệ thống trước để line mới có đủ snapshot KPI cần thiết.
        create_vals = self._prepare_summary_line_system_vals(
            evaluation,
            dept_evaluation,
            p3_individual_weight,
            p3_department_weight,
        )

        # Chỉ line mới mới nhận default manual ban đầu; line cũ sẽ do kế toán tự quản lý.
        create_vals.update(
            self.env["hr.evaluation.3p.summary.line"]._build_standard_amount_vals(
                job=evaluation.job_id,
                employee=evaluation.employee_id,
            )
        )
        return create_vals

    # Gom line hiện tại theo evaluation để aggregate lại mà vẫn nhận diện đúng line cũ.
    def _get_existing_line_match_maps(self):
        self.ensure_one()
        existing_lines_by_evaluation = {}

        # Lập chỉ mục toàn bộ line hiện hữu để tái sử dụng khi cập nhật snapshot mới.
        for line in self.line_ids:
            # Ưu tiên map trực tiếp theo evaluation vì đây là khóa nghiệp vụ chính của line tổng hợp.
            if line.evaluation_id:
                existing_lines_by_evaluation[line.evaluation_id.id] = line

        return existing_lines_by_evaluation

    # Tổng hợp lại summary lines và chốt snapshot export theo bộ trọng số Settings hiện tại.
    def action_aggregate(self):
        settings = self.env["res.config.settings"]
        p3_individual_weight, p3_department_weight = settings.get_p3_summary_weights()

        for summary in self:
            # Lập chỉ mục line cũ theo evaluation để aggregate chỉ recompute trên đúng nguồn KPI.
            existing_lines_by_evaluation = summary._get_existing_line_match_maps()
            used_line_ids = set()

            # Lấy phiếu KPI phòng ban của kỳ hiện tại để làm nguồn fallback chung.
            dept_evaluation = summary._get_department_evaluation()
            evaluations = self.env["hr.performance.evaluation"].search(
                [
                    ("department_id", "=", summary.department_id.id),
                    ("period_id", "=", summary.period_id.id),
                    ("state", "!=", "cancel"),
                ],
                order="employee_id, id",
            )

            for evaluation in evaluations:
                linked_dept_evaluation = (
                    evaluation.dept_evaluation_id or dept_evaluation
                )
                existing_line = existing_lines_by_evaluation.get(evaluation.id)

                # Chỉ recompute các field hệ thống phát sinh từ evaluation; tuyệt đối không
                # truyền các field kế toán nhập tay vào update payload.
                summary_line_vals = summary._prepare_summary_line_system_vals(
                    evaluation,
                    linked_dept_evaluation,
                    p3_individual_weight,
                    p3_department_weight,
                )

                # Update line cũ nếu tìm được, ngược lại tạo line mới với default manual ban đầu.
                if existing_line:
                    # Mỗi evaluation chỉ được gắn với một line trong batch hiện tại để tránh delete nhầm.
                    used_line_ids.add(existing_line.id)
                    # Ghi trực tiếp lên line hiện hữu để aggregate chỉ update field hệ thống
                    # và tránh side effect từ batch command của one2many.
                    existing_line.write(summary_line_vals)
                else:
                    # Tạo line mới riêng biệt để default manual ban đầu chỉ áp dụng cho record mới.
                    new_line = self.env["hr.evaluation.3p.summary.line"].create(
                        {
                            "summary_id": summary.id,
                            **summary._prepare_summary_line_create_vals(
                                evaluation,
                                linked_dept_evaluation,
                                p3_individual_weight,
                                p3_department_weight,
                            ),
                        }
                    )
                    used_line_ids.add(new_line.id)

            # Xóa các line không còn phiếu KPI nguồn trong kỳ hiện tại để summary luôn phản ánh dữ liệu mới nhất.
            stale_lines = summary.line_ids.filtered(
                lambda line: line.id not in used_line_ids
            )
            if stale_lines:
                # Chỉ xóa line không còn evaluation nguồn sau khi toàn bộ update/create đã hoàn tất.
                stale_lines.unlink()

            # Chỉ cần chốt trạng thái summary sau khi line con đã được đồng bộ trực tiếp.
            # summary.write({"state": "done"})
        return True

    # Ghi một dòng nhân viên vào bảng tổng hợp chính cùng toàn bộ công thức Excel động.
    def _write_export_detail_row(
        self,
        sheet,
        row,
        line_number,
        summary_line,
        snapshot,
        p3_individual_weight,
        p3_department_weight,
        cell_center,
        cell_left,
        cell_num,
        cell_percent,
        cell_heso_data,
    ):
        employee = summary_line.employee_id
        comment_text = "\n".join(snapshot.get("comments", []))

        # Ghi thông tin nhân sự cơ bản của nhân viên ở phần đầu dòng.
        sheet.write(row, 3, line_number, cell_center)
        sheet.write(row, 4, employee.identification_id or "", cell_center)
        sheet.write(row, 5, employee.name or "", cell_left)
        sheet.write(row, 6, summary_line.job_id.name or "", cell_left)

        # P1 hiện vẫn là placeholder kế toán nên giữ trống nếu chưa có dữ liệu thực.
        p1_base_salary = summary_line.p1_base_salary or ""
        p1_allowance = summary_line.p1_allowance or ""
        sheet.write(
            row, 7, p1_base_salary, cell_num if p1_base_salary != "" else cell_center
        )
        sheet.write(
            row, 8, p1_allowance, cell_num if p1_allowance != "" else cell_center
        )

        # Đổ các điểm thô của P2.1 vào đúng 5 cột TC cố định của layout Excel.
        p2_1_rows = snapshot.get("p2_1", [])
        p2_1_raw_scores = []
        for offset in range(self.P2_1_EXPORT_COLUMN_COUNT):
            col = 9 + offset
            if offset < len(p2_1_rows):
                raw_score = float(p2_1_rows[offset].get("raw_score", 0.0) or 0.0)
                p2_1_raw_scores.append(raw_score)
                sheet.write(row, col, raw_score, cell_num)
            else:
                sheet.write_blank(row, col, None, cell_center)

        # Ghi công thức hệ số P2.1 theo đúng convention Excel cũ.
        p2_1_start_cell = xl_rowcol_to_cell(row, 9)
        p2_1_end_cell = xl_rowcol_to_cell(row, 13)
        p2_1_formula = f"=SUM({p2_1_start_cell}:{p2_1_end_cell})/100"
        sheet.write_formula(
            row,
            14,
            p2_1_formula,
            cell_heso_data,
            sum(p2_1_raw_scores) / 100.0,
        )

        # Đổ các điểm thô của P2.2 vào đúng 16 cột TC cố định của layout Excel.
        p2_2_rows = snapshot.get("p2_2", [])
        p2_2_raw_scores = []
        for offset in range(self.P2_2_EXPORT_COLUMN_COUNT):
            col = 15 + offset
            if offset < len(p2_2_rows):
                raw_score = float(p2_2_rows[offset].get("raw_score", 0.0) or 0.0)
                p2_2_raw_scores.append(raw_score)
                sheet.write(row, col, raw_score, cell_num)
            else:
                sheet.write_blank(row, col, None, cell_center)

        # Ghi công thức hệ số P2.2 theo đúng convention Excel cũ.
        p2_2_start_cell = xl_rowcol_to_cell(row, 15)
        p2_2_end_cell = xl_rowcol_to_cell(row, 30)
        p2_2_formula = f"=SUM({p2_2_start_cell}:{p2_2_end_cell})/100"
        sheet.write_formula(
            row,
            31,
            p2_2_formula,
            cell_heso_data,
            sum(p2_2_raw_scores) / 100.0,
        )

        # Tính số weight bị wipeout của P3.1.1 và ghi vào ô điểm thưởng bị trừ.
        p3_individual_penalty = float(
            snapshot.get("p3_individual", {}).get("zero_weight_sum", 0.0) or 0.0
        )
        p3_department_penalty = float(
            snapshot.get("p3_department", {}).get("zero_weight_sum", 0.0) or 0.0
        )
        p3_individual_penalty_value = p3_individual_penalty / 100.0
        p3_department_penalty_value = p3_department_penalty / 100.0
        sheet.write(row, 32, p3_individual_penalty_value, cell_percent)
        sheet.write(row, 35, p3_department_penalty_value, cell_percent)

        # Viết công thức điểm sau khi trừ penalty cho P3.1.1 và P3.1.2.
        p3_individual_penalty_cell = xl_rowcol_to_cell(row, 32)
        p3_individual_score_cell = xl_rowcol_to_cell(row, 33)
        p3_department_penalty_cell = xl_rowcol_to_cell(row, 35)
        p3_department_score_cell = xl_rowcol_to_cell(row, 36)
        p3_individual_score_value = 1.0 - p3_individual_penalty_value
        p3_department_score_value = 1.0 - p3_department_penalty_value
        sheet.write_formula(
            row,
            33,
            f"=1-{p3_individual_penalty_cell}",
            cell_percent,
            p3_individual_score_value,
        )
        sheet.write_formula(
            row,
            36,
            f"=1-{p3_department_penalty_cell}",
            cell_percent,
            p3_department_score_value,
        )

        # Viết công thức trọng số quy đổi theo % cấu hình P3 hiện tại.
        p3_individual_weight_cell = xl_rowcol_to_cell(row, 34)
        p3_department_weight_cell = xl_rowcol_to_cell(row, 37)
        p3_individual_weight_value = p3_individual_score_value * (
            p3_individual_weight / 100.0
        )
        p3_department_weight_value = p3_department_score_value * (
            p3_department_weight / 100.0
        )
        sheet.write_formula(
            row,
            34,
            f"=({p3_individual_score_cell}*({p3_individual_weight}/100))",
            cell_percent,
            p3_individual_weight_value,
        )
        sheet.write_formula(
            row,
            37,
            f"=({p3_department_score_cell}*({p3_department_weight}/100))",
            cell_percent,
            p3_department_weight_value,
        )

        # Tổng trọng số là tổng 2 phần đóng góp của KPI cá nhân và KPI phòng ban.
        p3_total_weight_cell = xl_rowcol_to_cell(row, 38)
        p3_total_weight_value = p3_individual_weight_value + p3_department_weight_value
        sheet.write_formula(
            row,
            38,
            f"={p3_individual_weight_cell}+{p3_department_weight_cell}",
            cell_num,
            p3_total_weight_value,
        )

        # Hệ số P3 dùng đúng công thức IF lồng nhau theo rule Excel người dùng cung cấp.
        p3_coefficient_formula = (
            f"=IF({p3_total_weight_cell}>=1,1,"
            f"IF({p3_total_weight_cell}>=0.9,0.8,"
            f"IF({p3_total_weight_cell}>=0.8,0.7,"
            f"IF({p3_total_weight_cell}>=0.7,0.5,0))))"
        )
        sheet.write_formula(
            row,
            39,
            p3_coefficient_formula,
            cell_heso_data,
            self._compute_p3_coefficient_value(p3_total_weight_value),
        )

        # Ghi hệ số doanh thu theo semantics của percentage widget: giá trị nội bộ 1.2 sẽ hiển thị thành 120% trong Excel.
        p3_2_revenue = float(summary_line.p3_2_revenue or 0.0)
        sheet.write(row, 40, p3_2_revenue, cell_percent)

        # Cột đánh giá trên bảng chính dùng chung nội dung manager comment đã chuẩn hóa.
        if comment_text:
            sheet.write(row, 41, comment_text, cell_left)
        else:
            sheet.write_blank(row, 41, None, cell_left)

    # Render bảng III bằng comment manager đã chốt snapshot để nội dung nhất quán với sheet chính.
    def _write_export_comment_section(
        self,
        sheet,
        workbook,
        start_row,
        export_lines,
        snapshots_by_line_id,
        section_format,
    ):
        # Tiêu đề mục III.
        sheet.write(start_row, 3, "III", section_format)
        sheet.write(
            start_row, 4, "ĐÁNH GIÁ & Ý KIẾN CỦA TBP/ NGƯỜI ĐÁNH GIÁ", section_format
        )

        table_header = workbook.add_format(
            {
                "bold": True,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "bg_color": "#D9D9D9",
                "text_wrap": True,
            }
        )
        table_cell_center = workbook.add_format(
            {"align": "center", "valign": "vcenter", "border": 1}
        )
        table_cell_left = workbook.add_format(
            {"align": "left", "valign": "vcenter", "border": 1, "text_wrap": True}
        )

        # Dựng header bảng comment theo đúng layout hiện hữu.
        sheet.set_row(start_row + 1, 30)
        sheet.write(start_row + 1, 3, "STT", table_header)
        sheet.write(start_row + 1, 4, "Mã nhân viên", table_header)
        sheet.merge_range(start_row + 1, 5, start_row + 1, 6, "Họ và tên", table_header)
        sheet.merge_range(
            start_row + 1,
            7,
            start_row + 1,
            31,
            "Đánh giá và ý kiến trưởng bộ phận",
            table_header,
        )

        current_row = start_row + 2
        for index, summary_line in enumerate(export_lines, start=1):
            snapshot = snapshots_by_line_id[summary_line.id]
            comment_text = "\n".join(snapshot.get("comments", []))

            # Mỗi nhân viên chiếm một dòng riêng ở phần comment cuối file.
            sheet.set_row(current_row, 40)
            sheet.write(current_row, 3, index, table_cell_center)
            sheet.write(
                current_row,
                4,
                summary_line.employee_id.identification_id or "",
                table_cell_center,
            )
            sheet.merge_range(
                current_row,
                5,
                current_row,
                6,
                summary_line.employee_id.name or "",
                table_cell_left,
            )
            sheet.merge_range(
                current_row,
                7,
                current_row,
                31,
                comment_text,
                table_cell_left,
            )
            current_row += 1

    # Xuất file Excel bằng snapshot aggregate và ghi công thức động theo rule của file mẫu cũ.
    def action_export_excel(self):
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Kết Quả Đánh Giá 3P")
        settings = self.env["res.config.settings"]
        p3_individual_weight, p3_department_weight = settings.get_p3_summary_weights()
        export_lines = self.line_ids.sorted(
            lambda line: (line.employee_id.name or "", line.id)
        )
        snapshots_by_line_id = {
            line.id: self._load_excel_export_snapshot(line) for line in export_lines
        }

        # ==========================================
        # 1. ĐỊNH DẠNG (FORMATS)
        # ==========================================
        font_name = "Times New Roman"

        title_format = workbook.add_format(
            {
                "font_name": font_name,
                "bold": True,
                "font_size": 16,
                "align": "center",
                "valign": "vcenter",
            }
        )
        doc_info_format = workbook.add_format(
            {
                "font_name": font_name,
                "font_size": 10,
                "align": "right",
                "valign": "top",
                "text_wrap": True,
            }
        )
        section_format = workbook.add_format(
            {"font_name": font_name, "bold": True, "font_size": 11, "valign": "vcenter"}
        )
        label_format = workbook.add_format(
            {"font_name": font_name, "font_size": 11, "valign": "vcenter"}
        )
        note_format = workbook.add_format(
            {
                "font_name": font_name,
                "font_size": 10,
                "italic": True,
                "valign": "vcenter",
                "font_color": "red",
            }
        )

        header_base = {
            "font_name": font_name,
            "bold": True,
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
        }
        header_main = workbook.add_format({**header_base, "bg_color": "#D9D9D9"})

        # --- CÁC MÃ MÀU MỚI CHO HEADER ---
        format_p1 = workbook.add_format(
            {**header_base, "bg_color": "#FAD9D6"}
        )  # Tiêu chí P1
        format_p2 = workbook.add_format(
            {**header_base, "bg_color": "#FEF1CC"}
        )  # Tiêu chí P2
        format_p3 = workbook.add_format(
            {**header_base, "bg_color": "#D2F1DA"}
        )  # Tiêu chí P3

        format_white = workbook.add_format(
            {**header_base, "bg_color": "#FFFFFF"}
        )  # Các cell P2.1, P2.2, P3.1...
        format_gray = workbook.add_format(
            {**header_base, "bg_color": "#D8D8D8"}
        )  # P1.1, P1.2, P3.2 và con của nó
        format_t4_blue = workbook.add_format(
            {**header_base, "bg_color": "#D9F1F3"}
        )  # Từ TC1 đến Hệ số Tổng KPI

        # --- MÃ MÀU CHO CÁC CELL DATA BÊN DƯỚI CỘT HỆ SỐ ---
        # (Dùng chữ trắng để nổi bật trên nền xanh lá đậm #34A853)
        cell_heso_data = workbook.add_format(
            {
                "font_name": font_name,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "bg_color": "#34A853",
                "font_color": "#FFFFFF",
                "bold": True,
            }
        )

        cell_center = workbook.add_format(
            {
                "font_name": font_name,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
            }
        )
        cell_left = workbook.add_format(
            {"font_name": font_name, "align": "left", "valign": "vcenter", "border": 1}
        )
        cell_num = workbook.add_format(
            {
                "font_name": font_name,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
            }
        )
        cell_percent = workbook.add_format(
            {
                "font_name": font_name,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "num_format": "0%",
            }
        )

        # ==========================================
        # 2. CẤU HÌNH CỘT (COLUMN WIDTH)
        # ==========================================
        # Set 3 cột đầu tiên A, B, C độ rộng nhỏ lại làm lề
        sheet.set_column("A:C", 2)

        sheet.set_column("D:D", 5)  # STT (tịnh tiến A -> D)
        sheet.set_column("E:E", 12)  # Mã NV (B -> E)
        sheet.set_column("F:F", 25)  # Họ Tên (C -> F)
        sheet.set_column("G:G", 25)  # Chức vụ (D -> G)
        sheet.set_column("H:I", 30)  # P1.1, P1.2 (E:F -> H:I)
        sheet.set_column("J:O", 7)  # P2.1 (G:L -> J:O)
        sheet.set_column("P:AE", 7)  # P2.2 (M:AB -> P:AE)
        sheet.set_column("AF:AF", 8)  # P2.2 Hệ số (AC -> AF)

        # Cấu hình độ rộng cho toàn bộ các cột con của Tiêu chí P3
        sheet.set_column(
            "AG:AO", 18
        )  # Từ cột P3.1.1 cho tới Hệ số của P3.2 (AD:AL -> AG:AO)

        # Tăng width cho cột "Đánh giá..." (Cột AM -> AP)
        sheet.set_column("AP:AP", 20)

        # Đóng băng dòng header (tịnh tiến thêm 3 cột vào tham số thứ 2)
        sheet.freeze_panes(0, 7)

        # ==========================================
        # 3. PHẦN THÔNG TIN CHUNG (HEADER BÁO CÁO)
        # ==========================================
        # SỬA Ở ĐÂY: Merge từ D2 đến AM3 để dành không gian bên phải cho doc_info
        sheet.merge_range("D2:AM3", "BẢNG ĐÁNH GIÁ THEO PHƯƠNG PHÁP 3P", title_format)

        # Dời doc_info sang lề phải cùng của bảng (AN2 đến AP4).
        today_label = fields.Date.context_today(self).strftime("%d/%m/%Y")
        doc_info = f"No. {self.name or ''}\nDate: {today_label}\nPage: 01/01"
        sheet.merge_range("AN2:AP4", doc_info, doc_info_format)

        sheet.write("D6", "I", section_format)
        sheet.write("E6", "THÔNG TIN CHUNG", section_format)
        sheet.write("F7", "Bộ phận được đánh giá:", label_format)
        sheet.write("G7", self.department_id.display_name or "", label_format)
        sheet.write("F8", "Tháng đánh giá:", label_format)
        sheet.write("G8", self._get_export_period_label(), label_format)
        sheet.write("F9", "Người đánh giá:", label_format)
        sheet.write("G9", self.department_id.manager_id.name or "", label_format)
        sheet.write("F10", "Tiêu chí đánh giá:", label_format)
        sheet.write("G10", "Phương pháp 3P với trọng số", label_format)

        note_text = "Chú ý: đây là bảng tổng hợp Lương 3P của nhân viên phòng ban. Cuối mỗi tháng, trưởng bộ phận sẽ đánh giá nhân viên các tiêu chí P2.1; P2.2; P3.1.1; P3.1.2 tại các sheet tương ứng"
        sheet.merge_range("D11:P11", note_text, note_format)

        sheet.write("D12", "II", section_format)
        sheet.write("E12", "BẢNG TỔNG HỢP KẾT QUẢ", section_format)

        # ==========================================
        # 4. VẼ BẢNG HEADER 4 TẦNG (ROWS 14, 15, 16, 17)
        # ==========================================
        row_h1 = 13  # Excel Row 14 (Tầng 1 - Nhóm Tiêu chí chính)
        row_h2 = 14  # Excel Row 15 (Tầng 2 - Thành phần P)
        row_h3 = 15  # Excel Row 16 (Tầng 3 - Tên KPI / Chỉ số)
        row_h4 = 16  # Excel Row 17 (Tầng 4 - Chi tiết thành phần con)

        sheet.set_row(row_h1, 40)
        sheet.set_row(row_h2, 30)
        sheet.set_row(row_h3, 40)
        sheet.set_row(row_h4, 40)

        # Cột chung kéo dài dọc qua cả 4 tầng header (tịnh tiến +3 index)
        sheet.merge_range(row_h1, 3, row_h4, 3, "STT", header_main)
        sheet.merge_range(row_h1, 4, row_h4, 4, "Mã nhân viên", header_main)
        sheet.merge_range(row_h1, 5, row_h4, 5, "Họ và tên", header_main)
        sheet.merge_range(row_h1, 6, row_h4, 6, "Chức vụ", header_main)

        # --- TẦNG 1 ---
        sheet.merge_range(
            row_h1, 7, row_h1, 8, "TIÊU CHÍ P1\n(lương theo vị trí)", format_p1
        )
        sheet.merge_range(
            row_h1, 9, row_h1, 31, "TIÊU CHÍ P2\n(lương theo năng lực)", format_p2
        )
        sheet.merge_range(
            row_h1,
            32,
            row_h1,
            40,
            "TIÊU CHÍ P3\n(lương theo hiệu quả công việc)",
            format_p3,
        )
        sheet.merge_range(row_h1, 41, row_h4, 41, "Đánh giá", header_main)

        # --- TIÊU CHÍ P1 ---
        sheet.merge_range(row_h2, 7, row_h3, 7, "P1.1\n(lương cơ bản)", format_gray)
        sheet.write(row_h4, 7, "Mức lương", format_gray)

        sheet.merge_range(
            row_h2,
            8,
            row_h3,
            8,
            "P1.2\n(lương chuyên môn, chức vụ)\nĐánh giá theo định kỳ",
            format_gray,
        )
        sheet.write(row_h4, 8, "Mức lương", format_gray)

        # --- TIÊU CHÍ P2 ---
        sheet.merge_range(
            row_h2,
            9,
            row_h3,
            14,
            "P2.1\n(lương theo kiến thức công việc)\nĐánh giá theo định kỳ",
            format_white,
        )
        for i, col in enumerate(range(9, 14)):
            sheet.write(row_h4, col, f"TC{i + 1}", format_t4_blue)
        sheet.write(row_h4, 14, "Hệ số", format_t4_blue)

        sheet.merge_range(
            row_h2,
            15,
            row_h3,
            31,
            "P2.2\n(lương theo kỹ năng, kinh nghiệm)\nĐánh giá theo định kỳ",
            format_white,
        )
        for i, col in enumerate(range(15, 31)):
            sheet.write(row_h4, col, f"TC{i + 1}", format_t4_blue)
        sheet.write(row_h4, 31, "Hệ số", format_t4_blue)

        # --- TIÊU CHÍ P3 ---
        # Tầng 2
        sheet.merge_range(row_h2, 32, row_h2, 39, "P3.1", format_white)
        sheet.merge_range(row_h2, 40, row_h3, 40, "P3.2\n(theo doanh thu)", format_gray)
        sheet.write(row_h4, 40, "Hệ số", format_gray)

        # Tầng 3
        sheet.merge_range(
            row_h3, 32, row_h3, 34, "P3.1.1\nKPI CÁ NHÂN (1)", format_white
        )
        sheet.merge_range(
            row_h3, 35, row_h3, 37, "P3.1.2\nKPI PHÒNG BAN (2)", format_white
        )
        sheet.merge_range(
            row_h3, 38, row_h3, 39, "KPI NHÂN VIÊN=\n(1) X (2)", format_white
        )

        # Tầng 4
        # Dưới P3.1.1
        sheet.write(row_h4, 32, "Điểm thưởng\nbị trừ", format_t4_blue)
        sheet.write(row_h4, 33, "Điểm", format_t4_blue)
        sheet.write(row_h4, 34, "Trọng số", format_t4_blue)
        # Dưới P3.1.2
        sheet.write(row_h4, 35, "Điểm thưởng\nbị trừ", format_t4_blue)
        sheet.write(row_h4, 36, "Điểm", format_t4_blue)
        sheet.write(row_h4, 37, "Trọng số", format_t4_blue)
        # Dưới Tổng KPI (P3.1)
        sheet.write(row_h4, 38, "Tổng trọng số", format_t4_blue)
        sheet.write(row_h4, 39, "Hệ số", format_t4_blue)

        row = 17
        for index, summary_line in enumerate(export_lines, start=1):
            snapshot = snapshots_by_line_id[summary_line.id]

            # Ghi một dòng tổng hợp hoàn chỉnh từ snapshot thật của nhân viên.
            self._write_export_detail_row(
                sheet,
                row,
                index,
                summary_line,
                snapshot,
                p3_individual_weight,
                p3_department_weight,
                cell_center,
                cell_left,
                cell_num,
                cell_percent,
                cell_heso_data,
            )
            row += 1

        start_row = row + 2

        # Ghi phần III bằng comment manager đã chốt snapshot ở lần aggregate gần nhất.
        self._write_export_comment_section(
            sheet,
            workbook,
            start_row,
            export_lines,
            snapshots_by_line_id,
            section_format,
        )

        workbook.close()

        # Phần code return base64/action url lưu file bạn tiếp tục giữ theo logic hiện tại
        output.seek(0)
        file_data = output.read()
        output.close()

        # Tạo file đính kèm để tải xuống
        attachment = self.env["ir.attachment"].create(
            {
                "name": self._build_export_file_name(),
                "type": "binary",
                "datas": base64.b64encode(file_data),
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }


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
    employee_code = fields.Char(
        related="employee_id.identification_id",
        store=True,
        readonly=True,
    )
    job_id = fields.Many2one(
        "hr.job",
        ondelete="set null",
    )
    department_id = fields.Many2one(
        "hr.department",
        related="summary_id.department_id",
        store=True,
        readonly=True,
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        related="summary_id.period_id",
        store=True,
        readonly=True,
    )
    evaluation_id = fields.Many2one(
        "hr.performance.evaluation",
        ondelete="set null",
    )
    dept_evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation",
        ondelete="set null",
    )
    summary_state = fields.Selection(
        related="summary_id.state",
        store=True,
        readonly=True,
    )
    can_edit_manual_inputs = fields.Boolean(
        compute="_compute_can_edit_manual_inputs",
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
    p2_1_base_amount = fields.Float(
        string="P2.1 - Standard Amount",
        digits=(16, 0),
        default=0.0,
        help="Reusable standard amount copied from the job position and editable by accounting.",
    )
    p2_1_score_raw = fields.Float(
        string="P2.1",
        help="Weighted P2.1 score aggregated from the employee evaluation.",
    )
    p2_2_base_amount = fields.Float(
        string="P2.2 - Standard Amount",
        digits=(16, 0),
        default=0.0,
        help="Reusable standard amount copied from the job position and editable by accounting.",
    )
    p2_2_score_raw = fields.Float(
        string="P2.2",
        help="Weighted P2.2 score aggregated from the employee evaluation.",
    )
    p3_individual_score = fields.Float(
        string="P3.1.1",
        help="Employee KPI score used as the personal component of P3.1 before coefficient conversion.",
    )
    p3_department_score = fields.Float(
        string="P3.1.2",
        help="Department KPI score used as the team component of P3.1 before coefficient conversion.",
    )
    p3_1_base_amount = fields.Float(
        string="P3.1 - Standard Amount",
        digits=(16, 0),
        default=0.0,
        help="Reusable standard amount copied from the job position and editable by accounting.",
    )
    p3_1_score = fields.Float(  
        string="P3.1",
        default=0.0,
        help="""P3.1 Coefficient calculated based on Total Weight (Sum of P3.1.1 Individual KPI and P3.1.2 Department KPI):
            - Total Weight >= 100%: 1.0
            - Total Weight >= 90%: 0.8
            - Total Weight >= 80%: 0.7
            - Total Weight >= 70%: 0.5
            - Total Weight < 70%: 0.0""",
    )
    p3_2_base_amount = fields.Float(
        string="P3.2 - Standard Amount",
        digits=(16, 0),
        default=0.0,
        help="Reusable standard amount copied from the job position and editable by accounting.",
    )
    p3_2_revenue = fields.Float(
        string="P3.2",
        digits=(16, 4),
        default=0.0,
        help="Revenue ratio entered with the percentage widget. For example, enter 90% and Odoo stores 0.9 internally.",
    )
    # Display-only revenue ratio used on the summary list to avoid client-side cache conflicts.
    p3_2_revenue_list = fields.Float(
        string="P3.2",
        digits=(16, 4),
        compute="_compute_p3_2_revenue_list",
    )
    excel_export_snapshot = fields.Text(
        string="Excel Export Snapshot",
        help="Stored JSON snapshot used by the Excel export to keep historical rows stable.",
    )

    # Dựng field mirror chỉ để list view hiển thị hệ số doanh thu mà không bind trực tiếp vào field edit thật.
    @api.depends("p3_2_revenue")
    def _compute_p3_2_revenue_list(self):
        for line in self:
            # Sao chép nguyên giá trị revenue hiện tại sang field hiển thị để list view luôn đọc cùng một nguồn dữ liệu.
            line.p3_2_revenue_list = line.p3_2_revenue

    # Trả về snapshot các field nhập tay để aggregate có thể preserve ổn định qua các lần rebuild line.
    def _get_manual_input_vals(self):
        self.ensure_one()
        return {
            "p1_base_salary": self.p1_base_salary,
            "p1_allowance": self.p1_allowance,
            "p2_1_base_amount": self.p2_1_base_amount,
            "p2_2_base_amount": self.p2_2_base_amount,
            "p3_1_base_amount": self.p3_1_base_amount,
            "p3_2_base_amount": self.p3_2_base_amount,
            "p3_2_revenue": self.p3_2_revenue,
        }

    # Xác định job nguồn ưu tiên theo job truyền vào, sau đó rơi về job trên nhân viên để tái sử dụng định mức.
    @api.model
    def _resolve_standard_amount_job(self, employee=False, job=False):
        # Nếu caller đã truyền job rõ ràng thì dùng ngay để tránh lookup dư thừa.
        if job:
            return job

        # Khi job trống nhưng đã có nhân viên thì tái sử dụng job mặc định của nhân viên.
        if employee and employee.job_id:
            return employee.job_id

        # Không tìm được nguồn thì trả record rỗng để caller tự fallback về 0.
        return self.env["hr.job"]

    # Dựng bộ giá trị định mức chuẩn để tái dùng cho onchange, create và aggregate.
    @api.model
    def _build_standard_amount_vals(self, employee=False, job=False):
        # Chuẩn hóa lại job nguồn để mọi luồng đều dùng cùng một logic lấy mặc định.
        resolved_job = self._resolve_standard_amount_job(employee=employee, job=job)

        # Trả về dict cố định để caller có thể merge trực tiếp vào vals/create/update.
        return {
            "p1_base_salary": resolved_job.x_p11_standard_amount or 0.0,
            "p1_allowance": resolved_job.x_p12_standard_amount or 0.0,
            "p2_1_base_amount": resolved_job.x_p21_standard_amount or 0.0,
            "p2_2_base_amount": resolved_job.x_p22_standard_amount or 0.0,
            "p3_1_base_amount": resolved_job.x_p31_standard_amount or 0.0,
            "p3_2_base_amount": resolved_job.x_p32_standard_amount or 0.0,
        }

    # Xác định người dùng hiện tại có được sửa input tay và dùng nút refresh hay không.
    def _compute_can_edit_manual_inputs(self):
        # Tính một lần theo user hiện tại để toàn bộ dòng dùng chung cùng rule quyền.
        can_edit = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_accounting"
        )
        for line in self:
            # Gán cờ vào từng dòng để view có thể readonly/invisible theo đúng user hiện tại.
            line.can_edit_manual_inputs = can_edit

    # Lấy job nguồn thực tế của dòng để các nút refresh luôn dùng đúng chuẩn dữ liệu từ hr.job.
    def _get_standard_amount_source_job(self):
        self.ensure_one()

        # Ưu tiên job đang gắn trực tiếp trên dòng vì đây là nguồn business gần nhất.
        source_job = self._resolve_standard_amount_job(
            employee=self.employee_id,
            job=self.job_id,
        )
        if source_job:
            return source_job

        # Chặn thao tác refresh khi chưa xác định được vị trí nguồn để tránh ghi sai dữ liệu.
        raise UserError(
            _(
                "Please set a job position on the line or employee before refreshing standard amounts."
            )
        )

    # Sao chép lại một field định mức từ hr.job sang field nhập liệu tương ứng trên summary line.
    def _refetch_standard_amount_field(self, target_field_name, source_field_name):
        self.ensure_one()

        # Xác định job nguồn trước khi đọc standard amount để luôn bám đúng master data.
        source_job = self._get_standard_amount_source_job()

        # Chuẩn hóa lại job trên dòng nếu trước đây đang thiếu nhưng đã xác định được từ nhân viên.
        vals = {
            target_field_name: float(getattr(source_job, source_field_name, 0.0) or 0.0)
        }
        if not self.job_id:
            vals["job_id"] = source_job.id

        # Đồng bộ lại giá trị thủ công từ field cấu hình chuẩn của hr.job.
        self.write(vals)
        return True

    # Refresh lại P1.1 từ standard amount của hr.job.
    def action_refetch_p1_base_salary(self):
        for line in self:
            # Mỗi dòng tự refresh lại field P1.1 từ job nguồn tương ứng của chính nó.
            line._refetch_standard_amount_field(
                "p1_base_salary",
                "x_p11_standard_amount",
            )
        return True

    # Refresh lại P1.2 từ standard amount của hr.job.
    def action_refetch_p1_allowance(self):
        for line in self:
            # Mỗi dòng tự refresh lại field P1.2 từ job nguồn tương ứng của chính nó.
            line._refetch_standard_amount_field(
                "p1_allowance",
                "x_p12_standard_amount",
            )
        return True

    # Refresh lại P2.1 từ standard amount của hr.job.
    def action_refetch_p2_1_base_amount(self):
        for line in self:
            # Mỗi dòng tự refresh lại field P2.1 từ job nguồn tương ứng của chính nó.
            line._refetch_standard_amount_field(
                "p2_1_base_amount",
                "x_p21_standard_amount",
            )
        return True

    # Refresh lại P2.2 từ standard amount của hr.job.
    def action_refetch_p2_2_base_amount(self):
        for line in self:
            # Mỗi dòng tự refresh lại field P2.2 từ job nguồn tương ứng của chính nó.
            line._refetch_standard_amount_field(
                "p2_2_base_amount",
                "x_p22_standard_amount",
            )
        return True

    # Refresh lại P3.1 từ standard amount của hr.job.
    def action_refetch_p3_1_base_amount(self):
        for line in self:
            # Mỗi dòng tự refresh lại field P3.1 từ job nguồn tương ứng của chính nó.
            line._refetch_standard_amount_field(
                "p3_1_base_amount",
                "x_p31_standard_amount",
            )
        return True

    # Refresh lại P3.2 từ standard amount của hr.job.
    def action_refetch_p3_2_base_amount(self):
        for line in self:
            # Mỗi dòng tự refresh lại field P3.2 từ job nguồn tương ứng của chính nó.
            line._refetch_standard_amount_field(
                "p3_2_base_amount",
                "x_p32_standard_amount",
            )
        return True

    # Đồng bộ job nguồn và 6 định mức chuẩn khi người dùng đổi nhân viên hoặc vị trí trên giao diện.
    @api.onchange("employee_id", "job_id")
    def _onchange_standard_amount_source(self):
        for line in self:
            # Tìm job nguồn ưu tiên theo vị trí đang chọn, nếu thiếu thì lấy từ nhân viên.
            resolved_job = line._resolve_standard_amount_job(
                employee=line.employee_id,
                job=line.job_id,
            )

            # Tự điền lại job nếu nhân viên đã có vị trí nhưng dòng chưa gắn để người dùng không phải chọn 2 lần.
            if resolved_job and not line.job_id:
                line.job_id = resolved_job

            # Đồng bộ toàn bộ bộ định mức để kế toán có thể chỉnh tiếp từ giá trị mặc định mới nhất.
            for field_name, value in line._build_standard_amount_vals(
                employee=line.employee_id,
                job=resolved_job,
            ).items():
                line[field_name] = value

    # Bổ sung định mức mặc định từ job cho các luồng tạo record không đi qua form onchange.
    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        tracked_fields = {
            "p1_base_salary",
            "p1_allowance",
            "p2_1_base_amount",
            "p2_2_base_amount",
            "p3_1_base_amount",
            "p3_2_base_amount",
        }

        for vals in vals_list:
            # Sao chép vals để tránh mutate trực tiếp dữ liệu đầu vào từ caller.
            prepared_vals = dict(vals)
            employee = (
                self.env["hr.employee"].browse(prepared_vals["employee_id"])
                if prepared_vals.get("employee_id")
                else self.env["hr.employee"]
            )
            job = (
                self.env["hr.job"].browse(prepared_vals["job_id"])
                if prepared_vals.get("job_id")
                else self.env["hr.job"]
            )

            # Tự gắn job từ nhân viên nếu caller chưa truyền nhưng hồ sơ nhân viên đã có vị trí.
            resolved_job = self._resolve_standard_amount_job(employee=employee, job=job)
            if resolved_job and not prepared_vals.get("job_id"):
                prepared_vals["job_id"] = resolved_job.id

            # Chỉ điền những field còn thiếu để không đè dữ liệu tay hoặc dữ liệu aggregate đã preserve.
            standard_amount_vals = self._build_standard_amount_vals(
                employee=employee,
                job=resolved_job,
            )
            for field_name in tracked_fields:
                if field_name not in prepared_vals:
                    prepared_vals[field_name] = standard_amount_vals[field_name]

            prepared_vals_list.append(prepared_vals)

        # Gọi super sau khi đã chuẩn hóa xong để ORM lưu record với bộ định mức đầy đủ.
        lines = super().create(prepared_vals_list)
        lines._sync_linked_evaluation_result_fields()
        return lines

    # Đồng bộ lại score kết quả và level của các phiếu KPI cá nhân bị ảnh hưởng bởi line summary vừa đổi.
    def _sync_linked_evaluation_result_fields(self):
        evaluations = self.mapped("evaluation_id")
        if not evaluations:
            return

        # Recompute score nguồn trước để level và badge luôn đọc đúng snapshot 3P mới nhất.
        evaluations._compute_result_score()
        evaluations._compute_performance_level()
        evaluations._compute_performance_badge_class()

    # Ghi line summary rồi đồng bộ lại kết quả trên phiếu KPI cá nhân liên quan.
    def write(self, vals):
        evaluations = self.mapped("evaluation_id")
        result = super().write(vals)
        affected_evaluations = evaluations | self.mapped("evaluation_id")
        if affected_evaluations:
            affected_evaluations._compute_result_score()
            affected_evaluations._compute_performance_level()
            affected_evaluations._compute_performance_badge_class()
        return result

    # Xóa line summary và làm mới score kết quả của các phiếu từng liên kết với line đó.
    def unlink(self):
        evaluations = self.mapped("evaluation_id")
        result = super().unlink()
        if evaluations:
            evaluations._compute_result_score()
            evaluations._compute_performance_level()
            evaluations._compute_performance_badge_class()
        return result
