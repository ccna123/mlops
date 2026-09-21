/**
 * Renders a placeholder skeleton so a screen never shows blank white while
 * data is loading (brief §3.3 — a pipeline run is not instant).
 *
 * Args:
 *   rows: Number of skeleton lines to render (default 3).
 *   className: Extra class names appended to the wrapper.
 *
 * Returns:
 *   A JSX block of pulsing placeholder lines with tapering widths.
 *
 * Example:
 *   <LoadingSkeleton rows={5} /> # -> 5 pulsing gray bars
 */
export default function LoadingSkeleton({ rows = 3, className = "" }) {
  return (
    <div className={`skeleton-stack ${className}`}>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton-line" style={{ width: `${88 - index * 12}%` }} />
      ))}
    </div>
  );
}
