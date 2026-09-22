import { HIGHER_IS_BETTER, LOWER_IS_BETTER } from "../lib/constants";
import { formatNumber } from "../lib/format";

/**
 * Decides whether a metric moving from one value to another got worse.
 *
 * Args:
 *   name: The metric key, e.g. "rmse".
 *   reference: The value measured on the test split.
 *   current: The value measured on live traffic.
 *
 * Returns:
 *   True when the move is bad, false when it is good, and null for a metric
 *   whose direction this build does not know — an unknown metric gets no
 *   colour rather than a guessed one.
 */
// Vietnamese grouping, so the change reads the same way as the values it
// sits next to: "33,5%" beside "152.620,1831", never "33.5%".
function formatPercentPoint(value) {
  return value.toLocaleString("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function isWorse(name, reference, current) {
  if (LOWER_IS_BETTER.has(name)) return current > reference;
  if (HIGHER_IS_BETTER.has(name)) return current < reference;
  return null;
}

/**
 * Compares what a model scored at acceptance against what it scores on live
 * traffic, side by side.
 *
 * Both numbers already existed but lived on two different screens, so reading
 * one against the other meant switching tabs and remembering a figure. They
 * are also not interchangeable: the test column is the held-out split from
 * the training run, the live column is real traffic in the monitoring window.
 * The header says so, because a table of eight-digit numbers with no labels
 * is exactly how someone concludes the wrong thing.
 *
 * Args:
 *   current: `current_metrics` from the drift summary.
 *   reference: `reference_metrics`, or null/undefined when the summary
 *     predates that field or was graded against another baseline.
 *
 * Returns:
 *   A JSX element, or null when there is nothing measured to show.
 */
export default function MetricComparison({ current, reference }) {
  const names = Object.keys(current ?? {});
  if (names.length === 0) return null;
  const hasReference = reference !== null && reference !== undefined;

  return (
    <div className="metric-compare">
      <table>
        <thead>
          <tr>
            <th>Chỉ số</th>
            <th>Trên tập test</th>
            <th>Trên traffic thật</th>
            <th>Chênh lệch</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => {
            const live = current[name];
            const base = hasReference ? reference[name] : undefined;
            const comparable = typeof base === "number" && base !== 0;
            const delta = comparable ? ((live - base) / Math.abs(base)) * 100 : null;
            const worse = comparable ? isWorse(name, base, live) : null;

            return (
              <tr key={name}>
                <th scope="row">{name.toUpperCase()}</th>
                <td>{typeof base === "number" ? formatNumber(base) : "—"}</td>
                <td>{formatNumber(live)}</td>
                <td className={worse === true ? "delta-worse" : worse === false ? "delta-better" : ""}>
                  {delta === null
                    ? "—"
                    : `${delta > 0 ? "+" : ""}${formatPercentPoint(delta)}%${
                        worse === true ? " (tệ hơn)" : worse === false ? " (tốt hơn)" : ""
                      }`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="metric-compare-note">
        Cột <b>tập test</b> là điểm lúc nghiệm thu model, đo trên phần dữ liệu tách riêng model chưa từng thấy —
        đúng con số ở màn Models. Cột <b>traffic thật</b> đo trên các request đã đi qua <code>serving</code> trong
        cửa sổ theo dõi.{" "}
        {hasReference
          ? "Mức Performance drift ở trên chính là chênh lệch này chấm theo ngưỡng của stage monitor."
          : "Báo cáo này không kèm điểm tập test (viết trước 22/9/2026), nên không so được."}
      </p>
    </div>
  );
}
