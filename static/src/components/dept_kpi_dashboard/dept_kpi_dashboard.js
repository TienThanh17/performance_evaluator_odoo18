/** @odoo-module **/
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import {
    formatScore as _formatScore,
    formatVariance as _formatVariance,
    varianceClass as _varianceClass,
    statusText as _statusText,
    statusClass as _statusClass,
} from "@custom_adecsol_hr_performance_evaluator/utils/kpi_helpers";

const MANAGER_GROUP = "custom_adecsol_hr_performance_evaluator.group_manager";
const HR_GROUP = "custom_adecsol_hr_performance_evaluator.group_hr";

// ─────────────────────────────────────────────────────────────────────────────
// Colour palette — mirrors SCSS $dept-primary / $dept-green etc.
// ─────────────────────────────────────────────────────────────────────────────
const C_BLUE = "#0367b0";
const C_GREEN = "#119a45";
const C_AMBER = "#e6a817";
const C_RED = "#e03c3c";
const C_PURPLE = "#7c3aed";
const C_TEAL = "#0891b2";

// Per-employee point colours for Chart C & D
const POINT_COLORS = [
    "#0367b0", "#119a45", "#e6a817", "#7c3aed",
    "#0891b2", "#e03c3c", "#f97316", "#84cc16",
    "#ec4899", "#14b8a6",
];

function formatPeriodLabel(dateStr) {
    if (!dateStr) return "—";
    const d = new Date(dateStr);
    const year = d.getFullYear();
    const monthName = d.toLocaleDateString("en-US", { month: "long" });
    return `${_t(monthName)} / ${year}`;
}

function formatHour(h) {
    if (h === null || h === undefined || Number.isNaN(Number(h))) {
        return "--";
    }
    const value = Number(h);
    const hours = Math.trunc(value);
    const minutes = Math.round((value - hours) * 60);
    return `${hours}:${String(minutes).padStart(2, "0")}`;
}

/** Chart A — stacked bar: total vs done tasks per employee */
function buildChartAData(employeeStats) {
    const names = employeeStats.map((e) => e.name);
    const total = employeeStats.map((e) => e.total);
    const done = employeeStats.map((e) => e.done);
    const pending = employeeStats.map((e) => e.pending);
    return { names, total, done, pending };
}

/** Chart B — bar: project completion % */
function buildChartBData(projectProgress) {
    // projectProgress = [{name, progress_pct, total_tasks, done_tasks}, ...]
    const projects = projectProgress.map((p) => p.name);
    const pct = projectProgress.map((p) => p.progress_pct);
    const totals = projectProgress.map((p) => p.total_tasks);
    const done = projectProgress.map((p) => p.done_tasks);
    return { projects, pct, totals, done };
}

/** Chart C — line: attendance count per employee */
function buildChartCData(attendanceData) {
    // attendanceData = [{employee_id, name, attendance_count}, ...]
    return attendanceData.map((e, i) => ({
        name: e.name,
        count: e.attendance_count,
        color: POINT_COLORS[i % POINT_COLORS.length],
    }));
}

/** Chart D — line: bug count per employee */
function buildChartDData(bugData) {
    // bugData = [{employee_id, name, bug_count}, ...]
    return bugData.map((e, i) => ({
        name: e.name,
        bugs: e.bug_count,
        color: POINT_COLORS[i % POINT_COLORS.length],
    }));
}

/** Chart E — line: department KPI trend across recent periods */
function buildChartEData(trendData) {
    return {
        labels: trendData?.labels || [],
        datasets: [
            {
                label: _t("Department KPI Score"),
                data: trendData?.scores || [],
                borderColor: C_PURPLE,
                backgroundColor: C_PURPLE + "22",
                pointBackgroundColor: C_PURPLE,
                pointRadius: 4,
                tension: 0.35,
                fill: true,
            },
        ],
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart.js CDN loader (reuse pattern from kpi_dashboard_page.js)
// ─────────────────────────────────────────────────────────────────────────────
let _chartJsPromise = null;
function loadChartJs() {
    if (typeof window.Chart !== "undefined") return Promise.resolve();
    if (_chartJsPromise) return _chartJsPromise;
    _chartJsPromise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js";
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
    });
    return _chartJsPromise;
}

// ─────────────────────────────────────────────────────────────────────────────
// Default chart options helpers
// ─────────────────────────────────────────────────────────────────────────────
function baseBarOpts(yLabel = "") {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        },
        scales: {
            x: { ticks: { font: { size: 11 }, maxRotation: 30 }, grid: { display: false } },
            y: {
                title: { display: !!yLabel, text: yLabel, font: { size: 11 } },
                grid: { color: "rgba(0,0,0,0.05)" },
                ticks: { font: { size: 10 } },
            },
        },
    };
}

function baseLineOpts(yLabel = "", xLabel = "") {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        },
        scales: {
            x: {
                title: { display: !!xLabel, text: xLabel, font: { size: 11 } },
                ticks: { font: { size: 11 } },
                grid: { display: false },
            },
            y: {
                title: { display: !!yLabel, text: yLabel, font: { size: 11 } },
                grid: { color: "rgba(0,0,0,0.05)" },
                ticks: { font: { size: 10 } },
            },
        },
    };
}

function buildThresholdLinePlugin(thresholdValue = 100) {
    return {
        id: `deptThresholdLine_${thresholdValue}`,
        beforeDraw: (chart) => {
            const {
                ctx,
                chartArea,
                scales: { y },
            } = chart;
            if (!chartArea || !y) {
                return;
            }
            const yPos = y.getPixelForValue(thresholdValue);
            ctx.save();
            ctx.beginPath();
            ctx.moveTo(chartArea.left, yPos);
            ctx.lineTo(chartArea.right, yPos);
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = C_RED;
            ctx.setLineDash([6, 4]);
            ctx.stroke();
            ctx.restore();
        },
    };
}

function reportDoughnutPlugins() {
    return [
        {
            id: "deptReportEmptyStatePlugin",
            afterDraw(chart) {
                const data = chart.data.datasets[0]?.data || [];
                const isEmpty =
                    !data.length || data.every((val) => val === 0 || val === null);
                if (!isEmpty) {
                    return;
                }
                const ctx = chart.ctx;
                const { width, height } = chart;
                chart.clear();
                ctx.save();
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.font = "14px sans-serif";
                ctx.fillStyle = "#9ca3af";
                ctx.fillText(_t("No evaluation data available"), width / 2, height / 2);
                ctx.restore();
            },
        },
        {
            id: "deptReportSliceLabelsPlugin",
            afterDatasetsDraw(chart) {
                const ctx = chart.ctx;
                chart.data.datasets.forEach((dataset, i) => {
                    const meta = chart.getDatasetMeta(i);
                    if (meta.hidden) {
                        return;
                    }
                    meta.data.forEach((element, index) => {
                        const data = dataset.data[index];
                        if (!(data > 0)) {
                            return;
                        }
                        const position = element.tooltipPosition();
                        ctx.save();
                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 12px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText(data, position.x, position.y);
                        ctx.restore();
                    });
                });
            },
        },
    ];
}

// ─────────────────────────────────────────────────────────────────────────────
// OWL Component
// ─────────────────────────────────────────────────────────────────────────────
export class DeptKpiDashboard extends Component {
    static template = "performance_evaluator.DeptKpiDashboard";
    static props = ["*"];
    static CHART_RENDERERS = {
        line: "_renderLineChart",
        bar: "_renderBarChart",
        doughnut: "_renderDoughnutChart",
    };

    setup() {
        const actionContext = this.props.action?.context || {};
        const defaultDepartmentId =
            parseInt(actionContext.default_department_id, 10) || false;
        const defaultEvaluationId =
            parseInt(actionContext.default_evaluation_id, 10) || false;

        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        // Canvas refs
        this.dashboardRootRef = useRef("dashboardRoot");
        this.refA = useRef("chartA");
        this.refB = useRef("chartB");
        this.refC = useRef("chartC");
        this.refD = useRef("chartD");
        this.refE = useRef("chartE");
        this.refReportScore = useRef("reportChartScore");
        this.refReportTask = useRef("reportChartA");
        this.refReportAttendance = useRef("reportChartB");
        this.refReportLate = useRef("reportChartC");

        this.state = useState({
            phase: "loading",           // "loading" | "done" | "empty" | "error"
            errorMsg: "",
            chartErrorMsg: "",
            isManager: false,
            isHR: false,
            defaultDepartmentId,
            defaultEvaluationId,
            departments: [],
            selectedDepartmentId: null,
            evaluations: [],
            selectedEvaluationId: null,
            data: null,
            approvingAll: false,
        });

        this._charts = {};

        onWillStart(async () => {
            const [isManager, isHR] = await Promise.all([
                user.hasGroup(MANAGER_GROUP),
                user.hasGroup(HR_GROUP),
                loadChartJs(),
            ]);
            Object.assign(this.state, { isManager, isHR });
            await this._loadDepartments();
        });

        onMounted(async () => {
            if (this.state.phase === "done") {
                await this._renderAllCharts();
            }
        });

        onWillUnmount(() => {
            this._destroyCharts();
        });

        useEffect(
            () => {
                if (this.state.phase === "done" && this.state.data) {
                    this._renderAllCharts();
                }
            },
            () => [this.state.phase, this.state.data] // Chạy lại effect này nếu phase hoặc data thay đổi
        );
    }

    // ── Getters ───────────────────────────────────────────────────────────────

    get scoreScale() {
        return this.state.data?.score_scale || { base: 100, suffix: " / 100" };
    }

    get reportDashboard() {
        return this.state.data?.report_dashboard || null;
    }

    get canExportReport() {
        return !!this.reportDashboard?.report_id;
    }

    get reportScoreScale() {
        return this.reportDashboard?.score_scale || this.scoreScale;
    }

    get reportThresholds() {
        return this.reportDashboard?.thresholds || { excellent: 90, pass: 50 };
    }

    get approvableCount() {
        return (this.reportDashboard?.evaluations || []).filter(
            (ev) => ev.state === "manager_evaluating"
        ).length;
    }

    chartIcon(chartType) {
        const icons = {
            line: "fa fa-line-chart",
            bar: "fa fa-bar-chart",
            doughnut: "fa fa-pie-chart",
        };
        return icons[chartType] || "fa fa-area-chart";
    }

    chartHasData(chart) {
        const labels = chart?.chart_data?.labels || [];
        const datasets = chart?.chart_data?.datasets || [];
        return (
            labels.length > 0 &&
            datasets.some(
                (dataset) => Array.isArray(dataset?.data) && dataset.data.length
            )
        );
    }

    /** Hiển thị điểm số, mặc định 2 chữ số thập phân. */
    formatScore(val, decimals = 2) {
        return _formatScore(val, this.scoreScale, { decimals });
    }

    formatReportScore(val, decimals = 2) {
        return _formatScore(val, this.reportScoreScale, { decimals });
    }

    reportScorePct(value) {
        const base = Number(this.reportScoreScale.base || 100);
        return Math.max(0, Math.min(100, ((Number(value) || 0) / base) * 100));
    }

    levelLabel(lvl) {
        return { excellent: _t("⭐ Excellent"), pass: _t("✓ Pass"), fail: _t("✗ Fail") }[lvl] || "—";
    }

    // ── Quantitative Table Helpers ───────────────────────────────────────────
    formatVariance(row) { return _formatVariance(row); }
    varianceClass(row) { return _varianceClass(row); }
    statusText(row) { return _statusText(row); }
    statusClass(row) { return _statusClass(row); }

    // ── Data loaders ─────────────────────────────────────────────────────────
    async _loadDepartments() {
        try {
            const domain = [["active", "=", true]];
            if (this.state.isManager && !this.state.isHR) {
                domain.push(["manager_id.user_id", "=", user.userId]);
            }

            const depts = await this.orm.searchRead(
                "hr.department",
                domain,
                ["id", "name", "manager_id"],
                { order: "name asc" }
            );
            this.state.departments = depts;

            if (depts.length) {
                const targetDepartment =
                    depts.find((dept) => dept.id === this.state.defaultDepartmentId) ||
                    depts[0];
                this.state.selectedDepartmentId = targetDepartment.id;
                this.state.defaultDepartmentId = false;
                await this._loadEvaluations(targetDepartment.id);
            } else {
                this.state.phase = "empty";
            }
        } catch (e) {
            this.state.errorMsg = _t("Failed to load departments.");
            this.state.phase = "error";
        }
    }

    async _loadEvaluations(departmentId) {
        this.state.phase = "loading";
        this._destroyCharts();
        try {
            const evals = await this.orm.searchRead(
                "hr.department.performance.evaluation",
                [["department_id", "=", departmentId]],
                ["id", "name", "department_id", "start_date", "end_date",
                //    "department_score", "department_level",
                    "state", 'dept_kpi_score'],
                { order: "start_date desc", limit: 24 }
            );
            this.state.evaluations = evals;

            if (evals.length) {
                const targetEvaluation =
                    evals.find(
                        (evaluation) =>
                            evaluation.id === this.state.defaultEvaluationId
                    ) || evals[0];
                this.state.selectedEvaluationId = targetEvaluation.id;
                this.state.defaultEvaluationId = false;
                await this._loadDashboardData(departmentId, targetEvaluation);
            } else {
                this.state.defaultEvaluationId = false;
                this.state.data = null;
                this.state.phase = "empty";
            }
        } catch (e) {
            this.state.errorMsg = _t("Failed to load evaluations.");
            this.state.phase = "error";
        }
    }

    async _loadDashboardData(departmentId, evaluation) {
        this.state.phase = "loading";
        this._destroyCharts();
        try {
            const data = await this.orm.call(
                "hr.department.performance.evaluation",
                "get_dashboard_data",
                [evaluation.id],
            );
            data.period_label =
                data.period_name || formatPeriodLabel(evaluation.start_date);

            this.state.chartErrorMsg = "";
            this.state.data = data;
            this.state.phase = "done";

            await new Promise((r) => requestAnimationFrame(r));
            await this._renderAllCharts();
        } catch (e) {
            console.error("DeptKpiDashboard: _loadDashboardData", e);
            this.state.errorMsg = _t("Failed to load dashboard data.");
            this.state.phase = "error";
        }
    }


    // ── Event handlers ───────────────────────────────────────────────────────
    async onSelectDepartment(ev) {
        const id = parseInt(ev.target.value, 10) || null;
        this.state.selectedDepartmentId = id;
        this.state.evaluations = [];
        this.state.selectedEvaluationId = null;
        if (id) {
            await this._loadEvaluations(id);
        } else {
            this.state.phase = "empty";
        }
    }

    async onSelectEvaluation(ev) {
        const id = parseInt(ev.target.value, 10) || null;
        this.state.selectedEvaluationId = id;
        const ev_obj = this.state.evaluations.find((e) => e.id === id);
        if (ev_obj && this.state.selectedDepartmentId) {
            await this._loadDashboardData(this.state.selectedDepartmentId, ev_obj);
        }
    }

    async exportExcelReport() {
        const reportId = this.reportDashboard?.report_id;
        if (!reportId) {
            return;
        }
        const action = await this.orm.call(
            "hr.performance.report",
            "action_export_excel_report",
            [reportId]
        );
        if (action) {
            this.actionService.doAction(action);
        }
    }

    async approveAllEvaluations() {
        const evalIds = (this.reportDashboard?.evaluations || [])
            .filter((ev) => ev.state === "manager_evaluating")
            .map((ev) => ev.id);
        if (!evalIds.length || this.state.approvingAll) {
            return;
        }
        this.state.approvingAll = true;
        try {
            await this.orm.call("hr.performance.evaluation", "action_approve", [evalIds]);
            const evaluation = this.state.evaluations.find(
                (item) => item.id === this.state.selectedEvaluationId
            );
            if (evaluation && this.state.selectedDepartmentId) {
                await this._loadDashboardData(this.state.selectedDepartmentId, evaluation);
            }
            this.notification.add(_t("All manager evaluations were approved."), {
                type: "success",
            });
        } catch (error) {
            this.notification.add(
                error?.data?.message ||
                    error?.message ||
                    _t("Could not approve evaluations."),
                { type: "danger" }
            );
        } finally {
            this.state.approvingAll = false;
        }
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

    openIndividualDashboard(employeeId, evalId) {
        if (!employeeId || !evalId) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.client",
            tag: "kpi_individual_dashboard",
            name: _t("Individual KPI Dashboard"),
            context: {
                default_employee_id: employeeId,
                default_evaluation_id: evalId,
            },
        });
    }

    // ── Chart rendering ───────────────────────────────────────────────────────
    async _renderAllCharts() {
        const d = this.state.data;
        if (!d) return;
        this._destroyCharts();
        this._renderDynamicCharts(d.dynamic_charts || []);
    }

    _renderMacroSections(sections) {
        for (const section of sections || []) {
            if (section.section_type !== "chart_row") {
                continue;
            }
            for (const item of section.items || []) {
                this._renderMacroSectionItem(item);
            }
        }
    }

    _renderMacroSectionItem(item) {
        const canvas = this._getSectionCanvas(item?.key);
        if (!canvas) {
            return;
        }
        switch (item.measure_field) {
            case "department_task_distribution":
                this._renderChartA(
                    this.state.data?.task_summary_by_employee || [],
                    canvas,
                    item.key,
                );
                break;
            case "department_project_progress":
                this._renderChartB(
                    this.state.data?.project_progress || [],
                    canvas,
                    item.key,
                );
                break;
            case "department_attendance":
                this._renderChartC(
                    this.state.data?.attendance_count || [],
                    canvas,
                    item.key,
                );
                break;
            case "department_bug_count":
                this._renderChartD(
                    this.state.data?.bug_count_by_employee || [],
                    canvas,
                    item.key,
                );
                break;
            case "department_score_trend":
                this._renderChartE(
                    this.state.data?.score_trend || {},
                    canvas,
                    item.key,
                );
                break;
        }
    }

    _renderDynamicCharts(charts) {
        for (const chartInfo of charts || []) {
            if (!this.chartHasData(chartInfo)) continue;
            const rootEl = this._getDashboardRootEl();
            const escapedKey = window.CSS?.escape
                ? window.CSS.escape(chartInfo.key)
                : chartInfo.key;
            const canvas = rootEl?.querySelector(
                `canvas[data-chart-key="${escapedKey}"]`
            );
            if (!canvas) {
                console.warn(
                    "DeptKpiDashboard: canvas not found for dynamic chart",
                    chartInfo.key,
                    {
                        rootReady: Boolean(rootEl),
                        availableKeys: this._getAvailableChartKeys(rootEl),
                    }
                );
                continue;
            }

            const rendererName =
                this.constructor.CHART_RENDERERS[chartInfo.chart_type];
            if (!rendererName || typeof this[rendererName] !== "function") {
                continue;
            }

            try {
                const instance = this[rendererName](canvas, chartInfo);
                if (instance) {
                    this._charts[chartInfo.key] = instance;
                }
            } catch (error) {
                console.error(
                    "DeptKpiDashboard: failed to render dynamic chart",
                    chartInfo.key,
                    chartInfo,
                    error
                );
                this.state.chartErrorMsg = _t(
                    "Some charts could not be rendered. Check browser console for details."
                );
            }
        }
    }

    _getDashboardRootEl() {
        return this.dashboardRootRef.el || null;
    }

    _getSectionCanvas(key) {
        if (!key) return null;
        const rootEl = this._getDashboardRootEl();
        const escapedKey = window.CSS?.escape ? window.CSS.escape(key) : key;
        return rootEl?.querySelector(`canvas[data-section-key="${escapedKey}"]`);
    }

    _getAvailableChartKeys(rootEl) {
        if (!rootEl) return [];
        return Array.from(rootEl.querySelectorAll("canvas[data-chart-key]"))
            .map((canvas) => canvas.dataset.chartKey)
            .filter(Boolean);
    }

    _renderLineChart(canvas, chartInfo) {
        const Chart = window.Chart;
        const ctx = canvas?.getContext?.("2d");
        if (!ctx) return null;
        const chartData = chartInfo.chart_data || {};
        const chartMeta = chartInfo.chart_meta || {};
        const datasets = (chartData.datasets || []).map((dataset, index) => {
            const accentColor = index === 0 ? C_GREEN : C_RED;
            const shouldFill = dataset.fill ?? false;
            return {
                borderColor: accentColor,
                backgroundColor: shouldFill ? "rgba(34,197,94,0.12)" : "rgba(0,0,0,0)",
                borderWidth: 2,
                pointBackgroundColor: accentColor,
                pointRadius: index === 0 ? 4 : 0,
                tension: 0.35,
                spanGaps: false,
                fill: shouldFill,
                ...dataset,
            };
        });
        const yAxis = chartMeta.y_axis || {};
        const isHourAxis = yAxis.format === "hour";
        const yTicks = {
            stepSize: yAxis.stepSize,
            callback: isHourAxis ? (value) => formatHour(value) : undefined,
        };
        return new Chart(ctx, {
            type: "line",
            data: {
                labels: chartData.labels || [],
                datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: datasets.length > 1 },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const value = context.parsed?.y;
                                if (isHourAxis) {
                                    return `${context.dataset.label}: ${value != null ? formatHour(value) : "--"}`;
                                }
                                return `${context.dataset.label}: ${value != null ? value : "--"}`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        ticks: { maxTicksLimit: 10, font: { size: 10 } },
                        grid: { display: false },
                    },
                    y: {
                        beginAtZero: isHourAxis ? false : (yAxis.beginAtZero ?? true),
                        min: yAxis.min,
                        max: yAxis.max,
                        ticks: yTicks,
                        grid: { color: "rgba(0,0,0,0.05)" },
                    },
                },
            },
        });
    }

    _renderBarChart(canvas, chartInfo) {
        const Chart = window.Chart;
        const ctx = canvas?.getContext?.("2d");
        if (!ctx) return null;
        const chartData = chartInfo.chart_data || {};
        const datasets = (chartData.datasets || []).map((dataset) => ({
            backgroundColor: C_BLUE,
            borderRadius: 6,
            maxBarThickness: 42,
            ...dataset,
        }));
        return new Chart(ctx, {
            type: "bar",
            data: {
                labels: chartData.labels || [],
                datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: datasets.length > 1 },
                },
                scales: {
                    x: { grid: { display: false } },
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.05)" },
                    },
                },
            },
        });
    }

    _renderDoughnutChart(canvas, chartInfo) {
        const Chart = window.Chart;
        const ctx = canvas?.getContext?.("2d");
        if (!ctx) return null;
        const chartData = chartInfo.chart_data || {};
        const labels = chartData.labels || [];
        const centerTextPlugin = {
            id: "centerText",
            afterDraw: (chart) => {
                const { ctx: chartCtx, chartArea } = chart;
                if (!chartArea) return;
                const targetText = chart.config.data.target_center_text;
                if (!targetText) return;

                const centerX = (chartArea.left + chartArea.right) / 2;
                const centerY = (chartArea.top + chartArea.bottom) / 2;

                chartCtx.save();
                chartCtx.font = "12px sans-serif";
                chartCtx.fillStyle = "#6b7280";
                chartCtx.textAlign = "center";
                chartCtx.textBaseline = "middle";
                chartCtx.fillText("Target", centerX, centerY - 10);
                chartCtx.font = "bold 16px sans-serif";
                chartCtx.fillStyle = "#1f2937";
                chartCtx.fillText(targetText, centerX, centerY + 10);
                chartCtx.restore();
            },
        };
        return new Chart(ctx, {
            type: "doughnut",
            plugins: [centerTextPlugin],
            data: {
                labels,
                datasets: chartData.datasets || [],
                target_center_text: chartData.target_center_text,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: chartInfo.chart_meta?.cutout || "75%",
                plugins: {
                    legend: {
                        display: true,
                        position: "top",
                        labels: {
                            usePointStyle: true,
                            boxWidth: 8,
                            padding: 20,
                            font: {
                                size: 12,
                            },
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const label = labels[context.dataIndex] || context.label || "";
                                return `${label}: ${context.parsed}`;
                            },
                        },
                    },
                },
            },
        });
    }

    _renderChartA(employeeStats, canvas = this.refA.el, chartKey = "A") {
        if (!canvas) return;
        const source = employeeStats;
        const { names, done, pending, total } = buildChartAData(source);
        this._charts[chartKey] = new Chart(canvas, {
            type: "bar",
            data: {
                labels: names,
                datasets: [
                    {
                        label: _t("Completed"),
                        data: done,
                        backgroundColor: C_GREEN + "cc",
                        borderColor: C_GREEN,
                        borderWidth: 1,
                        stack: "tasks",
                    },
                    {
                        label: _t("Pending"),
                        data: pending,
                        backgroundColor: C_AMBER + "99",
                        borderColor: C_AMBER,
                        borderWidth: 1,
                        stack: "tasks",
                    },
                    // Annotation lines: total & completed threshold
                    {
                        label: _t("Total (line)"),
                        data: total,
                        type: "line",
                        borderColor: C_BLUE,
                        borderWidth: 2,
                        borderDash: [5, 4],
                        pointRadius: 3,
                        pointBackgroundColor: C_BLUE,
                        fill: false,
                        tension: 0,
                        stack: undefined,
                        order: -1,
                    },
                ],
            },
            options: {
                ...baseBarOpts(_t("Number of Tasks")),
                plugins: {
                    ...baseBarOpts().plugins,
                    tooltip: {
                        callbacks: {
                            afterBody: (items) => {
                                const idx = items[0].dataIndex;
                                return [`${_t("Total")}: ${total[idx]}`];
                            },
                        },
                    },
                },
            },
        });
    }

    _renderChartB(projectProgress, canvas = this.refB.el, chartKey = "B") {
        if (!canvas) return;

        const source = projectProgress;
        const { projects, pct, totals, done } = buildChartBData(source);

        this._charts[chartKey] = new Chart(canvas, {
            type: "bar",
            data: {
                labels: projects,
                datasets: [{
                    label: _t("Completion (%)"),
                    data: pct,
                    backgroundColor: pct.map((v) =>
                        v >= 80 ? C_GREEN + "cc" :
                            v >= 50 ? C_BLUE + "cc" : C_AMBER + "cc"
                    ),
                    borderColor: pct.map((v) =>
                        v >= 80 ? C_GREEN :
                            v >= 50 ? C_BLUE : C_AMBER
                    ),
                    borderWidth: 1,
                    borderRadius: 5,
                }],
            },
            options: {
                ...baseBarOpts(_t("Progress (%)")),
                scales: {
                    ...baseBarOpts().scales,
                    y: {
                        min: 0, max: 100,
                        title: { display: true, text: _t("Progress (%)"), font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { callback: (v) => v + "%", font: { size: 10 } },
                    },
                },
                plugins: {
                    ...baseBarOpts().plugins,
                    tooltip: {
                        callbacks: {
                            label: (c) => {
                                const i = c.dataIndex;
                                return [
                                    `${_t("Progress")}: ${pct[i]}%`,
                                    `${_t("Done")}: ${done[i]} / ${totals[i]} ${_t("tasks")}`,
                                ];
                            },
                        },
                    },
                },
            },
        });
    }

    _renderChartC(attendanceData, canvas = this.refC.el, chartKey = "C") {
        if (!canvas) return;
        const source = attendanceData;
        const data = buildChartCData(source);
        this._charts[chartKey] = new Chart(canvas, {
            type: "line",
            data: {
                labels: data.map((d) => d.name),
                datasets: [{
                    label: _t("Attendance Count"),
                    data: data.map((d) => d.count),
                    borderColor: C_TEAL,
                    backgroundColor: C_TEAL + "22",
                    pointBackgroundColor: data.map((d) => d.color),
                    pointBorderColor: data.map((d) => d.color),
                    pointRadius: 8,
                    pointHoverRadius: 10,
                    tension: 0.25,
                    fill: true,
                }],
            },
            options: {
                ...baseLineOpts(_t("Số lần chấm công"), _t("Nhân viên")),
                scales: {
                    x: {
                        title: { display: true, text: _t("Nhân viên"), font: { size: 11 } },
                        grid: { display: false },
                        ticks: { font: { size: 11 } },
                    },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: _t("Số lần chấm công"), font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: (this.state.data?.score_scale?.base || 100) / 10, font: { size: 10 } },
                    },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.label}: ${c.parsed.y} ${_t("lần")}`,
                        },
                    },
                },
            },
        });
    }

    _renderChartD(bugData, canvas = this.refD.el, chartKey = "D") {
        if (!canvas) return;
        const source = bugData;
        const data = buildChartDData(source);
        this._charts[chartKey] = new Chart(canvas, {
            type: "line",
            data: {
                labels: data.map((d) => d.name),
                datasets: [{
                    label: _t("Bug Count"),
                    data: data.map((d) => d.bugs),
                    borderColor: C_AMBER,
                    backgroundColor: C_AMBER + "22",
                    pointBackgroundColor: data.map((d) => d.color),
                    pointBorderColor: data.map((d) => d.color),
                    pointRadius: 8,
                    pointHoverRadius: 10,
                    tension: 0.25,
                    fill: true,
                }],
            },
            options: {
                ...baseLineOpts(_t("Number of Bugs"), _t("Employee")),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.label}: ${c.parsed.y} ${_t("bugs")}`,
                        },
                    },
                },
                scales: {
                    ...baseLineOpts().scales,
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: _t("Bug Count"), font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: 1, font: { size: 10 } },
                    },
                },
            },
        });
    }

    _renderChartE(trendData, canvas = this.refE.el, chartKey = "E") {
        if (!canvas) return;
        const { labels, datasets } = buildChartEData(trendData);
        if (!labels.length) return;
        this._charts[chartKey] = new Chart(canvas, {
            type: "line",
            data: { labels, datasets },
            options: {
                ...baseLineOpts(_t("Score"), _t("Month")),
                scales: {
                    x: {
                        title: { display: true, text: _t("Month"), font: { size: 11 } },
                        grid: { display: false },
                        ticks: { font: { size: 11 } },
                    },
                    y: {
                        min: 0, max: this.state.data?.score_scale?.base || 100,
                        title: { display: true, text: _t("Score"), font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: 1, font: { size: 10 } },
                    },
                },
            },
        });
    }

    _renderReportSections(sections) {
        for (const section of sections || []) {
            if (section.section_type === "chart_row") {
                for (const item of section.items || []) {
                    this._renderReportSectionItem(item);
                }
            } else if (section.section_type === "qualitative_grid") {
                this._renderReportQualitativeCharts(
                    section.charts || [],
                    section.key || "dept-report-qual",
                );
            }
        }
    }

    _renderReportSectionItem(item) {
        const canvas = this._getSectionCanvas(item?.key);
        if (!canvas) {
            return;
        }
        switch (item.measure_field) {
            case "report_score_bar":
                this._renderReportScoreChart(
                    this.reportDashboard?.employees || [],
                    canvas,
                    item.key,
                );
                break;
            case "report_task_summary":
                this._renderReportTaskChart(
                    this.reportDashboard?.task_summary || null,
                    canvas,
                    item.key,
                );
                break;
            case "report_attendance":
                this._renderReportAttendanceChart(
                    this.reportDashboard?.attendance_summary || null,
                    canvas,
                    item.key,
                );
                break;
            case "report_late_summary":
                this._renderReportLateChart(
                    this.reportDashboard?.late_summary || null,
                    canvas,
                    item.key,
                );
                break;
        }
    }

    _chartReportScoreConfig(employees) {
        const names = employees.map((employee) => employee.name);
        const scores = employees.map((employee) => employee.score);
        const scoreBase = this.reportScoreScale.base || 100;
        const excellent = this.reportThresholds.excellent || 90;
        const passed = this.reportThresholds.pass || 50;

        return {
            type: "bar",
            data: {
                labels: names,
                datasets: [
                    {
                        label: _t("Individual KPI Score"),
                        data: scores,
                        backgroundColor: scores.map((score) =>
                            score >= excellent
                                ? C_BLUE + "cc"
                                : score >= passed
                                  ? C_GREEN + "cc"
                                  : C_RED + "cc"
                        ),
                        borderColor: scores.map((score) =>
                            score >= excellent ? C_BLUE : score >= passed ? C_GREEN : C_RED
                        ),
                        borderWidth: 1,
                        borderRadius: 5,
                    },
                ],
            },
            options: {
                ...baseBarOpts(_t("Score")),
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 11 } },
                    },
                    y: {
                        min: 0,
                        max: scoreBase,
                        title: {
                            display: true,
                            text: _t("Individual KPI Score"),
                            font: { size: 11 },
                        },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: scoreBase / 10, font: { size: 10 } },
                    },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${_t("Score")}: ${context.parsed.y}`,
                        },
                    },
                },
            },
            plugins: [buildThresholdLinePlugin(scoreBase)],
        };
    }

    _renderReportScoreChart(
        employees,
        canvas = this.refReportScore.el,
        chartKey = "ReportScore",
    ) {
        if (!canvas || !employees.length) {
            return;
        }
        this._charts[chartKey] = new Chart(
            canvas,
            this._chartReportScoreConfig(employees)
        );
    }

    _chartReportTaskConfig(taskSummary) {
        const pending = (taskSummary.total_tasks || []).map(
            (total, index) => total - (taskSummary.done_tasks?.[index] || 0)
        );
        return {
            type: "bar",
            data: {
                labels: taskSummary.names || [],
                datasets: [
                    {
                        label: _t("Done"),
                        data: taskSummary.done_tasks || [],
                        backgroundColor: C_GREEN + "cc",
                        borderColor: C_GREEN,
                        borderWidth: 1,
                        stack: "tasks",
                        borderRadius: 4,
                    },
                    {
                        label: _t("Pending"),
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
                ...baseBarOpts(_t("Number of tasks")),
                plugins: {
                    legend: { display: true, position: "top" },
                    tooltip: {
                        callbacks: {
                            afterBody: (items) => {
                                const index = items[0]?.dataIndex ?? 0;
                                return [`${_t("Total")}: ${taskSummary.total_tasks?.[index] || 0}`];
                            },
                        },
                    },
                },
            },
        };
    }

    _renderReportTaskChart(
        taskSummary,
        canvas = this.refReportTask.el,
        chartKey = "ReportTask",
    ) {
        if (!canvas || !taskSummary?.names?.length) {
            return;
        }
        this._charts[chartKey] = new Chart(
            canvas,
            this._chartReportTaskConfig(taskSummary)
        );
    }

    _chartReportAttendanceConfig(attendanceSummary) {
        const expected = attendanceSummary.expected_work_days || 0;
        return {
            type: "doughnut",
            data: {
                labels: attendanceSummary.names || [],
                datasets: [
                    {
                        data: attendanceSummary.worked_days || [],
                        backgroundColor: (attendanceSummary.names || []).map(
                            (_, index) => POINT_COLORS[index % POINT_COLORS.length]
                        ),
                        borderWidth: 2,
                        borderColor: "#fff",
                        hoverOffset: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: {
                    legend: {
                        display: true,
                        position: "right",
                        labels: { font: { size: 11 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.label}: ${context.parsed} ${_t("days")}`,
                        },
                    },
                    deptReportCenterText: {
                        text: String(expected),
                        subText: _t("Total Days"),
                    },
                },
            },
            plugins: reportDoughnutPlugins(),
        };
    }

    _renderReportAttendanceChart(
        attendanceSummary,
        canvas = this.refReportAttendance.el,
        chartKey = "ReportAttendance",
    ) {
        if (!canvas || !attendanceSummary?.names?.length) {
            return;
        }
        if (!window.Chart.registry.plugins.get("deptReportCenterText")) {
            window.Chart.register({
                id: "deptReportCenterText",
                beforeDraw(chart) {
                    const cfg = chart.config.options.plugins.deptReportCenterText;
                    if (!cfg) {
                        return;
                    }
                    const {
                        ctx,
                        chartArea: { left, right, top, bottom },
                    } = chart;
                    const cx = (left + right) / 2;
                    const cy = (top + bottom) / 2;
                    ctx.save();
                    ctx.font = "bold 22px Inter, sans-serif";
                    ctx.fillStyle = "#111827";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText(cfg.text, cx, cy - 10);
                    ctx.font = "11px Inter, sans-serif";
                    ctx.fillStyle = "#9ca3af";
                    ctx.fillText(cfg.subText, cx, cy + 12);
                    ctx.restore();
                },
            });
        }
        this._charts[chartKey] = new Chart(
            canvas,
            this._chartReportAttendanceConfig(attendanceSummary)
        );
    }

    _chartReportLateConfig(lateSummary) {
        return {
            type: "line",
            data: {
                labels: lateSummary.names || [],
                datasets: [
                    {
                        label: _t("Late Count"),
                        data: lateSummary.late_count || [],
                        borderColor: C_RED,
                        backgroundColor: "rgba(224,60,60,0.08)",
                        fill: true,
                        tension: 0.3,
                        pointRadius: 8,
                        pointHoverRadius: 10,
                        pointBackgroundColor: (lateSummary.names || []).map(
                            (_, index) => POINT_COLORS[index % POINT_COLORS.length]
                        ),
                        pointBorderColor: (lateSummary.names || []).map(
                            (_, index) => POINT_COLORS[index % POINT_COLORS.length]
                        ),
                    },
                ],
            },
            options: {
                ...baseLineOpts(_t("Late Count"), _t("Employee")),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) =>
                                `${context.label}: ${context.parsed.y} ${_t("times late")}`,
                        },
                    },
                },
            },
        };
    }

    _renderReportLateChart(
        lateSummary,
        canvas = this.refReportLate.el,
        chartKey = "ReportLate",
    ) {
        if (!canvas || !lateSummary?.names?.length) {
            return;
        }
        this._charts[chartKey] = new Chart(
            canvas,
            this._chartReportLateConfig(lateSummary)
        );
    }

    _chartReportQualitativeConfig(qualitativeChart) {
        const scoreBase = this.reportScoreScale.base || 100;
        return {
            type: "bar",
            data: {
                labels: qualitativeChart.labels || [],
                datasets: [
                    {
                        label: _t("Score"),
                        data: qualitativeChart.scores || [],
                        backgroundColor: (qualitativeChart.labels || []).map(
                            (_, index) => POINT_COLORS[index % POINT_COLORS.length] + "cc"
                        ),
                        borderColor: (qualitativeChart.labels || []).map(
                            (_, index) => POINT_COLORS[index % POINT_COLORS.length]
                        ),
                        borderWidth: 1,
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.raw} ${_t("points")}`,
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 11 } },
                    },
                    y: {
                        beginAtZero: true,
                        max: scoreBase,
                        title: {
                            display: true,
                            text: _t("Score"),
                            color: "#6b7280",
                            font: { size: 12 },
                        },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: scoreBase / 10, font: { size: 10 } },
                    },
                },
            },
            plugins: [buildThresholdLinePlugin(scoreBase)],
        };
    }

    _renderReportQualitativeCharts(
        qualitativeCharts,
        sectionKey = "dept-report-qual",
    ) {
        qualitativeCharts.forEach((qualitativeChart, index) => {
            const el = document.getElementById(
                `${sectionKey}-qual-chart-${index}`
            );
            if (!el) {
                return;
            }
            const key = `${sectionKey}_ReportQual_${index}`;
            if (this._charts[key]) {
                this._charts[key].destroy();
            }
            this._charts[key] = new Chart(
                el,
                this._chartReportQualitativeConfig(qualitativeChart)
            );
        });
    }

    _destroyCharts() {
        for (const k of Object.keys(this._charts)) {
            try { this._charts[k].destroy(); } catch (_) { }
        }
        this._charts = {};
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Register as client action
// ─────────────────────────────────────────────────────────────────────────────
registry.category("actions").add("kpi_department_dashboard", DeptKpiDashboard);
