export class Auth {
  constructor(client) {
    this._client = client;
  }

  signUp({ email, password, redirectUrl } = {}) {
    return this._client._fetch('/v1/signups', {
      method: 'POST',
      auth: 'publishable',
      body: {
        email,
        password: password || null,
        redirect_url: redirectUrl || null,
      },
    });
  }

  signIn({ email, password, strategy, redirectUrl } = {}) {
    return this._client._fetch('/v1/signins', {
      method: 'POST',
      auth: 'publishable',
      body: {
        email,
        password: password || null,
        strategy: strategy || (password ? 'password' : 'magic_link'),
        redirect_url: redirectUrl || null,
      },
    });
  }

  signOut() {
    return this._client._fetch('/v1/sessions/logout', {
      method: 'POST',
      auth: 'publishable',
    });
  }

  verifyCode({ email, code }) {
    return this._client._fetch('/v1/verify-code', {
      method: 'POST',
      auth: 'publishable',
      body: { email, code },
    });
  }

  getSession() {
    return this._client._fetch('/v1/me', { auth: 'publishable' });
  }

  refreshToken(refreshToken) {
    return this._client._fetch('/v1/tokens/session', {
      method: 'POST',
      auth: 'publishable',
      body: { refresh_token: refreshToken },
    });
  }

  ssoExchange(token) {
    return this._client._fetch('/v1/sso/exchange', {
      method: 'POST',
      auth: 'publishable',
      body: { token },
    });
  }
}
