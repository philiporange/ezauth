export class Storage {
  constructor(client) {
    this._client = client;
  }

  get() {
    return this._client._fetch('/v1/tables/storage');
  }
}
