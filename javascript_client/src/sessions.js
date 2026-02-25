export class Sessions {
  constructor(client) {
    this._client = client;
  }

  revoke(sessionId) {
    return this._client._fetch('/v1/sessions/revoke', {
      method: 'POST',
      query: { session_id: sessionId },
    });
  }

  createSignInToken({ userId, expiresInSeconds } = {}) {
    return this._client._fetch('/v1/sign_in_tokens', {
      method: 'POST',
      body: {
        user_id: userId,
        expires_in_seconds: expiresInSeconds,
      },
    });
  }
}
