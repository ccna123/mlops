// Demo-mode stand-in for src/lib/api.js's `api` object. Same method
// signatures, same ApiError shape, so every page can call whichever one
// `useClient()` (src/lib/useClient.js) hands it without branching internally.
import { ApiError } from "./api";
import * as fx from "./demoFixtures";
import { STAGE_ORDER } from "./constants";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const demoApi = {
  health: async () => {
    await delay(150);
    return fx.health;
  },

  triggerRun: async (payload) => {
    await delay(300);
    return {
      run_id: `manual__${new Date().toISOString()}`,
      dag_id: "ml_pipeline",
      state: "queued",
      _demoTaskType: payload.task_type,
    };
  },

  listRuns: async () => {
    await delay(200);
    return fx.runs;
  },

  getRun: async (runId) => {
    await delay(200);
    return (
      fx.runDetails[runId] ?? {
        run_id: runId,
        state: "queued",
        tasks: STAGE_ORDER.map((task_id) => ({ task_id, state: null, try_number: 0, duration: null })),
      }
    );
  },

  getLogs: async (runId, { stage }) => {
    await delay(250);
    return fx.logsByStage[stage] ?? { lines: [], truncated: false };
  },

  uploadDataset: async (file, datasetVersion, onProgress) => {
    for (let progress = 0.2; progress <= 1; progress += 0.2) {
      await delay(120);
      onProgress?.(progress);
    }
    return { dataset_version: datasetVersion, rows: 4, size_mb: 0.01 };
  },

  getPreview: async (datasetVersion) => {
    await delay(400);
    if (datasetVersion !== "v1") {
      throw new ApiError("notfound", 404, `no dataset at version ${datasetVersion}`);
    }
    return fx.preview;
  },

  listModels: async () => {
    await delay(200);
    return fx.models;
  },

  promote: async (name, version) => {
    await delay(300);
    return { name, version, alias: "champion" };
  },

  deleteModelVersion: async (name, version) => {
    await delay(300);
    return { name, version, deleted: true };
  },

  deleteModel: async (name) => {
    await delay(300);
    return { name, deleted: true };
  },

  triggerDriftRun: async () => {
    await delay(300);
    return { run_id: `manual__${new Date().toISOString()}`, dag_id: "monitoring_dag", state: "queued" };
  },

  driftLatest: async (modelName) => {
    await delay(200);
    if (modelName !== "house_price_regressor") {
      throw new ApiError("notfound", 404, `no drift report yet for ${modelName}`);
    }
    return fx.driftLatest;
  },

  driftHistory: async (modelName) => {
    await delay(200);
    if (modelName !== "house_price_regressor") {
      return { history: [] };
    }
    return fx.driftHistory;
  },
};
