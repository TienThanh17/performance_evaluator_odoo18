/** @odoo-module **/
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { loadBundle, loadJS } from "@web/core/assets";
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
const C_SLATE = "#94a3b8";

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

function formatChartMetric(value, decimals = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "--";
    }
    return Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: decimals,
    });
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
// Chart.js loader
// ─────────────────────────────────────────────────────────────────────────────
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

// ─────────────────────────────────────────────────────────────────────────────
// OWL Component
// ─────────────────────────────────────────────────────────────────────────────
export class DeptKpiDashboard extends Component {
    static template = "performance_evaluator.DeptKpiDashboard";
    static props = ["*"];
    static CHART_RENDERERS = {
        line: "_renderLineChart",
        bar: "_renderBarChart",
        stacked_bar: "_renderStackedBarChart",
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
            commentModalOpen: false,
            commentModalLoading: false,
            commentModalRows: [],
            commentModalEmployeeName: "",
            commentModalEvaluationName: "",
        });

        this._charts = {};
        this._onWindowKeydown = (event) => {
            if (event.key === "Escape" && this.state.commentModalOpen) {
                this.closeCommentPopup();
            }
        };

        this._loadChartAssets = async () => {
            if (!window.Chart) {
                try {
                    await loadBundle("web.chartjs_lib");
                } catch (bundleError) {
                    console.warn(
                        "DeptKpiDashboard: failed to load web.chartjs_lib bundle",
                        bundleError
                    );
                }
                if (!window.Chart) {
                    await loadJS("/web/static/lib/Chart/Chart.js");
                }
            }

            if (!window.ChartDataLabels) {
                await loadJS("/survey/static/src/js/libs/chartjs-plugin-datalabels.js");
            }
        };

        onWillStart(async () => {
            await this._loadChartAssets();
            const [isManager, isHR] = await Promise.all([
                user.hasGroup(MANAGER_GROUP),
                user.hasGroup(HR_GROUP),
            ]);
            Object.assign(this.state, { isManager, isHR });
            await this._loadDepartments();
        });

        onMounted(async () => {
            window.addEventListener("keydown", this._onWindowKeydown);
            if (this.state.phase === "done") {
                await this._renderAllCharts();
            }
        });

        onWillUnmount(() => {
            window.removeEventListener("keydown", this._onWindowKeydown);
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

    get approvableCount() {
        return (this.reportDashboard?.evaluations || []).filter(
            (ev) => ev.state === "manager_evaluating"
        ).length;
    }

    chartIcon(chartType) {
        const icons = {
            line: "fa fa-line-chart",
            bar: "fa fa-bar-chart",
            stacked_bar: "fa fa-bar-chart",
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

    formatReportSnapshotScore(val) {
        if (val === false || val === null || val === undefined) {
            return "—";
        }
        return (Number(val || 0) / 100).toFixed(2);
    }

    levelLabel(lvl) {
        return { excellent: _t("⭐ Excellent"), pass: _t("✓ Pass"), fail: _t("✗ Fail") }[lvl] || "—";
    }

    formatCommentCount(count) {
        const normalizedCount = Number(count || 0);
        return normalizedCount === 1
            ? _t("1 comment")
            : _t("%s comments").replace("%s", normalizedCount);
    }

    commentText(value) {
        return value || "—";
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
        const deptEvaluationId = this.state.selectedEvaluationId;
        if (!deptEvaluationId || !this.approvableCount || this.state.approvingAll) {
            return;
        }
        this.state.approvingAll = true;
        try {
            const action = await this.orm.call(
                "hr.performance.evaluation",
                "action_open_approve_all_wizard_by_dept_evaluation",
                [],
                { dept_evaluation_id: deptEvaluationId }
            );
            await this.actionService.doAction(action, {
                onClose: async (closeInfo) => {
                    if (!closeInfo?.approved) {
                        return;
                    }
                    const evaluation = this.state.evaluations.find(
                        (item) => item.id === this.state.selectedEvaluationId
                    );
                    if (evaluation && this.state.selectedDepartmentId) {
                        await this._loadDashboardData(this.state.selectedDepartmentId, evaluation);
                    }
                },
            });
        } catch (error) {
            this.notification.add(
                error?.data?.message ||
                error?.message ||
                _t("Could not open batch approval."),
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

    async openCommentPopup(evaluationRow) {
        const commentCount = Number(evaluationRow?.comment_count || 0);
        if (!evaluationRow?.id || !commentCount || this.state.commentModalLoading) {
            return;
        }

        this.state.commentModalOpen = true;
        this.state.commentModalLoading = true;
        this.state.commentModalRows = [];
        this.state.commentModalEmployeeName = evaluationRow.employee_id?.[1] || "";
        this.state.commentModalEvaluationName = evaluationRow.name || "";

        try {
            const payload = await this.orm.call(
                "hr.performance.evaluation",
                "get_comment_popup_rows",
                [evaluationRow.id],
            );
            this.state.commentModalRows = payload?.rows || [];
            this.state.commentModalEmployeeName =
                payload?.employee_name || this.state.commentModalEmployeeName;
            this.state.commentModalEvaluationName =
                payload?.evaluation_name || this.state.commentModalEvaluationName;
        } catch (error) {
            this.notification.add(
                error?.data?.message ||
                error?.message ||
                _t("Could not load evaluation comments."),
                { type: "danger" }
            );
            this.closeCommentPopup();
        } finally {
            this.state.commentModalLoading = false;
        }
    }

    closeCommentPopup() {
        this.state.commentModalOpen = false;
        this.state.commentModalLoading = false;
        this.state.commentModalRows = [];
        this.state.commentModalEmployeeName = "";
        this.state.commentModalEvaluationName = "";
    }

    // ── Chart rendering ───────────────────────────────────────────────────────
    async _renderAllCharts() {
        const d = this.state.data;
        if (!d) return;
        this._destroyCharts();
        this._renderDynamicCharts(d.dynamic_charts || []);
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
            font: { size: 12 },
        };
        if (isHourAxis) {
            yTicks.callback = (value) => formatHour(value);
        } else if (yAxis.integerOnly) {
            yTicks.callback = (value) => (Number.isInteger(value) ? value : "");
        }
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
                        ticks: { maxTicksLimit: 10, font: { size: 12 } },
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
        const chartMeta = chartInfo.chart_meta || {};
        const targetLine = chartMeta.target_line || null;
        const yAxis = chartMeta.y_axis || {};
        const yTicks = { font: { size: 12 } };
        if (yAxis.integerOnly) {
            yTicks.callback = (value) => (Number.isInteger(value) ? value : "");
        }
        const datasets = (chartData.datasets || []).map((dataset) => {
            const isTargetLine =
                dataset?.type === "line" ||
                (Array.isArray(dataset?.borderDash) && dataset.borderDash.length > 0);
            if (isTargetLine) {
                return {
                    type: "line",
                    borderColor: C_RED,
                    backgroundColor: "rgba(0,0,0,0)",
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    fill: false,
                    tension: 0,
                    ...dataset,
                };
            }
            return {
                backgroundColor: C_BLUE,
                borderRadius: 0,
                maxBarThickness: 42,
                ...dataset,
            };
        });
        const referenceLinePlugin = {
            id: `datasetReferenceLine_${chartInfo.widget_id || "bar"}`,
            afterDatasetsDraw: (chart) => {
                const {
                    ctx: chartCtx,
                    chartArea,
                    scales: { x, y },
                } = chart;
                if (!chartArea || !x || !y) {
                    return;
                }

                chart.data.datasets.forEach((dataset, datasetIndex) => {
                    const isReferenceLine =
                        dataset?.type === "line" &&
                        Array.isArray(dataset?.borderDash) &&
                        dataset.borderDash.length > 0;
                    if (!isReferenceLine) {
                        return;
                    }

                    const meta = chart.getDatasetMeta(datasetIndex);
                    if (!meta || meta.hidden) {
                        return;
                    }

                    const values = Array.isArray(dataset.data) ? dataset.data : [];
                    if (!values.length) {
                        return;
                    }

                    chartCtx.save();
                    chartCtx.beginPath();
                    chartCtx.lineWidth = dataset.borderWidth || 2;
                    chartCtx.strokeStyle = dataset.borderColor || C_RED;
                    chartCtx.setLineDash(dataset.borderDash || [5, 4]);

                    if (values.length === 1) {
                        const yPos = y.getPixelForValue(values[0]);
                        chartCtx.moveTo(chartArea.left, yPos);
                        chartCtx.lineTo(chartArea.right, yPos);
                    } else {
                        values.forEach((value, valueIndex) => {
                            const xPos = x.getPixelForValue(valueIndex);
                            const yPos = y.getPixelForValue(value);
                            if (valueIndex === 0) {
                                chartCtx.moveTo(xPos, yPos);
                            } else {
                                chartCtx.lineTo(xPos, yPos);
                            }
                        });
                    }

                    chartCtx.stroke();
                    chartCtx.restore();
                });
            },
        };
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
                    legend: {
                        display: datasets.length > 1 || !!targetLine,
                        onClick: (event, legendItem, legend) => {
                            if (legendItem.datasetIndex === -1) {
                                legend.chart.$targetLineHidden = !legend.chart.$targetLineHidden;
                                legend.chart.update();
                                return;
                            }
                            Chart.defaults.plugins.legend.onClick(event, legendItem, legend);
                        },
                        labels: {
                            generateLabels: (chart) => {
                                const baseLabels = Chart.defaults.plugins.legend.labels.generateLabels(chart);
                                if (!targetLine) {
                                    return baseLabels;
                                }
                                return [
                                    ...baseLabels,
                                    {
                                        text: targetLine.label || "Target",
                                        fillStyle: "rgba(0,0,0,0)",
                                        strokeStyle: targetLine.color || C_RED,
                                        lineWidth: 1.5,
                                        lineDash: targetLine.dash || [6, 6],
                                        hidden: Boolean(chart.$targetLineHidden),
                                        datasetIndex: -1,
                                    },
                                ];
                            },
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false } },
                    y: {
                        beginAtZero: yAxis.beginAtZero ?? true,
                        min: yAxis.min,
                        max: yAxis.max,
                        ticks: yTicks,
                        grid: { color: "rgba(0,0,0,0.05)" },
                    },
                },
            },
            plugins: [
                ...(targetLine
                    ? [
                        {
                            id: `fullWidthTargetLine_${chartInfo.widget_id || "bar"}`,
                            afterDatasetsDraw: (chart) => {
                                if (chart.$targetLineHidden) {
                                    return;
                                }
                                const {
                                    ctx: chartCtx,
                                    chartArea,
                                    scales: { y },
                                } = chart;
                                if (!chartArea || !y) {
                                    return;
                                }

                                const yPos = y.getPixelForValue(targetLine.value);
                                chartCtx.save();
                                chartCtx.beginPath();
                                chartCtx.moveTo(chartArea.left, yPos);
                                chartCtx.lineTo(chartArea.right, yPos);
                                chartCtx.lineWidth = 1.5;
                                chartCtx.strokeStyle = targetLine.color || C_RED;
                                chartCtx.setLineDash(targetLine.dash || [6, 6]);
                                chartCtx.stroke();
                                chartCtx.restore();
                            },
                        },
                    ]
                    : []),
                referenceLinePlugin,
            ],
        });
    }

    _renderStackedBarChart(canvas, chartInfo) {
        const Chart = window.Chart;
        const ctx = canvas?.getContext?.("2d");
        if (!ctx) return null;
        const chartData = chartInfo.chart_data || {};
        const chartMeta = chartInfo.chart_meta || {};
        const yAxis = chartMeta.y_axis || {};
        const yTicks = { font: { size: 12 } };
        if (yAxis.integerOnly) {
            yTicks.callback = (value) => (Number.isInteger(value) ? value : "");
        }
        const datasets = (chartData.datasets || []).map((dataset, index) => {
            const isTargetLine =
                dataset?.type === "line" ||
                (Array.isArray(dataset?.borderDash) && dataset.borderDash.length > 0);
            if (isTargetLine) {
                return {
                    type: "line",
                    borderColor: C_RED,
                    backgroundColor: "rgba(0,0,0,0)",
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    fill: false,
                    tension: 0,
                    ...dataset,
                };
            }
            return {
                backgroundColor:
                    dataset.backgroundColor ||
                    (index === 0 ? "rgba(3, 103, 176, 0.88)" : "rgba(148, 163, 184, 0.55)"),
                borderColor: dataset.borderColor || (index === 0 ? C_BLUE : C_SLATE),
                borderWidth: 1,
                borderRadius: 0,
                borderSkipped: false,
                maxBarThickness: 42,
                ...dataset,
            };
        });
        const referenceLinePlugin = {
            id: `stackedReferenceLine_${chartInfo.widget_id || "stacked_bar"}`,
            afterDatasetsDraw: (chart) => {
                const {
                    ctx: chartCtx,
                    chartArea,
                    scales: { x, y },
                } = chart;
                if (!chartArea || !x || !y) {
                    return;
                }

                chart.data.datasets.forEach((dataset, datasetIndex) => {
                    const isReferenceLine =
                        dataset?.type === "line" &&
                        Array.isArray(dataset?.borderDash) &&
                        dataset.borderDash.length > 0;
                    if (!isReferenceLine) {
                        return;
                    }

                    const meta = chart.getDatasetMeta(datasetIndex);
                    if (!meta || meta.hidden) {
                        return;
                    }

                    const values = Array.isArray(dataset.data) ? dataset.data : [];
                    if (!values.length) {
                        return;
                    }

                    chartCtx.save();
                    chartCtx.beginPath();
                    chartCtx.lineWidth = dataset.borderWidth || 2;
                    chartCtx.strokeStyle = dataset.borderColor || C_RED;
                    chartCtx.setLineDash(dataset.borderDash || [5, 4]);

                    if (values.length === 1) {
                        const yPos = y.getPixelForValue(values[0]);
                        chartCtx.moveTo(chartArea.left, yPos);
                        chartCtx.lineTo(chartArea.right, yPos);
                    } else {
                        values.forEach((value, valueIndex) => {
                            const xPos = x.getPixelForValue(valueIndex);
                            const yPos = y.getPixelForValue(value);
                            if (valueIndex === 0) {
                                chartCtx.moveTo(xPos, yPos);
                            } else {
                                chartCtx.lineTo(xPos, yPos);
                            }
                        });
                    }

                    chartCtx.stroke();
                    chartCtx.restore();
                });
            },
        };
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
                    legend: { display: true, position: "top" },
                    tooltip: {
                        callbacks: {
                            label: (context) =>
                                `${context.dataset.label}: ${formatChartMetric(context.parsed?.y)}`,
                            afterBody: (items) => {
                                const index = items[0]?.dataIndex;
                                if (index === undefined || index === null) {
                                    return [];
                                }
                                return [
                                    `${_t("Target")}: ${formatChartMetric(chartMeta.target_values?.[index])}`,
                                    `${_t("Actual")}: ${formatChartMetric(chartMeta.actual_values?.[index])}`,
                                    `${_t("Gap to Target")}: ${formatChartMetric(chartMeta.gap_to_target_values?.[index])}`,
                                ];
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: false },
                    },
                    y: {
                        stacked: true,
                        beginAtZero: yAxis.beginAtZero ?? true,
                        min: yAxis.min,
                        max: yAxis.max,
                        ticks: yTicks,
                        grid: { color: "rgba(0,0,0,0.05)" },
                    },
                },
            },
            plugins: [referenceLinePlugin],
        });
    }

    _renderDoughnutChart(canvas, chartInfo) {
        const ChartDataLabels = window.ChartDataLabels;
        const Chart = window.Chart;
        const ctx = canvas?.getContext?.("2d");
        if (!ctx) return null;
        const chartData = chartInfo.chart_data || {};
        const labels = chartData.labels || [];
        return new Chart(ctx, {
            type: "doughnut",
            plugins: ChartDataLabels ? [ChartDataLabels] : [],
            data: {
                labels,
                datasets: chartData.datasets || [],
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
                    datalabels: {
                        display: true,
                        color: "#ffffff",
                        formatter: (value, ctx) => {
                            if (value === 0) return "";
                            const unit = ctx.dataset.unit || "";
                            return `${value} ${unit}`.trim();
                        },
                        font: {
                            weight: "bold",
                            size: 14,
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
                    borderRadius: 0,
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
