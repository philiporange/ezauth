export class Users {
  constructor(client) {
    this._client = client;
  }

  list({ limit, offset, email } = {}) {
    return this._client._fetch('/v1/users', {
      query: { limit, offset, email },
    });
  }

  create({ email, password } = {}) {
    return this._client._fetch('/v1/users', {
      method: 'POST',
      body: { email, password: password || null },
    });
  }

  get(userId) {
    return this._client._fetch(`/v1/users/${encodeURIComponent(userId)}`);
  }
}
