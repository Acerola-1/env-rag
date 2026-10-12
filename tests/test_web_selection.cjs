const test = require('node:test');
const assert = require('node:assert/strict');
require('../src/env_rag_final/web/static/selection.js');
const {resolve} = globalThis.RAGSelection;
const modes = ['naive', 'local', 'global', 'hybrid', 'mix'];
const all = [...modes, 'pg', ...modes.map(mode => `pg+${mode}`), 'bypass'];
test('normal query ignores every checked comparison option', () => {
  assert.deepEqual(resolve('ask', 'lightrag', 'local', all), ['local']);
  assert.deepEqual(resolve('ask', 'combined', 'mix', all), ['pg+mix']);
});
test('each native mode and corresponding combination is one complete route', () => {
  for (const mode of modes) {
    assert.deepEqual(resolve('ask', 'lightrag', mode, []), [mode]);
    assert.deepEqual(resolve('ask', 'combined', mode, []), [`pg+${mode}`]);
  }
});
test('PG and bypass have no hidden LightRAG dependency', () => {
  assert.deepEqual(resolve('ask', 'pg', undefined, all), ['pg']);
  assert.deepEqual(resolve('ask', 'bypass', undefined, all), ['bypass']);
});
test('comparison returns explicit routes rather than synthesizing a mode', () => {
  assert.deepEqual(resolve('compare', 'combined', 'mix', ['local', 'pg+local']), ['local', 'pg+local']);
  assert.deepEqual(resolve('compare', 'pg', 'mix', ['local', 'global']), ['local', 'global']);
  assert.deepEqual(resolve('compare', undefined, undefined, all), all);
});
test('comparison clears safely and duplicate labels never add extra queries', () => {
  assert.deepEqual(resolve('compare', 'pg', 'local', []), []);
  assert.deepEqual(resolve('compare', 'pg', 'local', ['local', 'local']), ['local']);
});
test('invalid workflow, route or mode refuses selection', () => {
  assert.throws(() => resolve('other', 'pg', 'local', []));
  assert.throws(() => resolve('ask', 'other', 'local', []));
  assert.throws(() => resolve('ask', 'combined', 'other', []));
  assert.throws(() => resolve('compare', 'pg', 'local', ['other']));
});
