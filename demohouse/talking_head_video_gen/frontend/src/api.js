import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const http = axios.create({
  baseURL,
  timeout: 300000,
});

export const createSession = async () => (await http.post("/api/session")).data;
export const getSession = async (sessionId) => (await http.get(`/api/session/${sessionId}`)).data;

export const uploadAsset = async (sessionId, kind, file) => {
  const form = new FormData();
  form.append("kind", kind);
  form.append("file", file);
  const resp = await http.post(`/api/upload/${sessionId}`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return resp.data;
};

export const step1Extract = async (payload) => (await http.post("/api/step1/extract", payload)).data;
export const step2TranscribeRewrite = async (payload) =>
  (await http.post("/api/step2/transcribe-rewrite", payload)).data;
export const step2RewriteOnly = async (payload) => (await http.post("/api/step2/rewrite", payload)).data;
export const step3Generate = async (payload) => (await http.post("/api/step3/generate", payload)).data;
export const step4Tts = async (payload) => (await http.post("/api/step4/tts", payload)).data;
export const step5Align = async (payload) => (await http.post("/api/step5/align", payload)).data;
export const step6Publish = async (payload) => (await http.post("/api/step6/publish", payload)).data;

export const absUrl = (url, cacheBust) => {
  if (!url) {
    return "";
  }

  const absolute = url.startsWith("http://") || url.startsWith("https://") ? url : `${baseURL}${url}`;
  if (!cacheBust || !absolute.includes("/api/artifacts/")) {
    return absolute;
  }

  const hasQuery = absolute.includes("?");
  return `${absolute}${hasQuery ? "&" : "?"}v=${encodeURIComponent(cacheBust)}`;
};
