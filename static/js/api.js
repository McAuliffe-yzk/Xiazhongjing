"use strict";

const XZJApi = Object.freeze({
  async request(resource, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    return window.fetch(resource, { ...options, headers });
  },

  async json(resource, options = {}) {
    const response = await this.request(resource, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data?.detail;
      const message = typeof detail === "string"
        ? detail
        : (detail?.message || data?.message || `请求失败（${response.status}）`);
      const error = new Error(message);
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  }
});

