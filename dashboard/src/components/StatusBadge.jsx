import { Check, AlertTriangle, XCircle, CircleDashed, HelpCircle } from "lucide-react";
import { STATUS_META, TASK_STATE_META } from "../lib/constants";

const ICONS = {
  check: Check,
  "alert-triangle": AlertTriangle,
  "x-circle": XCircle,
  "circle-dashed": CircleDashed,
};

/**
 * Renders one of the four drift/health severity states (brief §2).
 *
 * Args:
 *   value: One of "ok", "warning", "high", "insufficient_data", or an
 *     unrecognized string (rendered as a neutral gray badge with the raw
 *     text, never silently dropped).
 *   size: "md" (default) or "sm" for a denser layout.
 *
 * Returns:
 *   A JSX badge element carrying an icon and a text label — color is never
 *   the only channel, per the brief's accessibility rule.
 *
 * Example:
 *   <StatusBadge value="insufficient_data" /> # -> hatched badge, "chưa đủ dữ liệu"
 */
export default function StatusBadge({ value, size = "md" }) {
  const meta = STATUS_META[value];
  const sizeClass = size === "sm" ? "badge-sm" : "";
  if (!meta) {
    return (
      <span className={`badge badge-neutral ${sizeClass}`}>
        <HelpCircle size={14} /> {value ?? "—"}
      </span>
    );
  }
  const Icon = ICONS[meta.icon];
  return (
    <span className={`badge ${meta.badgeClass} ${sizeClass}`}>
      <Icon size={14} /> {meta.label}
    </span>
  );
}

/**
 * Renders an Airflow run/task state — a separate vocabulary from
 * StatusBadge (brief §2, last bullet): success/failed/running/queued/
 * skipped/upstream_failed/up_for_retry/null ("chưa chạy").
 *
 * Args:
 *   state: The task or run state string, or null for "not started yet".
 *   size: "md" (default) or "sm" for a denser layout.
 *
 * Returns:
 *   A JSX badge element. An unrecognized non-null value renders as a
 *   neutral gray badge holding the raw string, per the brief's fallback rule.
 *
 * Example:
 *   <TaskStateBadge state={null} /> # -> "chưa chạy", empty outline, no hatch
 */
export function TaskStateBadge({ state, size = "md" }) {
  const key = state === null || state === undefined ? "null" : state;
  const meta = TASK_STATE_META[key];
  const sizeClass = size === "sm" ? "badge-sm" : "";
  if (!meta) {
    return <span className={`badge badge-neutral ${sizeClass}`}>{state}</span>;
  }
  return <span className={`badge ${meta.badgeClass} ${sizeClass}`}>{meta.label}</span>;
}
