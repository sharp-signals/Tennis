const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(__dirname + '/prelive_scheduler.gs', 'utf8');

function trigger(handler, id) {
  return {
    getHandlerFunction: () => handler,
    getUniqueId: () => id || `id-${handler}`,
  };
}

function harness(initialTriggers = []) {
  const logs = [];
  const properties = new Map([['GITHUB_TOKEN', 'test-secret-token']]);
  const state = {
    triggers: initialTriggers.slice(),
    deleted: [],
    created: [],
    fetchOptions: null,
  };
  const context = {
    console: {
      log: value => logs.push(String(value)),
      warn: value => logs.push(String(value)),
    },
    PropertiesService: {getScriptProperties: () => ({
      getProperty: key => properties.get(key) || null,
      setProperty: (key, value) => properties.set(key, String(value)),
    })},
    Utilities: {formatDate: (date, timezone, pattern) => {
      const values = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
        timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
      }).formatToParts(date).map(part => [part.type, part.value]));
      if (pattern === 'yyyy-MM-dd') return `${values.year}-${values.month}-${values.day}`;
      if (pattern === 'HH:mm') return `${values.hour}:${values.minute}`;
      throw new Error(`unsupported pattern ${pattern}`);
    }},
    ScriptApp: {
      getProjectTriggers: () => state.triggers.slice(),
      deleteTrigger: item => {
        state.deleted.push(item.getHandlerFunction());
        state.triggers = state.triggers.filter(triggerItem => triggerItem !== item);
      },
      newTrigger: handler => {
        const schedule = {handler};
        const builder = {
          timeBased: () => builder,
          atHour: hour => { schedule.hour = hour; return builder; },
          nearMinute: minute => { schedule.minute = minute; return builder; },
          everyDays: days => { schedule.days = days; return builder; },
          inTimezone: timezone => { schedule.timezone = timezone; return builder; },
          create: () => {
            state.created.push(schedule);
            state.triggers.push(trigger(handler, `created-${handler}`));
          },
        };
        return builder;
      },
    },
    UrlFetchApp: {fetch: (_url, options) => {
      state.fetchOptions = options;
      return {getResponseCode: () => 204, getContentText: () => ''};
    }},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {context, state, logs, properties};
}

const handlers = [
  'dispatchPreLive0630',
  'dispatchPreLive1130',
  'dispatchPreLive1530',
  'dispatchPreLive1830',
];

test('four distinct handlers preserve the four Lisbon logical slots', () => {
  const {context, state} = harness();
  context.installPreLiveSchedule();
  assert.deepEqual(state.created.map(item => item.handler), handlers);
  assert.deepEqual(state.created.map(item => item.hour), [6, 11, 15, 18]);
  assert.deepEqual(state.created.map(item => item.minute), [30, 30, 30, 30]);
  assert.ok(state.created.every(item => item.timezone === 'Europe/Lisbon'));
});

test('installer removes managed legacy/new triggers but preserves unrelated ones', () => {
  const {context, state} = harness([
    trigger('dispatchPreLiveBot', 'legacy'),
    trigger('dispatchPreLive0630', 'old-new'),
    trigger('unrelatedHandler', 'unrelated'),
  ]);
  context.installPreLiveSchedule();
  assert.deepEqual(state.deleted.sort(), ['dispatchPreLive0630', 'dispatchPreLiveBot']);
  assert.equal(state.triggers.filter(item => item.getHandlerFunction() === 'unrelatedHandler').length, 1);
  assert.equal(state.created.length, 4);
});

test('dispatch payload carries correlation metadata without exposing token', () => {
  const {context, state, logs, properties} = harness(handlers.map(item => trigger(item)));
  const result = context.dispatchPreLiveBotForSlot('11:30');
  const payload = JSON.parse(state.fetchOptions.payload);
  assert.equal(payload.ref, 'main');
  assert.equal(payload.inputs.trigger_slot, '11:30');
  assert.equal(payload.inputs.trigger_source, 'google_apps_script');
  assert.match(payload.inputs.trigger_local_date, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(
    payload.inputs.dispatch_attempt_id,
    `${payload.inputs.trigger_local_date}:11:30:google_apps_script`,
  );
  const checkpoint = JSON.parse(properties.get('PRELIVE_LAST_DISPATCH_1130'));
  assert.equal(checkpoint.http_status, 204);
  assert.equal(checkpoint.dispatch_attempt_id, payload.inputs.dispatch_attempt_id);
  assert.equal(result.status, 'DISPATCH_ACCEPTED');
  assert.doesNotMatch(logs.join('\n') + JSON.stringify(result), /test-secret-token/);
});

test('verify is healthy for exactly one trigger per handler', () => {
  const {context} = harness(handlers.map(item => trigger(item)));
  const result = context.verifyPreLiveSchedule();
  assert.equal(result.trigger_status, 'HEALTHY');
  assert.equal(result.unexpected_legacy_triggers, 0);
  assert.deepEqual(Object.values(result.installed), [1, 1, 1, 1]);
});

test('verify is degraded for missing, duplicate, or legacy triggers', () => {
  const missing = harness(handlers.slice(0, 3).map(item => trigger(item))).context;
  assert.equal(missing.verifyPreLiveSchedule().status, 'DEGRADED');

  const duplicate = harness([
    ...handlers.map(item => trigger(item)),
    trigger('dispatchPreLive1130', 'duplicate'),
  ]).context;
  assert.equal(duplicate.verifyPreLiveSchedule().status, 'DEGRADED');

  const legacy = harness([
    ...handlers.map(item => trigger(item)),
    trigger('dispatchPreLiveBot', 'legacy'),
  ]).context;
  assert.equal(legacy.verifyPreLiveSchedule().status, 'DEGRADED');
});

test('self-heal reinstalls only a degraded schedule', () => {
  const healthy = harness(handlers.map(item => trigger(item)));
  healthy.context.ensurePreLiveSchedule();
  assert.equal(healthy.state.created.length, 0);

  const degraded = harness(handlers.slice(0, 3).map(item => trigger(item)));
  const result = degraded.context.ensurePreLiveSchedule();
  assert.equal(degraded.state.created.length, 4);
  assert.equal(result.trigger_status, 'HEALTHY');
});

test('non-204 dispatch still throws and records no successful dispatch', () => {
  const {context, properties} = harness();
  context.UrlFetchApp.fetch = () => ({
    getResponseCode: () => 403,
    getContentText: () => 'forbidden',
  });
  assert.throws(
    () => context.dispatchPreLiveBotForSlot('15:30'),
    /GitHub dispatch falhou: HTTP 403/,
  );
  assert.equal(properties.get('PRELIVE_LAST_DISPATCH_1530'), undefined);
});

test('daily coverage flags only slots whose Lisbon window already ended', () => {
  const {context, properties} = harness(handlers.map(item => trigger(item)));
  properties.set('PRELIVE_LAST_DISPATCH_0630', JSON.stringify({
    local_date: '2026-09-30', http_status: 204,
  }));
  const result = context.verifyPreLiveDailyCoverage(new Date('2026-09-30T15:00:00Z'));
  assert.deepEqual(Array.from(result.missing_past_slots), ['11:30', '15:30']);
  assert.equal(result.status, 'DEGRADED');
});

test('Lisbon day and legal-time conversion remain explicit across DST', () => {
  const {context} = harness();
  const winter = context.verifyPreLiveDailyCoverage(new Date('2026-01-15T07:00:00Z'));
  const summer = context.verifyPreLiveDailyCoverage(new Date('2026-07-15T06:00:00Z'));
  assert.equal(winter.local_date, '2026-01-15');
  assert.equal(summer.local_date, '2026-07-15');
  assert.deepEqual(Array.from(winter.missing_past_slots), ['06:30']);
  assert.deepEqual(Array.from(summer.missing_past_slots), ['06:30']);
});

test('workflow source contains no GitHub cron scheduler', () => {
  const workflow = fs.readFileSync(__dirname + '/../../.github/workflows/tennis-bot.yml', 'utf8');
  assert.doesNotMatch(workflow, /^\s*schedule:/m);
});
