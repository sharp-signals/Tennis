/**
 * CHANGE-2026-09-26-055
 *
 * Agendador autónomo do Tennis Pre-Live Bot. Usa o token já guardado como
 * GITHUB_TOKEN nas Propriedades do Script e despacha o workflow do GitHub.
 * Não lê a Sheet PAPER nem partilha dados com o respetivo sincronizador.
 */

const PRELIVE_OWNER = 'sharp-signals';
const PRELIVE_REPO = 'Tennis';
const PRELIVE_WORKFLOW = 'tennis-bot.yml';
const PRELIVE_REF = 'main';
const PRELIVE_TIMEZONE = 'Europe/Lisbon';
const PRELIVE_RUNS = [
  { handler: 'dispatchPreLive0630', slot: '06:30', hour: 6, minute: 30 },
  { handler: 'dispatchPreLive1130', slot: '11:30', hour: 11, minute: 30 },
  { handler: 'dispatchPreLive1530', slot: '15:30', hour: 15, minute: 30 },
  { handler: 'dispatchPreLive1830', slot: '18:30', hour: 18, minute: 30 },
];
const PRELIVE_LEGACY_HANDLER = 'dispatchPreLiveBot';
const PRELIVE_MANAGED_HANDLERS = PRELIVE_RUNS
  .map(run => run.handler)
  .concat([PRELIVE_LEGACY_HANDLER]);

function dispatchPreLive0630() {
  return dispatchPreLiveBotForSlot('06:30');
}

function dispatchPreLive1130() {
  return dispatchPreLiveBotForSlot('11:30');
}

function dispatchPreLive1530() {
  return dispatchPreLiveBotForSlot('15:30');
}

function dispatchPreLive1830() {
  return dispatchPreLiveBotForSlot('18:30');
}

function dispatchPreLiveBot() {
  return dispatchPreLiveBotForSlot('manual');
}

function dispatchPreLiveBotForSlot(slot) {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');
  const url = `https://api.github.com/repos/${PRELIVE_OWNER}/${PRELIVE_REPO}/actions/workflows/${PRELIVE_WORKFLOW}/dispatches`;
  const payload = {
    ref: PRELIVE_REF,
    inputs: {
      trigger_slot: slot || 'manual',
      trigger_source: 'google_apps_script',
    },
  };
  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 204) {
    throw new Error(`GitHub dispatch falhou: HTTP ${response.getResponseCode()} ${response.getContentText()}`);
  }
  const run = PRELIVE_RUNS.find(item => item.slot === slot);
  if (run) {
    properties.setProperty(
      `PRELIVE_LAST_DISPATCH_${slot.replace(':', '')}`,
      new Date().toISOString(),
    );
  }
  try {
    const health = ensurePreLiveSchedule();
    console.log(`Pre-live schedule após dispatch ${slot}: ${health.status}`);
  } catch (error) {
    console.warn(`Dispatch ${slot} concluído; self-healing indisponível.`);
  }
  return {status: 'SUCCESS', slot: slot || 'manual'};
}

function installPreLiveSchedule() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => PRELIVE_MANAGED_HANDLERS.includes(trigger.getHandlerFunction()))
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));

  PRELIVE_RUNS.forEach(run => {
    ScriptApp.newTrigger(run.handler)
      .timeBased()
      .atHour(run.hour)
      .nearMinute(run.minute)
      .everyDays(1)
      .inTimezone(PRELIVE_TIMEZONE)
      .create();
  });
  return verifyPreLiveSchedule();
}

function verifyPreLiveSchedule() {
  const installed = {};
  const triggerIds = {};
  PRELIVE_RUNS.forEach(run => {
    installed[run.handler] = 0;
    triggerIds[run.handler] = [];
  });
  let unexpectedLegacyTriggers = 0;
  ScriptApp.getProjectTriggers().forEach(trigger => {
    const handler = trigger.getHandlerFunction();
    if (Object.prototype.hasOwnProperty.call(installed, handler)) {
      installed[handler] += 1;
      if (typeof trigger.getUniqueId === 'function') {
        triggerIds[handler].push(trigger.getUniqueId());
      }
    } else if (handler === PRELIVE_LEGACY_HANDLER) {
      unexpectedLegacyTriggers += 1;
    }
  });
  const healthy = PRELIVE_RUNS.every(run => installed[run.handler] === 1)
    && unexpectedLegacyTriggers === 0;
  const properties = PropertiesService.getScriptProperties();
  const lastDispatch = {};
  PRELIVE_RUNS.forEach(run => {
    lastDispatch[run.slot] = properties.getProperty(
      `PRELIVE_LAST_DISPATCH_${run.slot.replace(':', '')}`,
    ) || null;
  });
  const result = {
    status: healthy ? 'HEALTHY' : 'DEGRADED',
    timezone: PRELIVE_TIMEZONE,
    expected_handlers: PRELIVE_RUNS.map(run => run.handler),
    installed,
    trigger_ids: triggerIds,
    unexpected_legacy_triggers: unexpectedLegacyTriggers,
    last_dispatch: lastDispatch,
  };
  console.log(JSON.stringify(result));
  return result;
}

function ensurePreLiveSchedule() {
  const before = verifyPreLiveSchedule();
  if (before.status === 'HEALTHY') return before;
  installPreLiveSchedule();
  return verifyPreLiveSchedule();
}
