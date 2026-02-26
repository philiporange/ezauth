class Objects {
  constructor(client) {
    this._client = client;
  }

  async put(bucketId, key, data, { contentType = 'application/octet-stream', userId } = {}) {
    const query = {};
    if (userId !== undefined) query.user_id = userId;
    const resp = await this._client._fetchRaw(
      `/v1/buckets/${encodeURIComponent(bucketId)}/objects/${key}`,
      {
        method: 'PUT',
        body: data,
        contentType,
        query: Object.keys(query).length ? query : undefined,
      },
    );
    return resp.json();
  }

  async get(bucketId, key, { userId } = {}) {
    const query = {};
    if (userId !== undefined) query.user_id = userId;
    const resp = await this._client._fetchRaw(
      `/v1/buckets/${encodeURIComponent(bucketId)}/objects/${key}`,
      { query: Object.keys(query).length ? query : undefined },
    );
    const contentType = resp.headers.get('content-type') || 'application/octet-stream';
    const arrayBuffer = await resp.arrayBuffer();
    return { data: arrayBuffer, contentType };
  }

  async delete(bucketId, key, { userId } = {}) {
    const query = {};
    if (userId !== undefined) query.user_id = userId;
    await this._client._fetchRaw(
      `/v1/buckets/${encodeURIComponent(bucketId)}/objects/${key}`,
      {
        method: 'DELETE',
        query: Object.keys(query).length ? query : undefined,
      },
    );
  }

  list(bucketId, { userId, limit, cursor } = {}) {
    const query = {};
    if (userId !== undefined) query.user_id = userId;
    if (limit !== undefined) query.limit = limit;
    if (cursor !== undefined) query.cursor = cursor;
    return this._client._fetch(
      `/v1/buckets/${encodeURIComponent(bucketId)}/objects`,
      { auth: 'auto', query: Object.keys(query).length ? query : undefined },
    );
  }
}

export class Buckets {
  constructor(client) {
    this._client = client;
    this.objects = new Objects(client);
  }

  create({ name }) {
    return this._client._fetch('/v1/buckets', {
      method: 'POST',
      body: { name },
      auth: 'auto',
    });
  }

  list() {
    return this._client._fetch('/v1/buckets', { auth: 'auto' });
  }

  get(bucketId) {
    return this._client._fetch(`/v1/buckets/${encodeURIComponent(bucketId)}`, { auth: 'auto' });
  }

  delete(bucketId) {
    return this._client._fetch(`/v1/buckets/${encodeURIComponent(bucketId)}`, {
      method: 'DELETE',
      auth: 'auto',
    });
  }
}
