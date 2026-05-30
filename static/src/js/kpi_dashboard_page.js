/** @odoo-module **/
/**
 * kpi_dashboard_page.js  –  Standalone KPI Dashboard Client Action
 *
 * Registered as the "kpi_individual_dashboard" client action tag.
 * Template: static/src/xml/kpi_dashboard_template.xml
 *           "performance_evaluator.KpiDashboardStandalone"
 */

import {
    Component,
    onMounted,
    onWillStart,
    useRef,
    useState,
    useEffect,
} from "@odoo/owl";
import { loadBundle, loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user"; // singleton – no service needed
import { _t } from "@web/core/l10n/translation";
import {
    formatScore as _formatScore,
    formatVariance as _formatVariance,
    varianceClass as _varianceClass,
    statusText as _statusText,
    statusClass as _statusClass,
} from "@custom_adecsol_hr_performance_evaluator/utils/kpi_helpers";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function formatHour(h) {
    if (h == null) return "--";
    const hours = Math.floor(h);
    const mins = Math.round((h - hours) * 60);
    return hours + ":" + String(mins).padStart(2, "0");
}

const PERIOD_LABELS = {
    monthly: _t("Monthly"),
    quarterly: _t("Quarterly"),
    biannual: _t("Half-Yearly"),
    yearly: _t("Yearly"),
};

const COLOR_BLUE = "#3b82f6";
const COLOR_GREEN = "#22c55e";
const COLOR_RED = "#ef4444";
const COLOR_INDIGO = "#6366f1";

// Group that grants manager-level access
const MANAGER_GROUP = "custom_adecsol_hr_performance_evaluator.group_manager";
const HR_GROUP = "custom_adecsol_hr_performance_evaluator.group_hr";
const ADMIN_GROUP = "custom_adecsol_hr_performance_evaluator.group_admin";

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
export class KpiDashboard extends Component {
    static template = "performance_evaluator.KpiDashboardStandalone";
    static props = ["*"]; // client action props
    static CHART_RENDERERS = {
        line: "_renderLineChart",
        bar: "_renderBarChart",
        doughnut: "_renderDoughnutChart",
    };

    setup() {
        this.orm = useService("orm");

        this.dashboardRootRef = useRef("dashboardRoot");
        this.radarRef = useRef("spiderChart");

        // 1. Lấy context từ action props (bắt lỗi an toàn nếu mở trực tiếp không qua nút bấm)
        const actionContext = this.props.action?.context || {};

        // 2. Hứng ID nhân viên (nếu không có thì trả về false để load tất cả)
        const passedEmployeeId = actionContext.default_employee_id || false;
        const passedEvaluationId = actionContext.default_evaluation_id || false;

        this.state = useState({
            employee_id: passedEmployeeId, // Dashboard sẽ lấy ID này để gọi xuống Python filter data
            passedEvaluationId: passedEvaluationId,
            phase: "evals", // "evals" | "dashboard" | "done" | "error"
            isManager: false,
            isHR: false,
            isAdmin: false,
            employees: [], // [{id, name}] – only for managers
            selectedEmployeeId: null, // null = current user's employee
            departments: [], // Thêm: Lưu danh sách phòng ban
            selectedDepartmentId: null, // Thêm: Phòng ban đang chọn
            filteredEmployees: [], // Thêm: Nhân viên ĐÃ LỌC theo phòng ban để show ra view
            evaluations: [],
            selectedEvaluationId: null,
            data: null,
            errorMsg: "",
            chartErrorMsg: "",
        });

        this._charts = {};
        this._chartRenderFrame = null;
        this._chartRenderFrameNested = null;

        onWillStart(async () => {
            await this._loadChartJs();
            // await loadJS("https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js");

            // Chạy song song tất cả các kiểm tra quyền
            const [isManager, isHR, isAdmin] = await Promise.all([
                user.hasGroup(MANAGER_GROUP),
                user.hasGroup(HR_GROUP),
                user.hasGroup(ADMIN_GROUP),
            ]);

            Object.assign(this.state, { isManager, isHR, isAdmin });

            // 2. If manager, prefetch the employee list
            if (this.state.isManager || this.state.isHR || this.state.isAdmin) {
                await this._loadEmployees();
            }

            // 3. Load evaluations (for current user or first employee)
            await this._loadEvaluations();
        });

        onMounted(async () => {
            if (this.state.selectedEvaluationId) {
                await this._loadDashboard();
            }
        });

        useEffect(
            () => {
                if (this.state.phase === "done" && this.state.data) {
                    this._scheduleChartRender();
                } else {
                    this._destroyCharts();
                }
                return () => this._cancelScheduledChartRender();
            },
            () => [this.state.phase, this.state.data], // Chạy lại effect này nếu phase hoặc data thay đổi
        );
    }

    async _loadChartJs() {
        if (window.Chart) return;
        this.state.chartErrorMsg = "";
        try {
            await loadBundle("web.chartjs_lib");
        } catch (bundleError) {
            console.warn("KPI Dashboard: failed to load web.chartjs_lib bundle", bundleError);
        }
        if (window.Chart) return;

        try {
            await loadJS("/web/static/lib/Chart/Chart.js");
        } catch (assetError) {
            console.error("KPI Dashboard: failed to load local Chart.js asset", assetError);
        }
        if (!window.Chart) {
            this.state.chartErrorMsg = _t(
                "Chart library could not be loaded, so dashboard charts are unavailable.",
            );
        }
    }

    // ── Data loaders ─────────────────────────────────────────────────────────
    async _loadEmployees() {
        try {
            // 1. Lấy thông tin nhân viên của user đang đăng nhập
            const myEmployee = await this.orm.searchRead(
                "hr.employee",
                [["user_id", "=", user.userId]],
                ["id", "name", "department_id"],
                { limit: 1 },
            );

            // 2. Load danh sách phòng ban
            let deptDomain = [["active", "=", true]];
            if (this.state.isManager && !this.state.isHR && !this.state.isAdmin) {
                deptDomain.push(["manager_id.user_id", "=", user.userId]);
            }

            const departments = await this.orm.searchRead(
                "hr.department",
                deptDomain,
                ["id", "name", "member_ids"],
                { order: "name asc" },
            );
            this.state.departments = departments;
            const managerDepartmentIds = departments.map((dept) => dept.id);

            // 3. Load toàn bộ nhân viên (kèm theo department_id)
            let empDomain = [["active", "=", true]];
            if (this.state.isManager && !this.state.isHR && !this.state.isAdmin) {
                if (managerDepartmentIds.length) {
                    empDomain.push(["department_id", "in", managerDepartmentIds]);
                } else {
                    empDomain.push(["id", "=", 0]);
                }
            }

            const employees = await this.orm.searchRead(
                "hr.employee",
                empDomain,
                ["id", "name", "department_id"],
                { order: "name asc", limit: 500 }, // Tăng limit nếu công ty đông
            );
            this.state.employees = employees;

            if (departments.length > 0) {
                this.state.selectedDepartmentId = departments[0].id;
                const deptMembers = employees.filter(
                    (e) => e.department_id && e.department_id[0] === departments[0].id,
                );
                if (
                    myEmployee.length &&
                    deptMembers.find((e) => e.id === myEmployee[0].id)
                ) {
                    this.state.selectedEmployeeId = myEmployee[0].id;
                } else if (deptMembers.length > 0) {
                    this.state.selectedEmployeeId = deptMembers[0].id;
                } else if (employees.length > 0) {
                    this.state.selectedEmployeeId = employees[0].id;
                }
            } else {
                this.state.selectedDepartmentId = null;
                this.state.selectedEmployeeId = null;
            }

            // Nếu có passedEmployeeId, override selectedEmployeeId và selectedDepartmentId
            if (this.state.employee_id) {
                const targetEmp = employees.find(
                    (e) => e.id === this.state.employee_id,
                );
                if (targetEmp) {
                    this.state.selectedEmployeeId = targetEmp.id;
                    if (targetEmp.department_id) {
                        this.state.selectedDepartmentId = targetEmp.department_id[0];
                    }
                }
            }

            // 4. Lọc nhân viên theo phòng ban
            this._filterEmployees();
        } catch (e) {
            // Non-fatal: manager selector just won't appear
            console.warn("KPI Dashboard: could not load employee list", e);
        }
    }

    // Hàm mới: Lọc nhân viên dựa trên phòng ban đang chọn
    _filterEmployees() {
        if (this.state.selectedDepartmentId) {
            this.state.filteredEmployees = this.state.employees.filter(
                (emp) =>
                    emp.department_id &&
                    emp.department_id[0] === this.state.selectedDepartmentId,
            );
        } else {
            // Nếu chọn "Tất cả phòng ban"
            this.state.filteredEmployees = this.state.employees;
        }

        // Kiểm tra xem selectedEmployeeId hiện tại có nằm trong list vừa lọc không
        const empExists = this.state.filteredEmployees.find(
            (e) => e.id === this.state.selectedEmployeeId,
        );

        // Nếu không có, tự động nhảy sang nhân viên đầu tiên của phòng ban đó
        if (!empExists && this.state.filteredEmployees.length > 0) {
            this.state.selectedEmployeeId = this.state.filteredEmployees[0].id;
        } else if (!empExists) {
            this.state.selectedEmployeeId = null; // Phòng ban này không có ai
        }
    }

    async _loadEvaluations() {
        try {
            const fields = [
                "id",
                "name",
                "period_type",
                "period_id",
                "start_date",
                "end_date",
                "performance_score",
                "performance_level",
                "final_score",
                "final_level",
                "state",
                "employee_id",
            ];

            // Domain: filter by selected employee (manager) or by current user
            let domain;
            if (
                (this.state.isManager || this.state.isHR || this.state.isAdmin) &&
                this.state.selectedEmployeeId
            ) {
                domain = [["employee_id", "=", this.state.selectedEmployeeId]];
            } else if (this.state.isManager && !this.state.isHR && !this.state.isAdmin) {
                domain = [["id", "=", 0]];
            } else if (this.state.employee_id) {
                // Được truyền thẳng employee_id từ context (ví dụ: mở từ form nhân viên)
                domain = [["employee_id", "=", this.state.employee_id]];
            } else {
                domain = [["employee_id.user_id", "=", user.userId]];
            }

            const evals = await this.orm.searchRead(
                "hr.performance.evaluation",
                domain,
                fields,
                { order: "start_date desc", limit: 500, context: { active_test: false } }, // Thêm dòng này để lấy cả record archived
            );

            this.state.evaluations = evals;

            if (evals.length > 0) {
                // Kiểm tra xem passedEvaluationId có khớp với evaluation nào trong danh sách không
                const targetEval = evals.find(e => e.id === this.state.passedEvaluationId);

                if (targetEval) {
                    this.state.selectedEvaluationId = targetEval.id;
                    // Reset lại để các lần user tự chọn nhân viên khác thì nó fallback về evals[0]
                    this.state.passedEvaluationId = false;
                } else {
                    this.state.selectedEvaluationId = evals[0].id;
                }
                this.state.phase = "dashboard";
            } else {
                this.state.data = null;
                this.state.phase = "done";
            }
        } catch (e) {
            this.state.errorMsg = _t("Could not load evaluations.");
            this.state.phase = "error";
        }
    }

    async _loadDashboard() {
        this.state.phase = "dashboard";
        this._destroyCharts();
        try {
            const data = await this.orm.call(
                "hr.performance.evaluation",
                "get_dashboard_data",
                [[this.state.selectedEvaluationId]],
            );
            this.state.data = data;
            this.state.phase = "done";

            // await Promise.resolve();
            // Ép trình duyệt đợi đến frame tiếp theo (đảm bảo thẻ <canvas> đã xuất hiện trên DOM)
            // await new Promise(resolve => requestAnimationFrame(resolve));

            // this._renderCharts();
        } catch (e) {
            console.error("KPI Dashboard: could not load dashboard data", e);
            this.state.errorMsg =
                e?.data?.message || e?.message || _t("Could not load dashboard data.");
            this.state.phase = "error";
        }
    }

    // ── Event handlers ───────────────────────────────────────────────────────
    async onSelectDepartment(ev) {
        const val = ev.target.value;
        // Nếu val rỗng ("") tức là chọn "Tất cả phòng ban"
        this.state.selectedDepartmentId = val ? parseInt(val, 10) : null;

        // Gọi hàm lọc lại danh sách nhân viên
        this._filterEmployees();

        // Reset data và load lại evaluation của nhân viên mới
        this.state.evaluations = [];
        this.state.selectedEvaluationId = null;
        this.state.data = null;
        await this._loadEvaluations();
        if (this.state.selectedEvaluationId) {
            await this._loadDashboard();
        }
    }

    async onSelectEmployee(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id || id === this.state.selectedEmployeeId) return;
        this.state.selectedEmployeeId = id;
        this.state.evaluations = [];
        this.state.selectedEvaluationId = null;
        this.state.data = null;
        await this._loadEvaluations();
        if (this.state.selectedEvaluationId) {
            await this._loadDashboard();
        }
    }

    async onSelectEval(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id || id === this.state.selectedEvaluationId) return;
        this.state.selectedEvaluationId = id;
        await this._loadDashboard();
    }

    // ── Computed helpers (called from template) ──────────────────────────────
    get scoreScale() {
        return this.state.data?.score_scale || { base: 10, suffix: " / 10" };
    }

    hasWidget(code) {
        const widgetMap = this.state.data?.widget_map || {};
        return !Object.keys(widgetMap).length || Boolean(widgetMap[code]);
    }

    /** Hiển thị điểm số, mặc định 2 chữ số thập phân. */
    formatScore(value, decimals = 2) {
        return _formatScore(value, this.scoreScale, { decimals });
    }

    scorePct(value) {
        const base = Number(this.scoreScale.base || 10);
        return Math.max(0, Math.min(100, ((Number(value) || 0) / base) * 100));
    }

    get scoreText() {
        return this.formatScore(this.state.data ? this.state.data.performance_score : 0);
    }

    get scoreRingStyle() {
        const score = this.state.data ? this.state.data.performance_score : 0;
        const pct = this.scorePct(score);
        const level = this.state.data ? this.state.data.performance_level : "fail";
        const color =
            level === "excellent"
                ? COLOR_BLUE
                : level === "pass"
                    ? COLOR_GREEN
                    : COLOR_RED;
        return "background: conic-gradient(" + color + " " + pct + "%, #e5e7eb 0)";
    }

    get levelLabel() {
        // Trả về thẳng Label đã được Python dịch
        return this.state.data ? this.state.data.performance_level_label : "";
    }

    // Nếu bạn có hàm set CSS dựa trên level, hãy giữ nguyên dùng key gốc:
    get levelClass() {
        const level = this.state.data ? this.state.data.performance_level : "";
        // Ví dụ: return level === 'fail' ? 'text-danger' : 'text-success';
        return "o_kpi_level_badge o_kpi_level_" + level;
    }

    get deptScoreText() {
        if (!this.state.data || !this.state.data.has_dept_evaluation) return "N/A";
        return this.formatScore(this.state.data.dept_kpi_score || 0);
    }

    get individualWeightText() {
        const weight = this.state.data ? this.state.data.individual_weight : 1;
        return Math.round((weight || 0) * 100) + "%";
    }

    get deptWeightText() {
        const weight = this.state.data ? this.state.data.dept_weight : 0;
        return Math.round((weight || 0) * 100) + "%";
    }

    get deptStatusClass() {
        const level = this._levelFromScore(
            this.state.data ? this.state.data.dept_kpi_score : 0,
        );
        return "o_kpi_level_badge o_kpi_level_" + level;
    }

    get deptStatusLabel() {
        if (!this.state.data || !this.state.data.has_dept_evaluation) return "N/A";
        const level = this._levelFromScore(this.state.data.dept_kpi_score || 0);
        const labels = { excellent: "Excellent", pass: "Pass", fail: "Fail" };
        return labels[level];
    }

    get deptTooltip() {
        if (this.state.data?.has_dept_evaluation) {
            return _t("Department score participates in the final KPI formula.");
        }
        return _t(
            "No department evaluation is linked. The individual KPI receives 100% weight.",
        );
    }

    get formulaText() {
        return `${this.individualWeightText} Cá nhân + ${this.deptWeightText} Phòng ban`;
    }

    _levelFromScore(score) {
        const thresholds = this.state.data?.thresholds || { excellent: 9, pass: 5 };
        if (score >= thresholds.excellent) return "excellent";
        if (score >= thresholds.pass) return "pass";
        return "fail";
    }

    // ── Final Score helpers (dùng cho breakdown section trong template) ────────
    get finalScoreText() {
        // Trả về final_score đã được làm tròn 2 chữ số thập phân
        return this.formatScore(this.state.data ? this.state.data.final_score : 0, 2);
    }

    get finalLevelClass() {
        // Class CSS tương ứng với final_level (excellent / pass / fail)
        const level = this.state.data ? this.state.data.final_level : "fail";
        return "o_kpi_level_badge o_kpi_level_" + level;
    }

    get finalLevelLabel() {
        if (this.state.data?.final_level_label) return this.state.data.final_level_label;
        const level = this.state.data ? this.state.data.final_level : "fail";
        const labels = { excellent: "Excellent", pass: "Pass", fail: "Fail" };
        return labels[level] || level;
    }

    // ── Quantitative table helpers ────────────────────────────────────────────
    // 1. Format text cho cột Variance (Thêm dấu + cho số dương)
    formatVariance(row) { return _formatVariance(row); }

    // 2. Màu sắc cho cột Variance
    varianceClass(row) { return _varianceClass(row); }

    // 3. Chữ hiển thị cho cột Status
    statusText(row) { return _statusText(row); }

    // 4. Màu nền cho Badge Status
    statusClass(row) { return _statusClass(row); }

    periodLabel(periodType) {
        return PERIOD_LABELS[periodType] || periodType;
    }

    formatHour(h) {
        return formatHour(h);
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
            datasets.some((dataset) => Array.isArray(dataset?.data) && dataset.data.length)
        );
    }

    evalOptionLabel(ev) {
        let periodLabel = "";

        // Kiểm tra nếu period là monthly và có start_date
        if (ev.period_type === "monthly" && ev.start_date) {
            // start_date có dạng "YYYY-MM-DD", tách chuỗi lấy phần tử thứ 2 (index 1)
            const monthString = ev.start_date.split("-")[1];

            // parseInt để bỏ số 0 ở đầu (ví dụ: "05" thành 5)
            const monthNumber = parseInt(monthString, 10);

            // Dùng _t() để có thể dịch từ "Month" sang "Tháng" trong file .po
            periodLabel = _t("Month ") + monthNumber;
        } else {
            // Fallback về logic cũ cho các period khác (yearly, quarterly...)
            periodLabel = PERIOD_LABELS[ev.period_type] || ev.period_type;
        }

        return (
            ev.name +
            " — " +
            periodLabel
        );
    }

    // ── Chart rendering ──────────────────────────────────────────────────────
    _scheduleChartRender() {
        this._cancelScheduledChartRender();
        this._chartRenderFrame = requestAnimationFrame(() => {
            this._chartRenderFrameNested = requestAnimationFrame(() => {
                this._renderCharts();
            });
        });
    }

    _cancelScheduledChartRender() {
        if (this._chartRenderFrame) {
            cancelAnimationFrame(this._chartRenderFrame);
            this._chartRenderFrame = null;
        }
        if (this._chartRenderFrameNested) {
            cancelAnimationFrame(this._chartRenderFrameNested);
            this._chartRenderFrameNested = null;
        }
    }

    _renderCharts() {
        const Chart = window.Chart;
        const d = this.state.data;
        if (!Chart || !d) {
            if (!Chart && !this.state.chartErrorMsg) {
                this.state.chartErrorMsg = _t(
                    "Chart library is not available in the browser.",
                );
            }
            return;
        }
        this._destroyCharts();

        const radarEl = this.radarRef.el;
        if (radarEl && d.spider_web?.labels?.length) {
            try {
                const spider = this._renderSpiderChart(radarEl, d.spider_web);
                if (spider) {
                    this._charts.spider = spider;
                }
            } catch (error) {
                console.error("KPI Dashboard: failed to render spider chart", error, d.spider_web);
                this.state.chartErrorMsg = _t(
                    "Some charts could not be rendered. Check browser console for details.",
                );
            }
        }

        for (const chartInfo of d.dynamic_charts || []) {
            if (!this.chartHasData(chartInfo)) continue;
            const rootEl = this._getDashboardRootEl();
            const escapedKey = window.CSS?.escape
                ? window.CSS.escape(chartInfo.key)
                : chartInfo.key;
            const canvas = rootEl?.querySelector(
                `canvas[data-chart-key="${escapedKey}"]`,
            );
            if (!canvas) {
                console.warn(
                    "KPI Dashboard: canvas not found for chart",
                    chartInfo.key,
                    {
                        rootReady: Boolean(rootEl),
                        availableKeys: this._getAvailableChartKeys(rootEl),
                    },
                );
                continue;
            }

            const rendererName = this.constructor.CHART_RENDERERS[chartInfo.chart_type];
            if (!rendererName || typeof this[rendererName] !== "function") continue;

            try {
                const instance = this[rendererName](canvas, chartInfo);
                if (instance) {
                    this._charts[chartInfo.key] = instance;
                }
            } catch (error) {
                console.error(
                    "KPI Dashboard: failed to render chart",
                    chartInfo.key,
                    chartInfo,
                    {
                        width: canvas.clientWidth,
                        height: canvas.clientHeight,
                    },
                    error,
                );
                this.state.chartErrorMsg = _t(
                    "Some charts could not be rendered. Check browser console for details.",
                );
            }
        }
    }

    _getDashboardRootEl() {
        return (
            this.dashboardRootRef.el ||
            this.radarRef.el?.closest(".o_kpi_dashboard_page") ||
            null
        );
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
            const accentColor = index === 0 ? COLOR_GREEN : COLOR_RED;
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
        const yTicks = { font: { size: 10 } };
        if (yAxis.stepSize != null) {
            yTicks.stepSize = yAxis.stepSize;
        }
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
                    legend: {
                        display: datasets.length > 1,
                        position: "top",
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const value = context.parsed.y;
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
            backgroundColor: COLOR_BLUE,
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
        return new Chart(ctx, {
            type: "doughnut",
            data: {
                labels,
                datasets: chartData.datasets || [],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: chartInfo.chart_meta?.cutout || "75%",
                plugins: {
                    legend: { display: false },
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

    _renderSpiderChart(canvas, data) {
        const Chart = window.Chart;
        const ctx = canvas?.getContext?.("2d");
        if (!ctx) return null;
        return new Chart(ctx, {
            type: "radar",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: _t("Score"),
                        data: data.scores,
                        backgroundColor: "rgba(99,102,241,0.25)",
                        borderColor: COLOR_INDIGO,
                        borderWidth: 2,
                        pointBackgroundColor: COLOR_INDIGO,
                        pointRadius: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                layout: {
                    padding: 30,
                },
                plugins: { legend: { display: false } },
                scales: {
                    r: {
                        min: 0,
                        max: data.max || this.scoreScale.base || 10,
                        ticks: {
                            stepSize: (data.max || this.scoreScale.base || 10) / 5,
                            font: { size: 10 },
                        },
                        pointLabels: {
                            font: { size: 11 },
                            callback: function (label) {
                                const maxLength = 15;
                                if (typeof label === "string" && label.length > maxLength) {
                                    const words = label.split(" ");
                                    let lines = [];
                                    let currentLine = "";

                                    words.forEach((word) => {
                                        if ((currentLine + word).length > maxLength) {
                                            if (currentLine) lines.push(currentLine.trim());
                                            currentLine = `${word} `;
                                        } else {
                                            currentLine += `${word} `;
                                        }
                                    });
                                    if (currentLine) lines.push(currentLine.trim());

                                    return lines;
                                }
                                return label;
                            },
                        },
                        grid: { color: "rgba(0,0,0,0.07)" },
                    },
                },
            },
        });
    }

    _destroyCharts() {
        this._cancelScheduledChartRender();
        for (const k of Object.keys(this._charts)) {
            try {
                this._charts[k].destroy();
            } catch (_) { }
        }
        this._charts = {};
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Register as client action
// ─────────────────────────────────────────────────────────────────────────────
registry.category("actions").add("kpi_individual_dashboard", KpiDashboard);
