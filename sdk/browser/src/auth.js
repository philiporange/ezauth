import { getConfig, EZAuthClient } from './client.js';

function _client() {
  return new EZAuthClient(getConfig());
}

export function signUp(params) {
  return _client().signUp(params);
}

export function signIn(params) {
  return _client().signIn(params);
}

export function signOut() {
  return _client().signOut();
}

export function handleEmailLinkCallback() {
  return _client().handleEmailLinkCallback();
}
