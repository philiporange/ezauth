export class EZAuthError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = 'EZAuthError';
    this.status = status;
    this.code = code;
  }
}

export class BaseClient {
  constructor(config) {
    this.baseUrl = (config.baseUrl || '').replace(/\/+$/, '');
    this.secretKey = config.secretKey || null;
    this.publishableKey = config.publishableKey || null;
  }

  async _fetch(path, { method = 'GET', body, auth = 'secret', query } = {}) {
    let url = `${this.baseUrl}${path}`;

    if (query) {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined && v !== null) params.append(k, String(v));
      }
      const qs = params.toString();
      if (qs) url += `?${qs}`;
    }

    const headers = { 'Content-Type': 'application/json' };

    if (auth === 'secret') {
      if (!this.secretKey) throw new EZAuthError('secretKey is required for this operation', 0, 'missing_key');
      headers['Authorization'] = `Bearer ${this.secretKey}`;
    } else if (auth === 'publishable') {
      if (!this.publishableKey) throw new EZAuthError('publishableKey is required for this operation', 0, 'missing_key');
      headers['X-Publishable-Key'] = this.publishableKey;
    }

    const opts = { method, headers };
    if (body !== undefined) opts.body = JSON.stringify(body);

    const resp = await fetch(url, opts);

    if (resp.status === 204) return null;

    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new EZAuthError(
        data.detail || `Request failed: ${resp.status}`,
        resp.status,
        data.code || null,
      );
    }

    return resp.json();
  }
}
