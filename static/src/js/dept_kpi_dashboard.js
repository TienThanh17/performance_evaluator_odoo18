/** @odoo-module **/
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";

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

/** Chart E — line: score over timeline (one line per employee) */
function buildChartEData(employees) {
    const months = [_t("Jan"), _t("Feb"), _t("Mar"), _t("Apr"), _t("May"), _t("Jun"), _t("Jul"), _t("Aug"), _t("Sep"), _t("Oct"), _t("Nov"), _t("Dec")];
    const datasets = employees.map((e, i) => {
        const color = POINT_COLORS[i % POINT_COLORS.length];
        return {
            label: e.name,
            // data: months.map(() => parseFloat((4 + Math.random() * 6).toFixed(2))),
            data: null,
            borderColor: color,
            backgroundColor: color + "22",
            pointBackgroundColor: color,
            pointRadius: 4,
            tension: 0.35,
            fill: false,
        };
    });
    return { labels: months, datasets };
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

// ─────────────────────────────────────────────────────────────────────────────
// OWL Component
// ─────────────────────────────────────────────────────────────────────────────
export class DeptKpiDashboard extends Component {
    static template = "performance_evaluator.DeptKpiDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");

        // Canvas refs
        this.refA = useRef("chartA");
        this.refB = useRef("chartB");
        this.refC = useRef("chartC");
        this.refD = useRef("chartD");
        this.refE = useRef("chartE");

        this.state = useState({
            phase: "loading",           // "loading" | "done" | "empty" | "error"
            errorMsg: "",
            isManager: false,
            isHR: false,
            departments: [],
            selectedDepartmentId: null,
            evaluations: [],
            selectedEvaluationId: null,
            data: null,
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
    formatScore(val) {
        if (val == null) return "—";
        const scale = this.state.data?.score_scale || { suffix: " / 10" };
        return `${Number(val).toFixed(2)}${scale.suffix || ""}`;
    }

    levelLabel(lvl) {
        return { excellent: _t("⭐ Excellent"), pass: _t("✓ Pass"), fail: _t("✗ Fail") }[lvl] || "—";
    }

    // ── Quantitative Table Helpers ───────────────────────────────────────────
    formatVariance(row) {
        if (row.variance === 0) return "0%";
        return row.variance > 0 ? `+${row.variance}%` : `${row.variance}%`;
    }

    varianceClass(row) {
        if (row.variance === 0) return "o_kpi_variance o_kpi_variance_good";
        const isGood = row.direction === "lower_better" ? row.variance < 0 : row.variance > 0;
        return isGood ? "o_kpi_variance o_kpi_variance_exceeded" : "o_kpi_variance o_kpi_variance_bad";
    }

    statusText(row) {
        if (row.variance === 0) return _t("Achieved");
        const isGood = row.direction === "lower_better" ? row.variance < 0 : row.variance > 0;
        return isGood ? _t("Exceeded") : _t("Not Met");
    }

    statusClass(row) {
        if (row.variance === 0) return "o_kpi_status o_kpi_status_pass";
        const isGood = row.direction === "lower_better" ? row.variance < 0 : row.variance > 0;
        return isGood ? "o_kpi_status o_kpi_status_excellent" : "o_kpi_status o_kpi_status_fail";
    }

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
                this.state.selectedDepartmentId = depts[0].id;
                await this._loadEvaluations(depts[0].id);
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
                this.state.selectedEvaluationId = evals[0].id;
                await this._loadDashboardData(departmentId, evals[0]);
            } else {
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
            data.period_label = formatPeriodLabel(evaluation.start_date);

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

    // ── Chart rendering ───────────────────────────────────────────────────────
    async _renderAllCharts() {
        const d = this.state.data;
        if (!d) return;
        const employees = d.employees || [];

        this._renderChartA(d.task_summary_by_employee || []);
        this._renderChartB(d.project_progress || []);
        this._renderChartC(d.attendance_count || []);
        this._renderChartD(d.bug_count_by_employee || []);
        this._renderChartE(employees);
    }

    _renderChartA(employeeStats) {
        const el = this.refA.el;
        if (!el) return;
        const source = employeeStats;
        const { names, done, pending, total } = buildChartAData(source);
        this._charts.A = new Chart(el, {
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

    _renderChartB(projectProgress) {
        const el = this.refB.el;
        if (!el) return;

        const source = projectProgress;
        const { projects, pct, totals, done } = buildChartBData(source);

        this._charts.B = new Chart(el, {
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

    _renderChartC(attendanceData) {
        const el = this.refC.el;
        if (!el) return;
        const source = attendanceData;
        const data = buildChartCData(source);
        this._charts.C = new Chart(el, {
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
                        ticks: { stepSize: (this.state.data?.score_scale?.base || 10) / 10, font: { size: 10 } },
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

    _renderChartD(bugData) {
        const el = this.refD.el;
        if (!el) return;
        const source = bugData;
        const data = buildChartDData(source);
        this._charts.D = new Chart(el, {
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

    _renderChartE(employees) {
        const el = this.refE.el;
        if (!el) return;
        const empList = employees.slice(0, 6);
        const { labels, datasets } = buildChartEData(empList);
        this._charts.E = new Chart(el, {
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
                        min: 0, max: this.state.data?.score_scale?.base || 10,
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
