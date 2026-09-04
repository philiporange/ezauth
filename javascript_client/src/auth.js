import { solveChallenge } from './hashcash.js';

export class Auth {
  constructor(client) {
    this._client = client;
  }

  /** Request a hashcash proof-of-work challenge. */
  requestChallenge() {
    return this._client._fetch('/v1/challenges', {
      method: 'POST',
      auth: 'publishable',
    });
  }

  /**
   * Solve a challenge from `requestChallenge()`, returning the
   * `{ challenge, nonce }` proof that signup expects. Uses the solver passed
   * to the client constructor when one was given.
   */
  solveChallenge(challenge) {
    return (this._client.hashcashSolver || solveChallenge)(challenge);
  }

  /**
   * Create a user. Proof of work is on by default on the server, so unless a
   * `hashcash` proof is supplied one is requested and solved first. Pass
   * `solveHashcash: false` against a server that has it turned off.
   */
  async signUp({ email, password, redirectUrl, hashcash, solveHashcash = true } = {}) {
    const body = {
      email,
      password: password || null,
      redirect_url: redirectUrl || null,
    };

    if (hashcash) {
      body.hashcash = hashcash;
    } else if (solveHashcash) {
      body.hashcash = await this.solveChallenge(await this.requestChallenge());
    }

    return this._client._fetch('/v1/signups', {
      method: 'POST',
      auth: 'publishable',
      body,
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
      bearer: true,
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
    return this._client._fetch('/v1/me', { auth: 'publishable', bearer: true });
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

  signInWithOAuth({ provider, redirectUrl } = {}) {
    return this._client._fetch(`/v1/oauth/${provider}/authorize`, {
      auth: 'publishable',
      query: { redirect_url: redirectUrl },
    });
  }
}
