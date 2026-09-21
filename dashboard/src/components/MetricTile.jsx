import { ArrowDown, ArrowUp } from "lucide-react";
import { formatNumber } from "../lib/format";
import { LOWER_IS_BETTER as LOWER_SET, HIGHER_IS_BETTER as HIGHER_SET } from "../lib/constants";

/**
 * Renders one metric as a large number with its name and a good/bad
 * direction hint. Metric keys are read from the data, never hardcoded
 * (brief §4.4 calls out a prior bug that assumed a fixed metric set).
 *
 * Args:
 *   name: The metric key exactly as returned by the API (e.g. "rmse").
 *   value: The metric's numeric value.
 *
 * Returns:
 *   A JSX tile. Unknown metric names render with no direction arrow.
 *
 * Example:
 *   <MetricTile name="rmse" value={98175.1} /> # -> "RMSE  98.175,103 ↓"
 */
export default function MetricTile({ name, value }) {
  const direction = LOWER_SET.has(name) ? "down" : HIGHER_SET.has(name) ? "up" : null;
  return (
    <div className="metric-tile">
      <div className="metric-tile-label">{name}</div>
      <div className="metric-tile-value" title={String(value)}>
        <span>{formatNumber(value)}</span>
        {direction === "down" && <ArrowDown size={16} className="metric-good" aria-label="thấp hơn là tốt hơn" />}
        {direction === "up" && <ArrowUp size={16} className="metric-good" aria-label="cao hơn là tốt hơn" />}
      </div>
    </div>
  );
}
