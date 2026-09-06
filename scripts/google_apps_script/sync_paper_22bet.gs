/**
 * CHANGE-2026-09-06-023
 * Publica apenas métricas agregadas da Sheet PAPER 22Bet no repositório.
 * Não publica a lista de apostas, notas ou dados pessoais.
 *
 * Antes de usar, definir nas Propriedades do script:
 * - GITHUB_TOKEN: fine-grained token com Contents: Read and write no Tennis
 * - GITHUB_REPOSITORY: sharp-signals/Tennis
 * Opcional: GITHUB_BRANCH (por omissão, main)
 */

const PAPER_22BET_SYNC = {
  sheetName: 'Apostas',
  headerRow: 5,
  firstColumn: 1,
  columnCount: 15,
  targetPath: 'data/manual_paper_22bet.json',
  defaultRepository: 'sharp-signals/Tennis',
  defaultBranch: 'main',
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Fenzobot')
    .addItem('Sincronizar métricas PAPER 22Bet', 'syncPaperTradingToGitHub')
    .addItem('Ativar sincronização automática', 'installPaperTradingSync')
    .addToUi();
}

function syncPaperTradingToGitHub() {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');

  const repository = properties.getProperty('GITHUB_REPOSITORY') || PAPER_22BET_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || PAPER_22BET_SYNC.defaultBranch;
  const payload = buildPaperTradingPayload_();
  const apiUrl = 'https://api.github.com/repos/' + repository + '/contents/' + PAPER_22BET_SYNC.targetPath;
  const headers = {
    Authorization: 'Bearer ' + token,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };

  const existingResponse = UrlFetchApp.fetch(apiUrl + '?ref=' + encodeURIComponent(branch), {
    method: 'get', headers: headers, muteHttpExceptions: true,
  });
  let sha = null;
  if (existingResponse.getResponseCode() === 200) {
    const existing = JSON.parse(existingResponse.getContentText());
    sha = existing.sha;
    const decoded = Utilities.newBlob(Utilities.base64DecodeWebSafe(existing.content || '')).getDataAsString();
    try {
      const previous = JSON.parse(decoded);
      if (previous.data_fingerprint === payload.data_fingerprint) {
        return 'Sem alterações no registo PAPER 22Bet.';
      }
    } catch (error) {
      // Um ficheiro antigo/corrompido é substituído pelo resumo atual.
    }
  } else if (existingResponse.getResponseCode() !== 404) {
    throw new Error('GitHub devolveu HTTP ' + existingResponse.getResponseCode() + ': ' + existingResponse.getContentText());
  }

  const body = {
    message: 'chore: sincronizar métricas PAPER 22Bet [skip ci]',
    content: Utilities.base64EncodeWebSafe(JSON.stringify(payload, null, 2)),
    branch: branch,
  };
  if (sha) body.sha = sha;
  const writeResponse = UrlFetchApp.fetch(apiUrl, {
    method: 'put', headers: headers, contentType: 'application/json',
    payload: JSON.stringify(body), muteHttpExceptions: true,
  });
  if (writeResponse.getResponseCode() < 200 || writeResponse.getResponseCode() >= 300) {
    throw new Error('Não foi possível publicar o resumo: HTTP ' + writeResponse.getResponseCode() + ': ' + writeResponse.getContentText());
  }
  return 'Métricas PAPER 22Bet sincronizadas com sucesso.';
}

function installPaperTradingSync() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'syncPaperTradingToGitHub')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('syncPaperTradingToGitHub').timeBased().everyMinutes(30).create();
  return 'Sincronização automática ativada: verifica a Sheet a cada 30 minutos e só publica se houver alterações.';
}

function buildPaperTradingPayload_() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const lastRow = sheet.getLastRow();
  const rowCount = Math.max(0, lastRow - PAPER_22BET_SYNC.headerRow);
  const rows = rowCount ? sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, PAPER_22BET_SYNC.firstColumn, rowCount, PAPER_22BET_SYNC.columnCount).getValues() : [];
  const activeRows = rows.filter(row => row[0] && row[1] && row[5]);
  const summary = newStats_();
  const byMarket = {};
  const bySide = {};
  activeRows.forEach(row => {
    const market = row[5] === 'Vencedor' ? 'Moneyline' : String(row[5]);
    const side = String(row[7] || 'Sem perfil');
    if (!byMarket[market]) byMarket[market] = newStats_();
    if (!bySide[side]) bySide[side] = newStats_();
    addRowToStats_(summary, row);
    addRowToStats_(byMarket[market], row);
    addRowToStats_(bySide[side], row);
  });

  const fingerprint = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(activeRows),
  ).map(byte => ('0' + (byte & 0xff).toString(16)).slice(-2)).join('');
  return {
    schema_version: 1,
    source: {
      label: 'Track Record PAPER Trading — 22Bet',
      url: spreadsheet.getUrl(),
      reference_bookmaker: '22Bet',
      synced_at_utc: new Date().toISOString(),
    },
    data_fingerprint: fingerprint,
    summary: finishStats_(summary),
    by_market: finishCollection_(byMarket),
    by_side: finishCollection_(bySide),
  };
}

function newStats_() {
  return {total_entries: 0, settled: 0, pending: 0, wins: 0, losses: 0, pushes: 0, units: 0, stake: 0, odds: []};
}

function addRowToStats_(stats, row) {
  stats.total_entries += 1;
  const result = String(row[12] || '').trim().toUpperCase();
  const odd = Number(row[9]);
  const stake = Number(row[10]);
  const profit = Number(row[13]);
  if (Number.isFinite(odd)) stats.odds.push(odd);
  if (result === 'GANHOU' || result === 'PERDEU') {
    stats.settled += 1;
    stats.wins += result === 'GANHOU' ? 1 : 0;
    stats.losses += result === 'PERDEU' ? 1 : 0;
    if (Number.isFinite(stake)) stats.stake += stake;
    if (Number.isFinite(profit)) stats.units += profit;
  } else if (result === 'VOID') {
    stats.pushes += 1;
    if (Number.isFinite(profit)) stats.units += profit;
  } else {
    stats.pending += 1;
  }
}

function finishStats_(stats) {
  const round = value => Math.round(value * 1000) / 1000;
  return {
    total_entries: stats.total_entries,
    settled: stats.settled,
    pending: stats.pending,
    wins: stats.wins,
    losses: stats.losses,
    pushes: stats.pushes,
    win_rate_pct: stats.settled ? round(100 * stats.wins / stats.settled) : null,
    units: round(stats.units),
    roi_pct: stats.stake ? round(100 * stats.units / stats.stake) : null,
    average_odd: stats.odds.length ? round(stats.odds.reduce((total, odd) => total + odd, 0) / stats.odds.length) : null,
  };
}

function finishCollection_(collection) {
  const result = {};
  Object.keys(collection).forEach(key => result[key] = finishStats_(collection[key]));
  return result;
}
