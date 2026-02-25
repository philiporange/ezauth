let _config = null;

export function init(config) {
  if (!config.publishableKey) {
    throw new Error('EZAuth: publishableKey is required');
  }
  _config = {
    publishableKey: config.publishableKey,
    authDomain: config.authDomain || '',
    isSatellite: config.isSatellite || false,
    primarySignInUrl: config.primarySignInUrl || null,
    proxyUrl: config.proxyUrl || null,
  };
  return new EZAuthClient(_config);
}

export function getConfig() {
  if (!_config) {
    throw new Error('EZAuth: call init() first');
  }
  return _config;
}

export class EZAuthClient {
  constructor(config) {
    this.config = config;
    this._baseUrl = config.authDomain
      ? `https://${config.authDomain}`
      : '';
  }

  _headers() {
    return {
      'Content-Type': 'application/json',
      'X-Publishable-Key': this.config.publishableKey,
    };
  }

  async _fetch(path, options = {}) {
    const url = `${this._baseUrl}${path}`;
    const resp = await fetch(url, {
      credentials: 'include',
      headers: this._headers(),
      ...options,
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${resp.status}`);
    }
    return resp.json();
  }

  async signUp(params) {
    return this._fetch('/v1/signups', {
      method: 'POST',
      body: JSON.stringify({
        email: params.email,
        password: params.password || null,
        redirect_url: params.redirectUrl || window.location.href,
      }),
    });
  }

  async signIn(params) {
    return this._fetch('/v1/signins', {
      method: 'POST',
      body: JSON.stringify({
        email: params.email,
        password: params.password || null,
        strategy: params.password ? 'password' : 'magic_link',
        redirect_url: params.redirectUrl || window.location.href,
      }),
    });
  }

  async signOut() {
    return this._fetch('/v1/sessions/logout', { method: 'POST' });
  }

  async getSession() {
    try {
      return await this._fetch('/v1/me');
    } catch {
      return null;
    }
  }

  async getUser() {
    return this.getSession();
  }

  async getToken() {
    const session = await this.getSession();
    if (!session) return null;
    // The JWT is in the cookie; for APIs, refresh if needed
    try {
      return await this._fetch('/v1/tokens/session', {
        method: 'POST',
        body: JSON.stringify({}),
      });
    } catch {
      return null;
    }
  }

  async handleEmailLinkCallback() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const ssoToken = params.get('__sso_token');

    if (ssoToken && this.config.isSatellite) {
      return this._fetch('/v1/sso/exchange', {
        method: 'POST',
        body: JSON.stringify({ token: ssoToken }),
      });
    }

    if (token) {
      // The verify endpoint is a GET that sets cookies via redirect
      // Just confirm the session is active
      return this.getSession();
    }

    return null;
  }
}
