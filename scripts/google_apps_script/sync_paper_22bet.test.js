const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(__dirname + '/sync_paper_22bet.gs', 'utf8');
const context = {console};
vm.createContext(context);
vm.runInContext(source, context);

const tracking = {complete: true, snapshot: 15, strategy: 16, selectedAt: 17, reviewOdd: 18, status: 19};
function row(key, selectedAt) {
  const values = Array(20).fill('');
  values[15] = key;
  values[16] = 'GUERRA_SELECTION_V1';
  values[17] = selectedAt;
  return values;
}

test('valid linkage is exact and ex-ante', () => {
  const index = {key1: {eligible: true, commence_time_utc: '2026-09-07T12:00:00Z'}};
  assert.equal(context.validateGuerraSelection_(row('key1', '2026-09-07T11:59:00Z'), tracking, index), 'LINKED_EX_ANTE');
  assert.equal(context.validateGuerraSelection_(row('key1', '2026-09-07T12:00:00Z'), tracking, index), 'SELECTION_AFTER_START');
});

test('missing, non-green and unstamped selections fail closed', () => {
  assert.equal(context.validateGuerraSelection_(row('unknown', '2026-09-07T10:00:00Z'), tracking, {}), 'SNAPSHOT_NOT_FOUND');
  assert.equal(context.validateGuerraSelection_(row('key1', '2026-09-07T10:00:00Z'), tracking, {key1: {eligible: false}}), 'NOT_GREEN_STRONG');
  assert.equal(context.validateGuerraSelection_(row('key1', ''), tracking, {key1: {eligible: true, commence_time_utc: '2026-09-07T12:00:00Z'}}), 'MISSING_SELECTION_TIMESTAMP');
});

test('unavailable cohort index fails closed', () => {
  assert.equal(context.validateGuerraSelection_(row('key1', '2026-09-07T10:00:00Z'), tracking, {}, false), 'UNAVAILABLE');
});

test('1.75 is inclusive and there is no 1.90 ceiling', () => {
  assert.equal(context.moneylineReviewRoute_(1.749), 'HANDICAP_MANUAL_REVIEW');
  assert.equal(context.moneylineReviewRoute_(1.75), 'MONEYLINE_MANUAL_REVIEW');
  assert.equal(context.moneylineReviewRoute_(2.50), 'MONEYLINE_MANUAL_REVIEW');
});

test('tracking column installation is idempotent', () => {
  const all = ['Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC', '22Bet Moneyline Review Odd', 'Validation Status'];
  assert.deepEqual(Array.from(context.missingTrackingHeaders_([])), all);
  assert.deepEqual(Array.from(context.missingTrackingHeaders_(all)), []);
});

test('published source contains no individual selection fields', () => {
  assert.doesNotMatch(source, /published_rows|individual_entries|player_names/);
});

test('legacy 15-column sheet still aggregates and is not reclassified', () => {
  const headers = Array.from({length: 15}, (_, index) => 'Legacy ' + index);
  const legacy = Array(15).fill('');
  legacy[0] = 'Alpha'; legacy[1] = 'Beta'; legacy[5] = 'Vencedor'; legacy[7] = 'Underdog';
  legacy[9] = 2.0; legacy[10] = 1; legacy[12] = 'GANHOU'; legacy[13] = 1;
  const sheet = {
    getLastRow: () => 6,
    getLastColumn: () => 15,
    getRange: (row) => ({getValues: () => row === 5 ? [headers] : [legacy]}),
  };
  context.SpreadsheetApp = {getActiveSpreadsheet: () => ({
    getSheetByName: () => sheet,
    getUrl: () => 'https://docs.google.com/spreadsheets/d/test',
  })};
  context.Utilities = {
    DigestAlgorithm: {SHA_256: 'SHA_256'},
    computeDigest: () => [0],
  };
  const payload = context.buildPaperTradingPayload_('', '', 'main');
  assert.equal(payload.summary.total_entries, 1);
  assert.equal(payload.summary.wins, 1);
  assert.equal(payload.by_strategy.GUERRA_SELECTION_V1.summary.total_entries, 0);
  assert.equal(payload.by_strategy.GUERRA_SELECTION_V1.status, 'UNAVAILABLE');
  assert.doesNotMatch(JSON.stringify(payload), /Alpha|Beta/);
});
