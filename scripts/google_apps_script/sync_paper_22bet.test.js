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

test('GitHub content is Base64-encoded from UTF-8 bytes', () => {
  context.Utilities = {
    newBlob: (text, contentType, name) => {
      assert.equal(text, 'ação');
      assert.equal(contentType, 'application/json');
      assert.equal(name, 'manual_paper_22bet.json');
      return {getBytes: () => [97, 195, 167, 195, 163, 111]};
    },
    base64Encode: (bytes) => {
      assert.deepEqual(Array.from(bytes), [97, 195, 167, 195, 163, 111]);
      return 'YcOnw6Nv';
    },
  };
  assert.equal(context.githubContentBase64_('ação'), 'YcOnw6Nv');
});

test('derived linkage changes semantic fingerprint with identical sheet rows', () => {
  const rows = [['same', 'rows']];
  const missing = context.semanticFingerprintMaterial_(rows, {linkage: {SNAPSHOT_NOT_FOUND: 1}, eligible_green_strong: 0});
  const linked = context.semanticFingerprintMaterial_(rows, {linkage: {LINKED_EX_ANTE: 1}, eligible_green_strong: 1});
  assert.notEqual(missing, linked);
});

test('standalone sync opens the configured Sheet ID', () => {
  const expected = {getSheetByName: () => null};
  context.PropertiesService = {getScriptProperties: () => ({
    getProperty: (key) => key === 'GOOGLE_SHEETS_SPREADSHEET_ID' ? 'standalone-sheet-id' : null,
  })};
  context.SpreadsheetApp = {openById: (id) => {
    assert.equal(id, 'standalone-sheet-id');
    return expected;
  }};
  assert.equal(context.paperTradingSpreadsheet_(), expected);
});

test('standalone sync retries by canonical URL when ID lookup is empty', () => {
  const expected = {getSheetByName: () => null};
  context.PropertiesService = {getScriptProperties: () => ({
    getProperty: (key) => key === 'GOOGLE_SHEETS_SPREADSHEET_ID' ? 'fallback-sheet-id' : null,
  })};
  context.SpreadsheetApp = {
    openById: () => null,
    openByUrl: (url) => {
      assert.equal(url, 'https://docs.google.com/spreadsheets/d/fallback-sheet-id/edit');
      return expected;
    },
  };
  assert.equal(context.paperTradingSpreadsheet_(), expected);
});

test('underdog pair counts one candidate, two PAPER legs and one complete pair', () => {
  const headers = ['Data', 'Jogo', 'Tour', 'Nível', 'Piso', 'Tipo de mercado', 'Seleção', 'Fav/Und', 'Pré/Live', 'Odd aposta', 'Stake (u)', 'EDGE', 'Resultado', 'Lucro (u)', 'Notas'].concat(
    ['Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC', '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status'],
  );
  const moneyline = row('wta:pair', '2026-09-07T10:00:00Z');
  moneyline[0] = 'Alpha'; moneyline[1] = 'Beta'; moneyline[5] = 'Vencedor'; moneyline[7] = 'Underdog'; moneyline[9] = 2.1; moneyline[12] = 'GANHOU'; moneyline[18] = 2.1;
  const handicap = row('wta:pair', '2026-09-07T10:00:00Z');
  handicap[0] = 'Alpha'; handicap[1] = 'Beta'; handicap[5] = 'Handicap games'; handicap[7] = 'Underdog'; handicap[9] = 1.9; handicap[12] = 'PERDEU'; handicap[19] = 3.5;
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
  assert.deepEqual(JSON.parse(JSON.stringify(strategy.flat_stake_simulation)), {
    status: 'AVAILABLE', stake_per_entry_eur: 10,
    included_resolved_entries: 2, pending_entries: 0, void_entries: 0,
    excluded_entries: 0, resolved_stake_eur: 20, pending_exposure_eur: 0,
    net_profit_eur: 1, roi_pct: 5, exclusion_reasons: {},
  });
  assert.notEqual(unavailable.data_fingerprint, payload.data_fingerprint);
  assert.equal(unavailable.by_strategy.GUERRA_SELECTION_V1.paper_entries, 0);
  assert.equal(unavailable.by_strategy.GUERRA_SELECTION_V1.flat_stake_simulation.excluded_entries, 0);
  assert.equal(unavailable.by_strategy.GUERRA_SELECTION_V1.flat_stake_simulation.status, 'UNAVAILABLE');
  assert.doesNotMatch(JSON.stringify(strategy), /wta:pair|Alpha|Beta/);
});

test('flat stake simulation handles win, loss, void and pending independently of real stake', () => {
  const simulation = context.newFlatStakeSimulation_();
  const win = Array(15).fill(''); win[9] = 2.0; win[10] = 999; win[12] = 'GANHOU'; win[13] = -500;
  const secondWin = Array(15).fill(''); secondWin[9] = 1.75; secondWin[12] = 'GANHOU';
  const loss = Array(15).fill(''); loss[9] = 4.0; loss[12] = 'PERDEU';
  const voided = Array(15).fill(''); voided[9] = 1.8; voided[12] = 'VOID';
  const pending = Array(15).fill(''); pending[9] = 2.2; pending[12] = 'PENDENTE';
  [win, secondWin, loss, voided, pending].forEach(value => context.addRowToFlatStakeSimulation_(simulation, value));
  const result = context.finishFlatStakeSimulation_(simulation, true);
  assert.equal(result.included_resolved_entries, 4);
  assert.equal(result.pending_entries, 1);
  assert.equal(result.void_entries, 1);
  assert.equal(result.resolved_stake_eur, 40);
  assert.equal(result.pending_exposure_eur, 10);
  assert.equal(result.net_profit_eur, 7.5);
  assert.equal(result.roi_pct, 18.75);
  assert.equal(result.status, 'AVAILABLE');
});

test('invalid odds and unknown results degrade the flat simulation with typed aggregate reasons', () => {
  const simulation = context.newFlatStakeSimulation_();
  const invalidOdd = Array(15).fill(''); invalidOdd[9] = 1; invalidOdd[12] = 'GANHOU';
  const unknownResult = Array(15).fill(''); unknownResult[9] = 2; unknownResult[12] = 'CANCELADO?';
  context.addRowToFlatStakeSimulation_(simulation, invalidOdd);
  context.addRowToFlatStakeSimulation_(simulation, unknownResult);
  const result = context.finishFlatStakeSimulation_(simulation, true);
  assert.equal(result.status, 'DEGRADED');
  assert.equal(result.excluded_entries, 2);
  assert.equal(result.net_profit_eur, null);
  assert.deepEqual(JSON.parse(JSON.stringify(result.exclusion_reasons)), {
    INVALID_DECIMAL_ODD: 1, UNRECOGNIZED_RESULT: 1,
  });
});

test('zero selections are unavailable and never imply zero profit', () => {
  const result = context.finishFlatStakeSimulation_(context.newFlatStakeSimulation_(), true);
  assert.equal(result.status, 'UNAVAILABLE');
  assert.equal(result.net_profit_eur, null);
  assert.equal(result.roi_pct, null);
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

test('Casa inserted before odds keeps all PAPER totals mapped by header', () => {
  const headers = [
    'Data', 'Jogo', 'Tour', 'Nível', 'Piso', 'Tipo de mercado', 'Seleção', 'Fav/Und',
    'Pré/Live', 'Casa', 'Odd aposta', 'Stake (u)', 'EDGE', 'Resultado', 'Lucro (u)', 'Notas',
  ];
  const wonOn22Bet = Array(headers.length).fill('');
  wonOn22Bet[0] = '2026-10-06'; wonOn22Bet[1] = 'Alpha vs Beta'; wonOn22Bet[5] = 'Vencedor';
  wonOn22Bet[7] = 'Favorito'; wonOn22Bet[9] = '22Bet'; wonOn22Bet[10] = 1.8;
  wonOn22Bet[11] = 1; wonOn22Bet[13] = 'GANHOU'; wonOn22Bet[14] = 0.8;
  const wonOnBetfair = Array(headers.length).fill('');
  wonOnBetfair[0] = '2026-10-06'; wonOnBetfair[1] = 'Gamma vs Delta'; wonOnBetfair[5] = 'Handicap games';
  wonOnBetfair[7] = 'Underdog'; wonOnBetfair[9] = 'Betfair'; wonOnBetfair[10] = 2.12;
  wonOnBetfair[11] = 1; wonOnBetfair[13] = 'GANHOU'; wonOnBetfair[14] = 1.064;
  const sheet = {
    getLastRow: () => 7, getLastColumn: () => headers.length,
    getRange: (sheetRow) => ({getValues: () => sheetRow === 5 ? [headers] : [wonOn22Bet, wonOnBetfair]}),
  };
  context.SpreadsheetApp = {getActiveSpreadsheet: () => ({
    getSheetByName: () => sheet, getUrl: () => 'https://docs.google.com/spreadsheets/d/test',
  })};
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, computeDigest: () => [0]};
  const payload = context.buildPaperTradingPayload_('', '', 'main');
  assert.equal(payload.summary.total_entries, 2);
  assert.equal(payload.summary.settled, 2);
  assert.equal(payload.summary.wins, 2);
  assert.equal(payload.summary.units, 1.864);
  assert.equal(payload.summary.roi_pct, 93.2);
  assert.equal(payload.summary.average_odd, 1.96);
  assert.equal(payload.by_market.Moneyline.units, 0.8);
  assert.equal(payload.by_market['Handicap games'].units, 1.064);
});

test('operational headers tolerate accents and invisible whitespace and preserve 0.5u exposure', () => {
  const headers = [
    'Data', 'Jogo', 'Tour', 'Nível', 'Piso', 'Tipo de Mercado\u00a0', 'Seleção', 'Fav/Und',
    'Pré/Live', 'Casa', 'Odd Aposta ', 'Stake (u)', 'EDGE', 'Resultado\u00a0', 'Lucro (u)', 'Notas',
  ];
  const settled = Array(headers.length).fill('');
  settled[0] = '2026-10-07'; settled[1] = 'Alpha vs Beta'; settled[5] = 'Vencedor'; settled[7] = 'Favorito';
  settled[10] = 1.85; settled[11] = 1; settled[13] = 'GANHOU'; settled[14] = 0.85;
  const pending = Array(headers.length).fill('');
  pending[0] = '2026-10-07'; pending[1] = 'Gamma vs Delta'; pending[5] = 'Handicap games'; pending[7] = 'Favorito';
  pending[10] = 1.82; pending[11] = 0.5; pending[13] = 'PENDENTE';
  const sheet = {
    getLastRow: () => 7, getLastColumn: () => headers.length,
    getRange: (sheetRow) => ({getValues: () => sheetRow === 5 ? [headers] : [settled, pending]}),
  };
  context.SpreadsheetApp = {getActiveSpreadsheet: () => ({getSheetByName: () => sheet, getUrl: () => 'https://docs.google.com/spreadsheets/d/test'})};
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, computeDigest: () => [0]};
  const payload = context.buildPaperTradingPayload_('', '', 'main');
  assert.equal(payload.summary.settled, 1);
  assert.equal(payload.summary.pending, 1);
  assert.equal(payload.summary.settled_stake_units, 1);
  assert.equal(payload.summary.pending_stake_units, 0.5);
  assert.deepEqual(JSON.parse(JSON.stringify(payload.source.operational_columns)), {
    market: 6, side: 8, odd: 11, stake: 12, result: 14, profit: 15,
  });
});

test('an expanded sheet with unrecognised operational headers fails closed', () => {
  const headers = Array.from({length: 16}, (_, index) => 'Unknown column ' + index);
  const tracking = context.trackingIndexes_(headers);
  assert.throws(
    () => context.assertOperationalTracking_(tracking, headers),
    /Contrato operacional da Sheet não reconhecido/,
  );
});

test('manual Challenger 125 has a separate 0.5u aggregate and never changes normal PAPER totals', () => {
  const headers = ['Data', 'Jogo', 'Tour', 'Nível', 'Piso', 'Tipo de mercado', 'Seleção', 'Fav/Und', 'Pré/Live', 'Odd aposta', 'Stake (u)', 'EDGE', 'Resultado', 'Lucro (u)', 'Notas'].concat([
    'Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC', '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status',
    'Challenger Índice Fenzobot', 'Challenger Cobertura %', 'Challenger Edge %',
  ]);
  const challenger = Array(24).fill('');
  challenger[0] = 'Private Player'; challenger[1] = 'Private Opponent'; challenger[5] = 'Vencedor'; challenger[7] = 'Favorito';
  challenger[9] = 2; challenger[10] = 0.5; challenger[12] = 'GANHOU'; challenger[13] = 0.5;
  challenger[15] = 'private:snapshot'; challenger[16] = 'CHALLENGER_125_EXPERIMENTAL_V1'; challenger[17] = '2026-10-04T10:00:00Z';
  challenger[21] = 78; challenger[22] = 0.62; challenger[23] = 4.2;
  const sheet = {
    getLastRow: () => 6, getLastColumn: () => 24,
    getRange: (sheetRow) => ({getValues: () => sheetRow === 5 ? [headers] : [challenger], setValue: () => {}}),
  };
  context.SpreadsheetApp = {getActiveSpreadsheet: () => ({getSheetByName: () => sheet, getUrl: () => 'https://docs.google.com/spreadsheets/d/test'})};
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, computeDigest: () => [0]};
  context.fetchGreenStrongIndex_ = () => ({available: false, eligibleCount: null, byKey: {}});
  const payload = context.buildPaperTradingPayload_('', '', 'main');
  const strategy = payload.by_strategy.CHALLENGER_125_EXPERIMENTAL_V1;
  assert.equal(payload.summary.total_entries, 0);
  assert.equal(strategy.summary.total_entries, 1);
  assert.equal(strategy.summary.wins, 1);
  assert.equal(strategy.summary.units, 0.5);
  assert.equal(strategy.fixed_stake_units, 0.5);
  assert.equal(strategy.by_fenzobot_index_band['70–79'].total_entries, 1);
  assert.equal(strategy.by_coverage_band['50–64,9%'].total_entries, 1);
  assert.equal(strategy.by_edge_band['4–4,9%'].total_entries, 1);
  assert.doesNotMatch(JSON.stringify(payload), /Private Player|Private Opponent|private:snapshot/);
});
