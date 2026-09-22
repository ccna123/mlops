// The single function every screen goes through to reach the backend.
// API_BASE stays relative on purpose (brief §5.1): in dev, vite.config.js
// proxies "/api" to the real API service so the browser never makes a
// cross-origin request. Production still needs the project owner's call
// between serving this build from the API's own origin or adding
// CORSMiddleware — this file does not decide that.
const API_BASE = "/api";

/** Error thrown by every failed `api.*` call, carrying the classification
 * the UI needs to pick between NotFound / validation message / ErrorState. */
export class ApiError extends Error {
  constructor(kind, status, detail) {
    super(typeof detail === "string" ? detail : "Yêu cầu không hợp lệ.");
    this.kind = kind; // "notfound" | "validation" | "toolarge" | "system"
    this.status = status;
    this.detail = detail;
  }
}

function classifyStatus(status) {
  if (status === 404) return "notfound";
  if (status === 422) return "validation";
  if (status === 413) return "toolarge";
  // 409 means the request was fine but the registry's state refuses it — the
  // only case today is deleting the champion. Without this branch it would
  // fall through to "system" and the UI would cry "Hệ thống đang hỏng".
  if (status === 409) return "conflict";
  return "system";
}

/**
 * Calls one API endpoint and normalizes the response and its failure modes.
 *
 * Args:
 *   path: Path appended to API_BASE, including any query string. Path
 *     segments coming from user input (run ids, model names, dataset
 *     versions) must already be encodeURIComponent-escaped by the caller.
 *   options: Fetch options, plus a `timeout` in milliseconds (default
 *     30000; callers pass 6000 for `/health` per the brief).
 *
 * Returns:
 *   The parsed JSON body on a 2xx response.
 *
 * Raises:
 *   ApiError: On a non-2xx response (classified by status) or when the
 *     request could not complete at all (network error, CORS block, or
 *     timeout — all indistinguishable in the browser).
 */
async function request(path, { timeout = 30000, ...opts } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...opts, signal: controller.signal });
  } catch {
    clearTimeout(timer);
    throw new ApiError(
      "system",
      0,
      "Không kết nối được API. API có thể chưa chạy, hoặc quyết định CORS/serving ở brief §5.1 chưa xong."
    );
  }
  clearTimeout(timer);

  // A 500 from this API is text/plain ("Internal Server Error"), not JSON —
  // never call res.json() blindly on an error response (brief §3.2).
  const contentType = res.headers.get("content-type") || "";
  const raw = await res.text();
  let body = raw;
  if (contentType.includes("application/json") && raw) {
    try {
      body = JSON.parse(raw);
    } catch {
      body = raw;
    }
  }

  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : body;
    throw new ApiError(classifyStatus(res.status), res.status, detail);
  }
  return body;
}

export const api = {
  health: () => request("/health", { timeout: 6000 }),

  triggerRun: (payload) =>
    request("/pipeline/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listEstimators: () => request("/estimators"),

  listRuns: (limit = 3) => request(`/pipeline/runs?limit=${limit}`),

  getRun: (runId) => request(`/pipeline/runs/${encodeURIComponent(runId)}`),

  // fetch() cannot report upload progress, so this uses XMLHttpRequest
  // directly instead of going through request() (brief §4.3).
  uploadDataset: (file, datasetVersion, onProgress) =>
    new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      form.append("dataset_version", datasetVersion);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/data/upload`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        let body = xhr.responseText;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          // leave as raw text (e.g. plain-text 500)
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body);
          return;
        }
        const detail = body && typeof body === "object" && "detail" in body ? body.detail : body;
        reject(new ApiError(classifyStatus(xhr.status), xhr.status, detail));
      };
      xhr.onerror = () => reject(new ApiError("system", 0, "Không kết nối được API khi tải lên."));
      xhr.send(form);
    }),

  getPreview: (datasetVersion, rows = 200) =>
    request(`/data/${encodeURIComponent(datasetVersion)}/preview?rows=${rows}`),

  listModels: () => request("/models"),

  promote: (name, version) =>
    request(`/models/${encodeURIComponent(name)}/${encodeURIComponent(version)}/promote`, { method: "POST" }),

  deleteModelVersion: (name, version) =>
    request(`/models/${encodeURIComponent(name)}/${encodeURIComponent(version)}`, { method: "DELETE" }),

  deleteModel: (name) => request(`/models/${encodeURIComponent(name)}`, { method: "DELETE" }),

  triggerDriftRun: () => request("/drift/run", { method: "POST" }),

  listScenarios: () => request("/scenarios"),

  simulate: (payload) =>
    request("/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  simulateStatus: () => request("/simulate/status", { timeout: 6000 }),

  driftLatest: (modelName) => request(`/drift/latest?model_name=${encodeURIComponent(modelName)}`),

  driftHistory: (modelName, limit = 20) =>
    request(`/drift/history?model_name=${encodeURIComponent(modelName)}&limit=${limit}`),

  // A URL rather than a fetch: the Evidently report is megabytes of HTML that
  // an iframe loads itself, so pulling it through request() would only put it
  // in memory twice.
  driftReportUrl: (modelName, runId) =>
    `${API_BASE}/drift/report?model_name=${encodeURIComponent(modelName)}&run_id=${encodeURIComponent(runId)}`,
};
