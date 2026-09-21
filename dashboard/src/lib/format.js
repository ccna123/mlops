const numberFormatter = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 4 });
const percentFormatter = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 });

/**
 * Formats a number using vi-VN grouping, per the brief's §5.2 convention.
 *
 * Args:
 *   value: The number to format, or null/undefined for a missing value.
 *
 * Returns:
 *   The formatted string, or "—" when value is missing or not a number.
 *
 * Example:
 *   formatNumber(2012000) # -> "2.012.000"
 */
export function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return numberFormatter.format(value);
}

/**
 * Formats a 0..1 fraction as a vi-VN percentage.
 *
 * Args:
 *   value: The fraction to format, or null/undefined for a missing value.
 *
 * Returns:
 *   The formatted percentage string, or "—" when value is missing.
 *
 * Example:
 *   formatPercent(0.632155) # -> "63,22%"
 */
export function formatPercent(value) {
  if (value === null || value === undefined) return "—";
  return `${percentFormatter.format(value * 100)}%`;
}

/**
 * Formats an ISO 8601 timestamp as relative Vietnamese text.
 *
 * Args:
 *   iso: ISO 8601 timestamp string, or a falsy value for "unknown".
 *
 * Returns:
 *   A short relative-time string ("3 phút trước"), or "—" when iso is falsy.
 *
 * Example:
 *   formatRelativeTime("2026-09-21T03:00:00Z") # -> "5 phút trước" (depends on now)
 */
export function formatRelativeTime(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 5) return "vừa xong";
  if (seconds < 60) return `${seconds} giây trước`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} phút trước`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} giờ trước`;
  return `${Math.floor(seconds / 86400)} ngày trước`;
}

/**
 * Formats an ISO 8601 timestamp as an absolute vi-VN date and time.
 *
 * Args:
 *   iso: ISO 8601 timestamp string, or a falsy value for "unknown".
 *
 * Returns:
 *   A localized absolute date-time string, or "—" when iso is falsy.
 *
 * Example:
 *   formatAbsoluteTime("2026-09-21T03:53:17.127926+00:00") # -> "21 thg 9, 2026, 03:53:17"
 */
export function formatAbsoluteTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("vi-VN", { dateStyle: "medium", timeStyle: "medium" });
}

/**
 * Formats a duration in seconds as Vietnamese minutes/seconds text.
 *
 * Args:
 *   seconds: Duration in seconds, or null/undefined for an unknown duration.
 *
 * Returns:
 *   The formatted duration string, or "—" when seconds is missing.
 *
 * Example:
 *   formatDuration(94) # -> "1 phút 34 giây"
 */
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} giây`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes} phút ${rest} giây`;
}

/**
 * Extracts the trigger timestamp embedded in an Airflow run id.
 *
 * Airflow builds run ids as `<type>__<ISO 8601>` (e.g.
 * `manual__2026-09-21T10:48:59.064443+00:00`). A queued run has no
 * `started_at` yet, so this is the only way to know how long it has
 * actually been waiting — reading the clock when the page first saw it
 * would restart the count on every reload.
 *
 * Args:
 *   runId: The Airflow run id string.
 *
 * Returns:
 *   A Date, or null when runId is missing or carries no parseable
 *   timestamp (a run id typed by hand in the Airflow UI can be anything).
 *
 * Example:
 *   runIdTimestamp("manual__2026-09-21T10:48:59.064443+00:00") # -> Date(2026-09-21T10:48:59Z)
 *   runIdTimestamp("my-custom-run") # -> null
 */
export function runIdTimestamp(runId) {
  if (typeof runId !== "string") return null;
  const separator = runId.indexOf("__");
  if (separator === -1) return null;
  const parsed = new Date(runId.slice(separator + 2));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Computes elapsed duration in seconds between two ISO timestamps.
 *
 * Args:
 *   startIso: Start timestamp, or null.
 *   endIso: End timestamp, or null (still running / not observed).
 *
 * Returns:
 *   Elapsed seconds as a number, or null when either timestamp is missing.
 *
 * Example:
 *   durationBetween("2026-09-20T13:38:01Z", "2026-09-20T13:38:44Z") # -> 43
 */
export function durationBetween(startIso, endIso) {
  if (!startIso || !endIso) return null;
  return (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000;
}
