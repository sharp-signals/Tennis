const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(__dirname + '/sync_system_history.gs', 'utf8');
const context = {console};
vm.createContext(context);
vm.runInContext(source, context);

test('Challenger history projection is rectangular', () => {
  let written = null;
  context.upsertSystemSheet_ = (_spreadsheet, _name, values) => { written = values; };
  const range = {
    setBackground() { return this; },
    setFontColor() { return this; },
    setFontWeight() { return this; },
  };
  const spreadsheet = {
    getSheetByName() {
      return {getRange() { return range; }};
    },
  };
  const stats = {
    total_entries: 1, settled: 1, wins: 1, losses: 0,
    pushes: 0, pending: 0, units: 0.85, roi_pct: 85, average_odd: 1.85,
  };
  context.writeChallengerManualPaperSheet_(spreadsheet, {
    by_strategy: {
      CHALLENGER_125_EXPERIMENTAL_V1: {
        status: 'AVAILABLE', summary: stats, by_market: {Moneyline: stats},
      },
    },
  });
  assert.ok(written);
  assert.deepEqual([...new Set(written.map(row => row.length))], [10]);
});

test('an optional existing filter never blocks the history sync', () => {
  const sheet = {
    getFilter() { return null; },
    getName() { return 'Atribuição — fatores'; },
  };
  const range = {
    createFilter() { throw new Error('Não é possível criar um filtro numa página que já tem um filtro.'); },
  };
  assert.equal(context.createSystemFilterBestEffort_(sheet, range), false);
});

test('weight decision panel blocks tuning while GUERRA factor evidence is insufficient', () => {
  const attribution = {
    summary: [
      {scope: 'GLOBAL', factor: 'fadiga', seen_snapshots: 857, active_matches: 486, coverage_pct: 56.7, hit_pct: 51.6, market_expected_pct: 54, market_residual_pp: -2.4, average_effective_weight: 3.345},
      {scope: 'GLOBAL', factor: 'servico_carreira', seen_snapshots: 857, active_matches: 536, coverage_pct: 62.5, hit_pct: 60.3, market_expected_pct: 55.7, market_residual_pp: 4.6, average_effective_weight: 3.2},
      {scope: 'ATP', factor: 'servico_carreira', market_residual_pp: 5.9},
      {scope: 'WTA', factor: 'servico_carreira', market_residual_pp: 2.7},
    ],
  };
  const manual = {by_strategy: {GUERRA_SELECTION_V1: {audit_v1: {quality: {
    linked_entries: 139, canonical_entries: 65, factor_audit_eligible_entries: 2,
    selected_side_unresolved: 63,
  }}}}};
  const model = context.buildWeightDecisionPanelModel_(attribution, manual);
  assert.match(model.status, /MANTER PESOS/);
  assert.match(model.headline, /Faltam 18/);
  assert.equal(model.eligible, 2);
  assert.equal(model.rows.find(row => row.factor === 'servico_carreira').signal, 'Sinal positivo a validar');
});

test('history projection repairs legacy GUERRA break-even scale defensively', () => {
  const rows = context.normaliseGuerraAuditRows_([{
    average_odd: 1.89, win_rate_pct: 60, break_even_pct: 5291,
    hit_vs_break_even_pp: -5231,
  }]);
  assert.equal(rows[0].break_even_pct, 52.9);
  assert.equal(rows[0].hit_vs_break_even_pp, 7.1);
});

test('weight panel clears legacy validation before writing the new projection', () => {
  const start = source.indexOf('function writeWeightDecisionPanel_');
  const end = source.indexOf('function writeProspectiveSystemHistory_', start);
  const body = source.slice(start, end);
  assert.ok(body.indexOf('clearDataValidations()') >= 0);
  assert.ok(body.indexOf('clearDataValidations()') < body.indexOf('setValues(rows)'));
});
