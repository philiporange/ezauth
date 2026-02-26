import { Rows } from './rows.js';

class Columns {
  constructor(client) {
    this._client = client;
  }

  add(tableId, { name, type, required, defaultValue, position } = {}) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/columns`,
      {
        method: 'POST',
        body: {
          name,
          type,
          required: required ?? false,
          default_value: defaultValue ?? null,
          position: position ?? null,
        },
        auth: 'auto',
      },
    );
  }

  update(tableId, columnId, { name, required, defaultValue, position } = {}) {
    const body = {};
    if (name !== undefined) body.name = name;
    if (required !== undefined) body.required = required;
    if (defaultValue !== undefined) body.default_value = defaultValue;
    if (position !== undefined) body.position = position;

    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/columns/${encodeURIComponent(columnId)}`,
      { method: 'PATCH', body, auth: 'auto' },
    );
  }

  delete(tableId, columnId) {
    return this._client._fetch(
      `/v1/tables/${encodeURIComponent(tableId)}/columns/${encodeURIComponent(columnId)}`,
      { method: 'DELETE', auth: 'auto' },
    );
  }
}

export class Tables {
  constructor(client) {
    this._client = client;
    this.columns = new Columns(client);
    this.rows = new Rows(client);
  }

  create({ name, columns } = {}) {
    const body = { name };
    if (columns !== undefined) body.columns = columns;
    return this._client._fetch('/v1/tables', { method: 'POST', body, auth: 'auto' });
  }

  list() {
    return this._client._fetch('/v1/tables', { auth: 'auto' });
  }

  get(tableId) {
    return this._client._fetch(`/v1/tables/${encodeURIComponent(tableId)}`, { auth: 'auto' });
  }

  delete(tableId) {
    return this._client._fetch(`/v1/tables/${encodeURIComponent(tableId)}`, {
      method: 'DELETE',
      auth: 'auto',
    });
  }
}
