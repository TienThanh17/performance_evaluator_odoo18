/** @odoo-module **/
/**
 * kpi_helpers.js — Các hàm tiện ích dùng chung cho KPI Dashboard
 *
 * Được import bởi:
 *   - static/src/js/dept_kpi_dashboard.js
 *   - static/src/js/kpi_dashboard_page.js
 *   - static/src/components/kpi_tree_dashboard/kpi_tree_dashboard.js
 */

import { _t } from "@web/core/l10n/translation";

// ─────────────────────────────────────────────────────────────────────────────
// Score formatting
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format điểm số theo thang điểm cấu hình từ backend.
 *
 * @param {number|null} val - Giá trị điểm cần hiển thị
 * @param {object|null} scale - score_scale từ backend
 *   { suffix: string, base: number, display_multiplier: number }
 * @param {object} [opts]
 * @param {number|null} [opts.decimals=2] - Số chữ số thập phân; null = không làm tròn (raw)
 * @param {boolean} [opts.useMultiplier=false] - Có nhân display_multiplier trước khi hiển thị không
 * @returns {string}
 *
 * @example
 * // dept_kpi_dashboard: toFixed(2), không multiplier
 * formatScore(8.5, scale, { decimals: 2 })              // "8.50 / 10"
 *
 * // kpi_dashboard_page: toFixed linh hoạt, không multiplier
 * formatScore(8.5, scale, { decimals: 1 })              // "8.5 / 10"
 *
 * // kpi_tree_dashboard: có multiplier, không toFixed
 * formatScore(8.5, scale, { decimals: null, useMultiplier: true })  // "8.5 / 10"
 */
export function formatScore(val, scale, { decimals = 2, useMultiplier = false } = {}) {
    if (val == null) return "—";
    const safeScale = scale || { suffix: " / 10" };
    let score = Number(val) || 0;
    if (useMultiplier) {
        score = score * (safeScale.display_multiplier || 1);
    }
    const formatted = (decimals != null && !Number.isInteger(score)) 
        ? score.toFixed(decimals) 
        : String(score);
    return `${formatted}${safeScale.suffix || ""}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Quantitative KPI table helpers (dùng chung cho dept & individual dashboard)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format text cho cột Variance — thêm dấu "+" cho số dương.
 * @param {{ variance: number }} row
 * @returns {string}
 */
export function formatVariance(row) {
    if (row.variance === 0) return "0%";
    return row.variance > 0 ? `+${row.variance}%` : `${row.variance}%`;
}

/**
 * CSS class cho cột Variance.
 * @param {{ variance: number, linear_direction?: string }} row
 * @returns {string}
 */
export function varianceClass(row) {
    if (row.variance === 0) return "o_kpi_variance o_kpi_variance_good";
    const isGood = row.linear_direction === "lower_better" ? row.variance < 0 : row.variance > 0;
    return isGood ? "o_kpi_variance o_kpi_variance_exceeded" : "o_kpi_variance o_kpi_variance_bad";
}

/**
 * Text hiển thị cho cột Status.
 * @param {{ variance: number, linear_direction?: string }} row
 * @returns {string}
 */
export function statusText(row) {
    if (row.variance === 0) return _t("Achieved");
    const isGood = row.linear_direction === "lower_better" ? row.variance < 0 : row.variance > 0;
    return isGood ? _t("Exceeded") : _t("Not Met");
}

/**
 * CSS class cho badge Status.
 * @param {{ variance: number, linear_direction?: string }} row
 * @returns {string}
 */
export function statusClass(row) {
    if (row.variance === 0) return "o_kpi_status o_kpi_status_pass";
    const isGood = row.linear_direction === "lower_better" ? row.variance < 0 : row.variance > 0;
    return isGood ? "o_kpi_status o_kpi_status_excellent" : "o_kpi_status o_kpi_status_fail";
}
