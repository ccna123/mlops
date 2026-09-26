import { primaryMetric } from "../lib/driftReading";
import { formatNumber } from "../lib/format";

const GROUP_LABELS = { city: "Thành phố", property_type: "Loại bất động sản" };

/**
 * Metrics per city and per property type on live traffic, next to the same
 * group on the test set (要件定義書 CN-45). For reading only: no level and no
 * gate is decided on these. The overall metric can hide one city that got
 * clearly worse; this is where it shows.
 *
 * Args:
 *   groups: The summary's `group_metrics` ({current, reference}), or undefined.
 *   taskType: Decides which metric is shown.
 *
 * Returns:
 *   A JSX element, or null when there is nothing measured per group.
 */
export default function GroupMetrics({ groups, taskType }) {
  const metric = primaryMetric(taskType);
  const current = groups?.current;
  if (!metric || !current) return null;
  const reference = groups.reference ?? {};

  return (
    <div className="group-metrics">
      <p className="drift-strip-label">{metric.toUpperCase()} theo nhóm</p>
      <p className="drift-strip-hint">
        Trên traffic thực tế, đặt cạnh cùng nhóm trên test set. Chỉ để xem — không dùng để xếp mức.
      </p>
      {Object.entries(current).map(([column, byGroup]) => (
        <div className="table-scroll" key={column}>
          <table>
            <thead>
              <tr>
                <th>{GROUP_LABELS[column] ?? column}</th>
                <th>SỐ CẶP</th>
                <th>TRÊN TRAFFIC</th>
                <th>TRÊN TEST SET</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byGroup).map(([name, values]) => {
                const onTest = reference[column]?.[name]?.[metric];
                return (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{formatNumber(values.n)}</td>
                    <td>
                      {values.insufficient_data ? (
                        <span className="badge badge-insufficient badge-sm">chưa đủ dữ liệu</span>
                      ) : (
                        formatNumber(values[metric])
                      )}
                    </td>
                    <td>{onTest === undefined ? "—" : formatNumber(onTest)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
