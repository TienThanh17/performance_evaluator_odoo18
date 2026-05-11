/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FormRenderer } from "@web/views/form/form_renderer";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { useService } from "@web/core/utils/hooks";
import { useState, onWillStart, onWillUpdateProps, useEffect, useRef } from "@odoo/owl";

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────
const C_BLUE   = "#3b5bdb";
const C_GREEN  = "#22c55e";
const C_AMBER  = "#f59e0b";
const C_RED    = "#ef4444";
const C_TEAL   = "#14b8a6";
const C_PURPLE = "#8b5cf6";

const POINT_COLORS = [
    "#3b5bdb", "#22c55e", "#f59e0b", "#ef4444",
    "#14b8a6", "#8b5cf6", "#ec4899", "#06b6d4",
    "#84cc16", "#f97316",
];

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function formatMonthYear(dateStr) {
    if (!dateStr) return "";
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

function toInputDate(val) {
    if (!val) return "";
    if (typeof val === "object" && typeof val.toISODate === "function") return val.toISODate();
    if (val instanceof Date) {
        const y = val.getFullYear();
        const m = String(val.getMonth() + 1).padStart(2, "0");
        const d = String(val.getDate()).padStart(2, "0");
        return `${y}-${m}-${d}`;
    }
    const str = String(val);
    return str.length >= 10 ? str.slice(0, 10) : str;
}

// ─────────────────────────────────────────────────────────────────────────────
// Base chart option factories
// ─────────────────────────────────────────────────────────────────────────────
function baseBarOpts(yLabel = "") {
    return {
        responsive: true,
        plugins: { legend: { display: true, position: "top" } },
        scales: {
            x: { grid: { display: false }, ticks: { font: { size: 11 } } },
            y: {
                beginAtZero: true,
                title: { display: !!yLabel, text: yLabel, font: { size: 11 } },
                grid: { color: "rgba(0,0,0,0.05)" },
                ticks: { font: { size: 10 } },
            },
        },
    };
}

function baseLineOpts(yLabel = "") {
    return {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
            x: { grid: { display: false }, ticks: { font: { size: 11 } } },
            y: {
                beginAtZero: true,
                title: { display: !!yLabel, text: yLabel, font: { size: 11 } },
                grid: { color: "rgba(0,0,0,0.05)" },
                ticks: { stepSize: 1, font: { size: 10 } },
            },
        },
    };
}

// ═════════════════════════════════════════════════════════════════════════════
// PerformanceDashboardRenderer
// ═════════════════════════════════════════════════════════════════════════════
export class PerformanceDashboardRenderer extends FormRenderer {
    static template = "custom_adecsol_hr_performance_evaluator.PerformanceDashboard";

    setup() {
        super.setup();
        this.orm           = useService("orm");
        this.actionService = useService("action");

        // Chart canvas refs
        this.refChartA = useRef("chartA");
        this.refChartB = useRef("chartB");
        this.refChartC = useRef("chartC");
        // qualitative refs tạo động khi render

        this._charts    = {};
        this._chartJsLoaded = false;

        this.state = useState({
            departmentName : "",
            periodLabel    : "",
            totalEmployees : 0,
            avgScore       : "0.0",
            passRate       : "0",
            evaluations    : [],
            period         : "",
            startDate      : "",
            endDate        : "",
            deadline       : "",
            active         : true,
            chartData      : null,   // data từ get_report_dashboard_data
        });

        onWillStart(async () => {
            await this._loadChartJs();
            await this._loadDashboardData();
        });

        onWillUpdateProps(async () => {
            await this._loadDashboardData();
        });

        useEffect(
            () => {
                if (this.state.chartData) {
                    this._renderAllCharts();
                }
            },
            () => [this.state.chartData]
        );
    }

    // ── Chart.js loader ───────────────────────────────────────────────────────
    async _loadChartJs() {
        if (window.Chart) return;
        await new Promise((resolve, reject) => {
            const s = document.createElement("script");
            s.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js";
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    }

    // ── Data loader ───────────────────────────────────────────────────────────
    async _loadDashboardData() {
        const record = this.props.record;
        const data   = record.data;

        this.state.departmentName = data.department_name || "";
        this.state.periodLabel    = data.start_date ? formatMonthYear(data.start_date) : "";
        this.state.period         = data.period    || "monthly";
        this.state.startDate      = toInputDate(data.start_date);
        this.state.endDate        = toInputDate(data.end_date);
        this.state.deadline       = toInputDate(data.deadline);
        this.state.active         = data.active !== undefined ? data.active : true;

        // Lấy evalIds từ One2many StaticList
        const evalList = data.evaluation_ids;
        let evalIds = [];
        if (evalList?.records) {
            evalIds = evalList.records.map((r) => r.resId).filter(Boolean);
        } else if (Array.isArray(evalList)) {
            evalIds = evalList.map((r) => (typeof r === "object" ? r.id || r.resId : r)).filter(Boolean);
        }

        if (!evalIds.length) {
            this.state.totalEmployees = 0;
            this.state.avgScore       = "0.0";
            this.state.passRate       = "0";
            this.state.evaluations    = [];
            this.state.chartData      = null;
            return;
        }

        // Đọc evaluations cho roster table
        const evaluations = await this.orm.read(
            "hr.performance.evaluation",
            evalIds,
            ["employee_id", "job_id", "performance_score", "performance_level", "state"]
        );

        const total     = evaluations.length;
        const scoreSum  = evaluations.reduce((s, e) => s + (e.performance_score || 0), 0);
        const passCount = evaluations.filter(
            (e) => e.performance_level === "pass" || e.performance_level === "excellent"
        ).length;

        this.state.totalEmployees = total;
        this.state.avgScore       = total ? (scoreSum / total).toFixed(2) : "0.0";
        this.state.passRate       = total ? Math.round((passCount / total) * 100).toString() : "0";
        this.state.evaluations    = evaluations;

        // Lấy chart data từ Python
        const reportId = record.resId;
        if (reportId) {
            try {
                const chartData = await this.orm.call(
                    "hr.performance.report",
                    "get_report_dashboard_data",
                    [reportId]
                );
                this.state.chartData = chartData;
            } catch (e) {
                console.error("PerformanceDashboard: get_report_dashboard_data failed", e);
            }
        }
    }

    // ── Chart rendering orchestrator ──────────────────────────────────────────
    _renderAllCharts() {
        if (!window.Chart || !this.state.chartData) return;
        this._destroyCharts();
        const d = this.state.chartData;
        this._renderChartA(d.task_summary);
        this._renderChartB(d.attendance_summary);
        this._renderChartC(d.late_summary);
        this._renderQualitativeCharts(d.qualitative_charts || []);
    }

    // ── Chart A: Task Summary — stacked bar ───────────────────────────────────
    _chartAConfig(ts) {
        const pending = ts.total_tasks.map((t, i) => t - (ts.done_tasks[i] || 0));
        return {
            type: "bar",
            data: {
                labels: ts.names,
                datasets: [
                    {
                        label: "Done",
                        data: ts.done_tasks,
                        backgroundColor: C_GREEN + "cc",
                        borderColor: C_GREEN,
                        borderWidth: 1,
                        stack: "tasks",
                        borderRadius: 4,
                    },
                    {
                        label: "Pending",
                        data: pending,
                        backgroundColor: C_AMBER + "99",
                        borderColor: C_AMBER,
                        borderWidth: 1,
                        stack: "tasks",
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                ...baseBarOpts("Số task"),
                plugins: {
                    legend: { display: true, position: "top" },
                    tooltip: {
                        callbacks: {
                            afterBody: (items) => {
                                const i = items[0].dataIndex;
                                return [`Total: ${ts.total_tasks[i]}`];
                            },
                        },
                    },
                },
            },
        };
    }

    _renderChartA(ts) {
        const el = this.refChartA.el;
        if (!el || !ts || !ts.names.length) return;
        this._charts.A = new window.Chart(el, this._chartAConfig(ts));
    }

    // ── Chart B: Attendance — doughnut ────────────────────────────────────────
    _chartBConfig(as) {
        return {
            type: "doughnut",
            data: {
                labels: as.names,
                datasets: [{
                    data: as.worked_days,
                    backgroundColor: as.names.map((_, i) => POINT_COLORS[i % POINT_COLORS.length]),
                    borderWidth: 2,
                    borderColor: "#fff",
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "65%",
                plugins: {
                    legend: { display: true, position: "right", labels: { font: { size: 11 } } },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.label}: ${c.parsed} ngày`,
                        },
                    },
                },
            },
        };
    }

    _renderChartB(as) {
        const el = this.refChartB.el;
        if (!el || !as || !as.names.length) return;
        this._charts.B = new window.Chart(el, this._chartBConfig(as));
    }

    // ── Chart C: Late count — line ────────────────────────────────────────────
    _chartCConfig(ls) {
        return {
            type: "line",
            data: {
                labels: ls.names,
                datasets: [{
                    label: "Số lần trễ",
                    data: ls.late_count,
                    borderColor: C_RED,
                    backgroundColor: "rgba(239,68,68,0.08)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: 8,
                    pointHoverRadius: 10,
                    pointBackgroundColor: ls.names.map((_, i) => POINT_COLORS[i % POINT_COLORS.length]),
                    pointBorderColor: ls.names.map((_, i) => POINT_COLORS[i % POINT_COLORS.length]),
                }],
            },
            options: {
                ...baseLineOpts("Số lần trễ"),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.label}: ${c.parsed.y} lần trễ`,
                        },
                    },
                },
            },
        };
    }

    _renderChartC(ls) {
        const el = this.refChartC.el;
        if (!el || !ls || !ls.names.length) return;
        this._charts.C = new window.Chart(el, this._chartCConfig(ls));
    }

    // ── Qualitative charts — doughnut per KPI ────────────────────────────────
    _qualChartConfig(qc) {
        return {
            type: "doughnut",
            data: {
                labels: qc.labels,
                datasets: [{
                    data: qc.scores,
                    backgroundColor: qc.labels.map((_, i) => POINT_COLORS[i % POINT_COLORS.length]),
                    borderWidth: 2,
                    borderColor: "#fff",
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "60%",
                plugins: {
                    legend: { display: true, position: "right", labels: { font: { size: 11 } } },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.label}: ${c.parsed} điểm`,
                        },
                    },
                },
            },
        };
    }

    _renderQualitativeCharts(qualCharts) {
        qualCharts.forEach((qc, idx) => {
            const el = document.getElementById(`pd-qual-chart-${idx}`);
            if (!el) return;
            const key = `qual_${idx}`;
            if (this._charts[key]) { this._charts[key].destroy(); }
            this._charts[key] = new window.Chart(el, this._qualChartConfig(qc));
        });
    }

    _destroyCharts() {
        for (const k of Object.keys(this._charts)) {
            try { this._charts[k].destroy(); } catch (_) {}
        }
        this._charts = {};
    }

    // ── Helpers ───────────────────────────────────────────────────────────────
    _getEvalIds() {
        const evalList = this.props.record.data.evaluation_ids;
        if (evalList?.records) return evalList.records.map((r) => r.resId).filter(Boolean);
        if (Array.isArray(evalList)) return evalList.map((r) => (typeof r === "object" ? r.id || r.resId : r)).filter(Boolean);
        return [];
    }

    async _writeConfigField(reportVals, evalVals) {
        const record   = this.props.record;
        const reportId = record.resId;
        if (!reportId) return;
        await this.orm.write("hr.performance.report", [reportId], reportVals);
        if (evalVals && Object.keys(evalVals).length) {
            const evalIds = this._getEvalIds();
            if (evalIds.length) await this.orm.write("hr.performance.evaluation", evalIds, evalVals);
        }
        await record.load();
        await this._loadDashboardData();
    }

    // ── Event handlers ────────────────────────────────────────────────────────
    async onPeriodChange(ev) {
        const value = ev.target.value;
        this.state.period = value;
        await this._writeConfigField({ period: value }, { period: value });
    }

    async onStartDateChange(ev) {
        const value = ev.target.value;
        this.state.startDate = value;
        if (value) this.state.periodLabel = formatMonthYear(value);
        await this._writeConfigField({ start_date: value || false }, { start_date: value || false });
    }

    async onEndDateChange(ev) {
        const value = ev.target.value;
        this.state.endDate = value;
        await this._writeConfigField({ end_date: value || false }, { end_date: value || false });
    }

    async onDeadlineChange(ev) {
        const value = ev.target.value;
        this.state.deadline = value;
        await this._writeConfigField({ deadline: value || false }, { deadline: value || false });
    }

    async onActiveChange(ev) {
        const value = ev.target.checked;
        this.state.active = value;
        await this._writeConfigField({ active: value }, { active: value });
    }

    async exportExcelReport() {
        const reportId = this.props.record.resId;
        if (!reportId) return;
        const action = await this.orm.call("hr.performance.report", "action_export_excel_report", [reportId]);
        if (action) this.actionService.doAction(action);
    }

    openEvaluation(evalId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.performance.evaluation",
            res_id: evalId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("views").add("performance_dashboard_form", {
    ...formView,
    Renderer: PerformanceDashboardRenderer,
    Controller: FormController,
});
