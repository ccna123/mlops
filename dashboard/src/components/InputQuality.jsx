import StatusBadge from "./StatusBadge";
import { QUALITY_FACTOR } from "../lib/constants";
import { formatPercent } from "../lib/format";

/**
 * The fourth monitoring section, shown apart from the three drift tiles
 * (要件定義書 CN-44): can the input still be read the way the model reads it.
 *
 * Args:
 *   quality: The summary's `input_quality` ({level, columns}), or undefined
 *     for a report written before this section existed.
 *
 * Returns:
 *   A JSX element listing the offending columns, worst first.
 */
export default function InputQuality({ quality }) {
  return (
    <div className="severity-cell quality-cell">
      <p className="severity-cell-label" style={{ color: QUALITY_FACTOR.color }}>
        {QUALITY_FACTOR.label}
      </p>
      {quality ? (
        <StatusBadge value={quality.level} />
      ) : (
        <p className="hint-note">Báo cáo này được tính trước khi có mục data quality.</p>
      )}
      <p className="severity-cell-hint">{QUALITY_FACTOR.hint}</p>
      {quality?.columns?.length > 0 && (
        <table className="quality-table">
          <thead>
            <tr>
              <th>Cột</th>
              <th>Missing tăng</th>
              <th>Giá trị chưa từng gặp</th>
              <th>Mức</th>
            </tr>
          </thead>
          <tbody>
            {quality.columns.map((column) => (
              <tr key={column.column}>
                <td className="mono">{column.column}</td>
                <td>{column.missing_increase_points.toLocaleString("vi-VN", { maximumFractionDigits: 1 })} điểm %</td>
                <td>{column.unseen_share === null ? "—" : formatPercent(column.unseen_share)}</td>
                <td>
                  <StatusBadge value={column.level} size="sm" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
