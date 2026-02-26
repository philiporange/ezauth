import { BaseClient, EZAuthError } from './client.js';
import { Auth } from './auth.js';
import { Users } from './users.js';
import { Sessions } from './sessions.js';
import { Tables } from './tables.js';
import { Buckets } from './buckets.js';
import { Storage } from './storage.js';

class EZAuth extends BaseClient {
  constructor(config = {}) {
    super(config);
    this.auth = new Auth(this);
    this.users = new Users(this);
    this.sessions = new Sessions(this);
    this.tables = new Tables(this);
    this.buckets = new Buckets(this);
    this.storage = new Storage(this);
  }
}

export { EZAuth, EZAuthError };
