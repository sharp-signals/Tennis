const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(__dirname + '/sync_paper_22bet.gs', 'utf8');
const context = {console};
vm.createContext(context);
vm.runInContext(source, context);

const tracking = {complete: true, snapshot: 15, strategy: 16, selectedAt: 17, reviewOdd: 18, handicapLine: 19, status: 20};
function row(key, selectedAt) {
  const values = Array(21).fill('');
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
  const all = ['Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC', '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status'];
  assert.deepEqual(Array.from(context.missingTrackingHeaders_([])), all);
  assert.deepEqual(Array.from(context.missingTrackingHeaders_(all)), []);
});

test('derived linkage changes semantic fingerprint with identical sheet rows', () => {
  const rows = [['same', 'rows']];
  const missing = context.semanticFingerprintMaterial_(rows, {linkage: {SNAPSHOT_NOT_FOUND: 1}, eligible_green_strong: 0});
  const linked = context.semanticFingerprintMaterial_(rows, {linkage: {LINKED_EX_ANTE: 1}, eligible_green_strong: 1});
  assert.notEqual(missing, linked);
});

test('underdog pair counts one candidate, two PAPER legs and one complete pair', () => {
  const headers = Array.from({length: 15}, (_, index) => 'Legacy ' + index).concat(
    ['Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC', '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status'],
  );
  const moneyline = row('wta:pair', '2026-09-07T10:00:00Z');
  moneyline[0] = 'Alpha'; moneyline[1] = 'Beta'; moneyline[5] = 'Vencedor'; moneyline[7] = 'Underdog'; moneyline[9] = 2.1; moneyline[18] = 2.1;
  const handicap = row('wta:pair', '2026-09-07T10:00:00Z');
  handicap[0] = 'Alpha'; handicap[1] = 'Beta'; handicap[5] = 'Handicap games'; handicap[7] = 'Underdog'; handicap[9] = 1.9; handicap[19] = 3.5;
  const rows = [moneyline, handicap];
  const sheet = {
    getLastRow: () => 7,
    getLastColumn: () => 21,
    getRange: (sheetRow) => ({
      getValues: () => sheetRow === 5 ? [headers] : rows,
      setValue: () => {},
    }),
  };
  context.SpreadsheetApp = {getActiveSpreadsheet: () => ({
    getSheetByName: () => sheet, getUrl: () => 'https://docs.google.com/spreadsheets/d/test',
  })};
  context.Utilities = {
    DigestAlgorithm: {SHA_256: 'SHA_256'},
    computeDigest: (algorithm, material) => Array.from(crypto.createHash('sha256').update(String(material)).digest()),
  };
  context.fetchGreenStrongIndex_ = () => ({available: false, eligibleCount: null, byKey: {}});
  const unavailable = context.buildPaperTradingPayload_('token', 'repo', 'main');
  context.fetchGreenStrongIndex_ = () => ({
    available: true, eligibleCount: 1,
    byKey: {'wta:pair': {eligible: true, commence_time_utc: '2026-09-07T12:00:00Z', selected_side_market_position: 'UNDERDOG'}},
  });
  const payload = context.buildPaperTradingPayload_('token', 'repo', 'main');
  const strategy = payload.by_strategy.GUERRA_SELECTION_V1;
  assert.equal(strategy.selected_candidates, 1);
  assert.equal(strategy.paper_entries, 2);
  assert.equal(strategy.selection_rate_pct, 100);
  assert.equal(strategy.underdog_pair_completeness.complete_moneyline_positive_handicap_pairs, 1);
  assert.notEqual(unavailable.data_fingerprint, payload.data_fingerprint);
  assert.equal(unavailable.by_strategy.GUERRA_SELECTION_V1.paper_entries, 0);
  assert.doesNotMatch(JSON.stringify(strategy), /wta:pair|Alpha|Beta/);
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
