export class Rows {
  constructor(client) {
    this._client = client;
  }

  insert(tableId, { data, userId } = {}) {
    const body = { data };
    if (userId !== undefined) body.user_id = userId;
    return this._client._fetch(`/v1/tables/${encodeURIComponent(tableId)}/rows`, {
      method: 'POST',
      body,
      auth: 'auto',
    });
  }

  get(tableId, rowId) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/rows/${encodeURIComponent(rowId)}`,
      { auth: 'auto' },
    );
  }

  update(tableId, rowId, { data }) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/rows/${encodeURIComponent(rowId)}`,
      { method: 'PATCH', body: { data }, auth: 'auto' },
    );
  }

  delete(tableId, rowId) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/rows/${encodeURIComponent(rowId)}`,
      { method: 'DELETE', auth: 'auto' },
    );
  }

  query(tableId, { filter, sort, limit, cursor } = {}) {
    const body = {};
    if (filter !== undefined) body.filter = filter;
    if (sort !== undefined) body.sort = sort;
    if (limit !== undefined) body.limit = limit;
    if (cursor !== undefined) body.cursor = cursor;

    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/rows/query`,
      { method: 'POST', body, auth: 'auto' },
    );
  }
}
