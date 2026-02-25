export class Rows {
  constructor(client) {
    this._client = client;
  }

  insert(tableId, { data }) {
    return this._client._fetch(`/v1/tables/${encodeURIComponent(tableId)}/rows`, {
      method: 'POST',
      body: { data },
    });
  }

  get(tableId, rowId) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/rows/${encodeURIComponent(rowId)}`,
    );
  }

  update(tableId, rowId, { data }) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/rows/${encodeURIComponent(rowId)}`,
      { method: 'PATCH', body: { data } },
    );
  }

  delete(tableId, rowId) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/rows/${encodeURIComponent(rowId)}`,
      { method: 'DELETE' },
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
      { method: 'POST', body },
    );
  }
}
