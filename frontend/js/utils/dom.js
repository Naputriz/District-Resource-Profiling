/**
 * utils/dom.js
 * DOM manipulation utilities, HTML escaping to prevent XSS,
 * formatting helpers for numbers, choropleth colors, and simulation assumptions.
 */

export function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function formatAssumptionValue(v) {
  if (v === null || v === undefined) {
    return "-";
  }
  if (typeof v !== "object") {
    return String(v);
  }
  if (Array.isArray(v)) {
    return v.map(item => (typeof item === "object" ? JSON.stringify(item) : String(item))).join(", ");
  }
  if ("value" in v) {
    let out = String(v.value);
    if (v.unit) out += ` ${v.unit}`;
    const note = v.source || v.note || v.description;
    if (note) out += ` (${note})`;
    return out;
  }
  return Object.entries(v)
    .map(([subK, subV]) => `${subK}: ${typeof subV === "object" ? JSON.stringify(subV) : subV}`)
    .join(", ");
}

export function getChoroplethColor(score) {
  if (score >= 70) return "#10b981"; // Emerald
  if (score >= 50) return "#84cc16"; // Lime
  if (score >= 35) return "#f59e0b"; // Amber
  if (score >= 20) return "#f97316"; // Orange
  return "#f43f5e";                  // Rose/Red
}
