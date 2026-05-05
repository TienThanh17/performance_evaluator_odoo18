/** @odoo-module **/

/**
 * Performance Dashboard Form – js_class="performance_dashboard_form"
 *
 * Kế thừa FormRenderer của Odoo 18 (OWL).
 * Thay thế toàn bộ nội dung view bằng KPI dashboard riêng,
 * tính toán các chỉ số từ dữ liệu evaluation_ids có trong record.
 */

import { registry } from "@web/core/registry";
import { FormRenderer } from "@web/views/form/form_renderer";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";

// ────────────────────────────────────────────────────────────────
// Helper: format Date object → "Month Year" (e.g. "April 2026")
// ────────────────────────────────────────────────────────────────
function formatMonthYear(dateStr) {
    if (!dateStr) return "";
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

// ────────────────────────────────────────────────────────────────
// Helper: convert Odoo 18 date value → "YYYY-MM-DD" for input[type=date]
// Odoo 18 OWL passes Date fields as Luxon DateTime objects,
// not plain strings. input[type="date"] requires "YYYY-MM-DD".
// ────────────────────────────────────────────────────────────────
function toInputDate(val) {
    if (!val) return "";
    // Luxon DateTime (has .toISODate method)
    if (typeof val === "object" && typeof val.toISODate === "function") {
        return val.toISODate(); // returns "YYYY-MM-DD"
    }
    // JS Date object
    if (val instanceof Date) {
        const y = val.getFullYear();
        const m = String(val.getMonth() + 1).padStart(2, "0");
        const d = String(val.getDate()).padStart(2, "0");
        return `${y}-${m}-${d}`;
    }
    // Plain string: ensure it's YYYY-MM-DD (trim time part if present)
    const str = String(val);
    return str.length >= 10 ? str.slice(0, 10) : str;
}

// ────────────────────────────────────────────────────────────────
// Helper: get initials from name
// ────────────────────────────────────────────────────────────────
function getInitials(name) {
    if (!name) return "?";
    const parts = name.trim().split(" ");
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

// ════════════════════════════════════════════════════════════════
// Custom FormRenderer – renders the dashboard template instead
// ════════════════════════════════════════════════════════════════
export class PerformanceDashboardRenderer extends FormRenderer {
    static template = "custom_adecsol_hr_performance_evaluator.PerformanceDashboard";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");

        // Dữ liệu dashboard được reactive qua useState
        this.state = useState({
            departmentName: "",
            periodLabel: "",
            totalEmployees: 0,
            avgScore: "0.0",
            passRate: "0",
            evaluations: [],
            // Evaluation Configuration fields
            period: "",
            startDate: "",
            endDate: "",
            deadline: "",
            active: true,
        });

        onWillStart(async () => {
            await this._loadDashboardData();
        });

        onWillUpdateProps(async () => {
            await this._loadDashboardData();
        });
    }

    // ──────────────────────────────────────────────────────
    // Load & tính toán dữ liệu từ record hr.performance.report
    // ──────────────────────────────────────────────────────
    async _loadDashboardData() {
        const record = this.props.record;
        const data = record.data;
        console.log('this.props.record.data', data)

        // Tên phòng ban
        this.state.departmentName = data.department_name;

        // Nhãn kỳ đánh giá (dùng start_date - "April 2026")
        this.state.periodLabel = data.start_date
            ? formatMonthYear(data.start_date)
            : "";

        // Evaluation Configuration state
        this.state.period = data.period || "monthly";
        this.state.startDate = toInputDate(data.start_date);
        this.state.endDate   = toInputDate(data.end_date);
        this.state.deadline  = toInputDate(data.deadline);
        this.state.active = data.active !== undefined ? data.active : true;

        // Lấy danh sách evaluation_ids từ record.
        // Trong Odoo 18 OWL, One2many trả về StaticList có property .records[],
        // mỗi phần tử có .resId là ID thực của record.
        const evalList = data.evaluation_ids;
        let evalIds = [];
        if (evalList && typeof evalList === "object" && evalList.records) {
            // Đây là StaticList của Odoo 18
            evalIds = evalList.records
                .map((r) => r.resId)
                .filter(Boolean);
        } else if (Array.isArray(evalList)) {
            // Fallback cho trường hợp data đã là array
            evalIds = evalList.map((r) =>
                typeof r === "object" ? (r.id || r.resId) : r
            ).filter(Boolean);
        }

        if (evalIds.length === 0) {
            this.state.totalEmployees = 0;
            this.state.avgScore = "0.0";
            this.state.passRate = "0";
            this.state.evaluations = [];
            return;
        }

        // Đọc chi tiết evaluation records
        const evaluations = await this.orm.read(
            "hr.performance.evaluation",
            evalIds,
            [
                "employee_id",
                "job_id",
                "performance_score",
                "performance_level",
                "state",
            ]
        );

        // Lấy thêm barcode (Employee ID) từ hr.employee
        // Dùng barcode thay vì registration_number (không có trong Odoo chuẩn)
        const empIds = evaluations
            .filter((e) => e.employee_id)
            .map((e) => e.employee_id[0]);

        let empMap = {};
        if (empIds.length) {
            try {
                const empRecs = await this.orm.read("hr.employee", empIds, [
                    "barcode",
                ]);
                empRecs.forEach((e) => {
                    empMap[e.id] = e.barcode || `EMP-${e.id}`;
                });
            } catch (_e) {
                // Nếu barcode cũng không có, fallback về EMP-{id}
                empIds.forEach((id) => { empMap[id] = `EMP-${id}`; });
            }
        }

        // Gắn employee_id vào mỗi evaluation
        evaluations.forEach((ev) => {
            ev.employee_registration_number = ev.employee_id
                ? empMap[ev.employee_id[0]] || `EMP-${ev.employee_id[0]}`
                : "-";
        });

        // ── Tính KPI ──
        const total = evaluations.length;
        const scoreSum = evaluations.reduce(
            (acc, ev) => acc + (ev.performance_score || 0),
            0
        );
        const passCount = evaluations.filter(
            (ev) =>
                ev.performance_level === "pass" ||
                ev.performance_level === "excellent"
        ).length;

        this.state.totalEmployees = total;
        this.state.avgScore = total
            ? (scoreSum / total).toFixed(2)
            : "0.0";
        this.state.passRate = total
            ? Math.round((passCount / total) * 100).toString()
            : "0";
        this.state.evaluations = evaluations;
    }

    // ──────────────────────────────────────────────────────
    // Helpers: lấy evalIds từ record hiện tại
    // ──────────────────────────────────────────────────────
    _getEvalIds() {
        const evalList = this.props.record.data.evaluation_ids;
        if (evalList && typeof evalList === "object" && evalList.records) {
            return evalList.records.map((r) => r.resId).filter(Boolean);
        }
        if (Array.isArray(evalList)) {
            return evalList.map((r) => (typeof r === "object" ? r.id || r.resId : r)).filter(Boolean);
        }
        return [];
    }

    // ──────────────────────────────────────────────────────
    // Helper: write config field to report + evaluation_ids
    // ──────────────────────────────────────────────────────
    async _writeConfigField(reportVals, evalVals) {
        const record = this.props.record;
        const reportId = record.resId;
        if (!reportId) return;

        // Ghi vào hr.performance.report
        await this.orm.write("hr.performance.report", [reportId], reportVals);

        // Ghi vào tất cả hr.performance.evaluation liên quan
        if (evalVals && Object.keys(evalVals).length) {
            const evalIds = this._getEvalIds();
            if (evalIds.length) {
                await this.orm.write("hr.performance.evaluation", evalIds, evalVals);
            }
        }

        // Reload lại record để UI đồng bộ
        await record.load();
        await this._loadDashboardData();
    }

    // ──────────────────────────────────────────────────────
    // Event handlers cho Evaluation Configuration
    // ──────────────────────────────────────────────────────
    async onPeriodChange(ev) {
        const value = ev.target.value;
        this.state.period = value;
        this.state.periodLabel = value;
        await this._writeConfigField(
            { period: value },
            { period: value }
        );
    }

    async onStartDateChange(ev) {
        const value = ev.target.value;
        this.state.startDate = value;
        if (value) {
            this.state.periodLabel = formatMonthYear(value);
        }
        await this._writeConfigField(
            { start_date: value || false },
            { start_date: value || false }
        );
    }

    async onEndDateChange(ev) {
        const value = ev.target.value;
        this.state.endDate = value;
        await this._writeConfigField(
            { end_date: value || false },
            { end_date: value || false }
        );
    }

    async onDeadlineChange(ev) {
        const value = ev.target.value;
        this.state.deadline = value;
        await this._writeConfigField(
            { deadline: value || false },
            { deadline: value || false }
        );
    }

    async onActiveChange(ev) {
        const value = ev.target.checked;
        this.state.active = value;
        await this._writeConfigField(
            { active: value },
            { active: value }
        );
    }

    // ──────────────────────────────────────────────────────
    // Export Excel Report
    // ──────────────────────────────────────────────────────
    async exportExcelReport() {
        const record = this.props.record;
        const reportId = record.resId;
        if (!reportId) return;

        const action = await this.orm.call(
            "hr.performance.report",
            "action_export_excel_report",
            [reportId]
        );

        if (action) {
            this.actionService.doAction(action);
        }
    }

    // ──────────────────────────────────────────────────────
    // Mở form record hr.performance.evaluation theo id
    // ──────────────────────────────────────────────────────
    openEvaluation(evalId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.performance.evaluation",
            res_id: evalId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ──────────────────────────────────────────────────────
    // "View All" → mở danh sách evaluation của report này
    // ──────────────────────────────────────────────────────
    viewAll() {
        const record = this.props.record;
        const evalIds = (record.data.evaluation_ids || []).map((r) =>
            typeof r === "object" ? r.id : r
        );
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.performance.evaluation",
            name: "Team Evaluations",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["id", "in", evalIds]],
            target: "current",
        });
    }
}

// ════════════════════════════════════════════════════════════════
// Đăng ký js_class vào view registry
// ════════════════════════════════════════════════════════════════
registry.category("views").add("performance_dashboard_form", {
    ...formView,
    Renderer: PerformanceDashboardRenderer,
    // Giữ nguyên Controller gốc để save/discard/breadcrumb hoạt động
    Controller: FormController,
});
