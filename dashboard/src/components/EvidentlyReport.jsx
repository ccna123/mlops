import { useState } from "react";
import { Copy, ExternalLink, FileBarChart } from "lucide-react";

/**
 * Shows Evidently's own HTML report for one monitoring run.
 *
 * What it adds over the strips above: Evidently's per-column view — which
 * feature drifted, by how much, with the distributions drawn. What it cannot
 * do: say anything about the other runs, or about performance. It is the
 * detail behind one point of the history, so it sits next to the history
 * rather than in place of it.
 *
 * The report is fetched from the API, never from MinIO: the browser has no
 * storage credentials and must not get any (design doc section 8.2). It is
 * mounted only when asked for, because these reports run to megabytes, and
 * it renders inside a sandboxed iframe so its scripts cannot reach this page.
 *
 * Args:
 *   url: Where the API serves this run's report, or null when the current
 *     client cannot serve one (demo mode).
 *   reportKey: The object key, still shown so it can be found in MinIO.
 *     Null when the run wrote no report at all.
 *   onCopyKey: Called with `reportKey` when the copy button is pressed.
 *
 * Returns:
 *   A JSX element.
 */
export default function EvidentlyReport({ url, reportKey, onCopyKey }) {
  const [open, setOpen] = useState(false);

  if (!reportKey) {
    return (
      <div className="evidently-placeholder">
        <p>
          Lần đo này <b>không sinh báo cáo Evidently</b> — không có dự đoán nào trong cửa sổ theo dõi, nên monitor
          dừng trước khi chạy Evidently.
        </p>
      </div>
    );
  }

  return (
    <div className="evidently-box">
      <div className="evidently-head">
        <div>
          <p className="evidently-title">
            <FileBarChart size={15} /> Báo cáo Evidently (chi tiết từng cột)
          </p>
          <p className="evidently-sub">
            Đây là báo cáo feature drift của <b>riêng lần đo này</b> — không có lịch sử và không có performance.
          </p>
          <p className="evidently-sub">
            Evidently chỉ kết luận theo <b>tỉ lệ cột bị lệch</b> (ngưỡng 0,5), nên nó có thể ghi &ldquo;Dataset Drift
            is NOT detected&rdquo; trong khi ô Data drift ở trên báo cảnh báo: mức đó còn tính thêm luật độ lớn của
            Plan 4, vốn sinh ra để bắt trường hợp drift dồn vào một hai cột.
          </p>
        </div>
        <div className="evidently-actions">
          {url && (
            <button className="btn-secondary" onClick={() => setOpen((value) => !value)}>
              {open ? "Ẩn báo cáo" : "Xem báo cáo"}
            </button>
          )}
          {url && (
            <a className="btn-secondary" href={url} target="_blank" rel="noreferrer">
              <ExternalLink size={14} /> Tab mới
            </a>
          )}
        </div>
      </div>

      {open && url && (
        // allow-scripts without allow-same-origin: Evidently's charts need
        // JavaScript, but the report stays in an opaque origin and cannot
        // touch this page or its storage.
        <iframe
          className="evidently-frame"
          src={url}
          sandbox="allow-scripts"
          title="Báo cáo Evidently"
        />
      )}

      {!url && <p className="hint-note">Chế độ minh hoạ không có báo cáo thật để hiển thị.</p>}

      <div className="report-key-row">
        <code>{reportKey}</code>
        <button className="icon-btn" onClick={() => onCopyKey(reportKey)} aria-label="Sao chép">
          <Copy size={14} />
        </button>
      </div>
    </div>
  );
}
