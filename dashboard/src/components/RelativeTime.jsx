import { formatRelativeTime, formatAbsoluteTime } from "../lib/format";

/**
 * Renders an ISO 8601 timestamp as relative text with the absolute time
 * available on hover (brief §3.3).
 *
 * Args:
 *   iso: ISO 8601 timestamp string, or a falsy value.
 *
 * Returns:
 *   A JSX span, or "—" when iso is falsy.
 *
 * Example:
 *   <RelativeTime iso="2026-09-21T03:53:17Z" /> # -> "5 phút trước" (tooltip: absolute time)
 */
export default function RelativeTime({ iso }) {
  if (!iso) return <span>—</span>;
  return <span title={formatAbsoluteTime(iso)}>{formatRelativeTime(iso)}</span>;
}
