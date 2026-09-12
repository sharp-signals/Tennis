/**
 * CHANGE-2026-09-13-042
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
  { hour: 6, minute: 30 },
  { hour: 11, minute: 30 },
  { hour: 15, minute: 30 },
  { hour: 18, minute: 30 },
];

function dispatchPreLiveBot() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');
  const url = `https://api.github.com/repos/${PRELIVE_OWNER}/${PRELIVE_REPO}/actions/workflows/${PRELIVE_WORKFLOW}/dispatches`;
  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({ ref: PRELIVE_REF }),
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 204) {
    throw new Error(`GitHub dispatch falhou: HTTP ${response.getResponseCode()} ${response.getContentText()}`);
  }
}

function installPreLiveSchedule() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'dispatchPreLiveBot')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));

  PRELIVE_RUNS.forEach(run => {
    ScriptApp.newTrigger('dispatchPreLiveBot')
      .timeBased()
      .atHour(run.hour)
      .nearMinute(run.minute)
      .everyDays(1)
      .inTimezone(PRELIVE_TIMEZONE)
      .create();
  });
}
