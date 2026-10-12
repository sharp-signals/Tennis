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
