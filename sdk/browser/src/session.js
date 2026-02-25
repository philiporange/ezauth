import { getConfig, EZAuthClient } from './client.js';

function _client() {
  return new EZAuthClient(getConfig());
}

export function getSession() {
  return _client().getSession();
}

export function getUser() {
  return _client().getUser();
}

export function getToken() {
  return _client().getToken();
}
