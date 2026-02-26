export class Storage {
  constructor(client) {
    this._client = client;
  }

  tables() {
    return this._client._fetch('/v1/tables/storage', { auth: 'auto' });
  }

  objects() {
    return this._client._fetch('/v1/buckets/storage', { auth: 'auto' });
  }
}
