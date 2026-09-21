import { AlertOctagon, SearchX, RefreshCw } from "lucide-react";

/**
 * Renders one of the two error states the brief requires to stay visually
 * distinct (§3.2): "not found" (404, a normal outcome) versus "system is
 * broken" (500 or a network failure, worth retrying and checking HealthPill).
 *
 * Args:
 *   kind: "notfound" or "system" (default "system").
 *   detail: For "notfound", the API's `detail` string, shown verbatim.
 *   onRetry: Optional callback for the "system" variant's retry button.
 *
 * Returns:
 *   A JSX error block matching the given kind.
 *
 * Example:
 *   <ErrorState kind="notfound" detail="no run 'x' in DAG 'ml_pipeline'" />
 */
export default function ErrorState({ kind = "system", detail, onRetry }) {
  if (kind === "notfound") {
    return (
      <div className="error-state">
        <SearchX size={28} className="error-state-icon-neutral" />
        <p className="error-state-title">Không tìm thấy</p>
        <p className="error-state-desc">{typeof detail === "string" ? detail : "Không tìm thấy tài nguyên."}</p>
      </div>
    );
  }
  return (
    <div className="error-state error-state-danger">
      <AlertOctagon size={28} className="error-state-icon-danger" />
      <p className="error-state-title">Hệ thống đang hỏng</p>
      <p className="error-state-desc">
        Kiểm tra biểu tượng trạng thái ở góc trên để biết dịch vụ nào đang gặp vấn đề.
      </p>
      {onRetry && (
        <button className="btn-secondary" onClick={onRetry}>
          <RefreshCw size={14} /> Thử lại
        </button>
      )}
    </div>
  );
}
