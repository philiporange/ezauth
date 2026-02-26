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
    this.accessToken = config.accessToken || null;
  }

  _buildHeaders(auth, contentType = 'application/json') {
    const headers = {};
    if (contentType) headers['Content-Type'] = contentType;

    if (auth === 'secret') {
      if (!this.secretKey) throw new EZAuthError('secretKey is required for this operation', 0, 'missing_key');
      headers['Authorization'] = `Bearer ${this.secretKey}`;
    } else if (auth === 'publishable') {
      if (!this.publishableKey) throw new EZAuthError('publishableKey is required for this operation', 0, 'missing_key');
      headers['X-Publishable-Key'] = this.publishableKey;
    } else if (auth === 'auto') {
      if (this.secretKey) {
        headers['Authorization'] = `Bearer ${this.secretKey}`;
      } else if (this.publishableKey) {
        headers['X-Publishable-Key'] = this.publishableKey;
        if (this.accessToken) {
          headers['Authorization'] = `Bearer ${this.accessToken}`;
        } else {
          throw new EZAuthError('accessToken is required for user operations', 0, 'missing_token');
        }
      } else {
        throw new EZAuthError('secretKey or publishableKey is required', 0, 'missing_key');
      }
    }

    return headers;
  }

  _buildUrl(path, query) {
    let url = `${this.baseUrl}${path}`;
    if (query) {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined && v !== null) params.append(k, String(v));
      }
      const qs = params.toString();
      if (qs) url += `?${qs}`;
    }
    return url;
  }

  async _fetch(path, { method = 'GET', body, auth = 'secret', query } = {}) {
    const url = this._buildUrl(path, query);
    const headers = this._buildHeaders(auth);

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

  async _fetchRaw(path, { method = 'GET', body, contentType, auth = 'auto', query } = {}) {
    const url = this._buildUrl(path, query);
    const headers = this._buildHeaders(auth, contentType || '');

    const opts = { method, headers };
    if (body !== undefined) opts.body = body;

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

    return resp;
  }
}
