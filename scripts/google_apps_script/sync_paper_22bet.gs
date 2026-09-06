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
  validationPath: 'data/validation/green-strong-v1.json',
  trackingHeaders: [
    'Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC',
    '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status',
  ],
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Fenzobot')
    .addItem('Sincronizar métricas PAPER 22Bet', 'syncPaperTradingToGitHub')
    .addItem('Instalar colunas GREEN_STRONG_V1', 'installGreenStrongTrackingColumns')
    .addItem('Ativar sincronização automática', 'installPaperTradingSync')
    .addToUi();
}

function syncPaperTradingToGitHub() {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');

  const repository = properties.getProperty('GITHUB_REPOSITORY') || PAPER_22BET_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || PAPER_22BET_SYNC.defaultBranch;
  const payload = buildPaperTradingPayload_(token, repository, branch);
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

function installGreenStrongTrackingColumns() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn, 1, width).getValues()[0];
  let next = headers.length;
  missingTrackingHeaders_(headers).forEach(header => {
    if (headers.indexOf(header) === -1) {
      sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn + next).setValue(header);
      headers.push(header);
      next += 1;
    }
  });
  return 'Colunas GREEN_STRONG_V1 instaladas sem alterar as 15 colunas existentes.';
}

function missingTrackingHeaders_(headers) {
  return PAPER_22BET_SYNC.trackingHeaders.filter(header => headers.indexOf(header) === -1);
}

function onEdit(e) {
  if (!e || !e.range || e.range.getSheet().getName() !== PAPER_22BET_SYNC.sheetName) return;
  if (e.range.getRow() <= PAPER_22BET_SYNC.headerRow || !e.value) return;
  const sheet = e.range.getSheet();
  const map = trackingColumnMap_(sheet);
  if (map['Fenzobot Snapshot Key'] !== e.range.getColumn()) return;
  const stampColumn = map['Selected At UTC'];
  if (!stampColumn) return;
  const stampCell = sheet.getRange(e.range.getRow(), stampColumn);
  if (!stampCell.getValue()) stampCell.setValue(new Date().toISOString());
}

function installPaperTradingSync() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'syncPaperTradingToGitHub')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('syncPaperTradingToGitHub').timeBased().everyMinutes(30).create();
  return 'Sincronização automática ativada: verifica a Sheet a cada 30 minutos e só publica se houver alterações.';
}

function buildPaperTradingPayload_(token, repository, branch) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const lastRow = sheet.getLastRow();
  const rowCount = Math.max(0, lastRow - PAPER_22BET_SYNC.headerRow);
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn, 1, width).getValues()[0];
  const rows = rowCount ? sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, PAPER_22BET_SYNC.firstColumn, rowCount, width).getValues() : [];
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

  const tracking = trackingIndexes_(headers);
  const green = tracking.complete ? fetchGreenStrongIndex_(token, repository, branch) : {byKey: {}, eligibleCount: null, available: false};
  const guerraStats = newStats_();
  const guerraByMarket = {};
  const guerraBySide = {};
  const guerraReviewRoutes = {};
  const selectedSnapshotKeys = {};
  const underdogPairs = {};
  const linkage = {LINKED_EX_ANTE: 0, SNAPSHOT_NOT_FOUND: 0, NOT_GREEN_STRONG: 0, SELECTION_AFTER_START: 0, MISSING_SELECTION_TIMESTAMP: 0, UNAVAILABLE: 0};
  rows.forEach((row, offset) => {
    if (!(row[0] && row[1] && row[5]) || !tracking.complete || String(row[tracking.strategy] || '').trim() !== 'GUERRA_SELECTION_V1') return;
    const status = validateGuerraSelection_(row, tracking, green.byKey, green.available);
    linkage[status] = (linkage[status] || 0) + 1;
    sheet.getRange(PAPER_22BET_SYNC.headerRow + 1 + offset, tracking.status + 1).setValue(status);
    if (status !== 'LINKED_EX_ANTE') return;
    const snapshotKey = String(row[tracking.snapshot]).trim();
    const cohort = green.byKey[snapshotKey] || {};
    selectedSnapshotKeys[snapshotKey] = true;
    const market = row[5] === 'Vencedor' ? 'Moneyline' : String(row[5]);
    const side = String(row[7] || 'Sem perfil');
    const route = moneylineReviewRoute_(row[tracking.reviewOdd]);
    if (!guerraByMarket[market]) guerraByMarket[market] = newStats_();
    if (!guerraBySide[side]) guerraBySide[side] = newStats_();
    addRowToStats_(guerraStats, row);
    addRowToStats_(guerraByMarket[market], row);
    addRowToStats_(guerraBySide[side], row);
    guerraReviewRoutes[route] = (guerraReviewRoutes[route] || 0) + 1;
    if (cohort.selected_side_market_position === 'UNDERDOG') {
      if (!underdogPairs[snapshotKey]) underdogPairs[snapshotKey] = {moneyline: false, positiveHandicap: false};
      const leg = manualLegType_(row, tracking);
      if (leg === 'MONEYLINE') underdogPairs[snapshotKey].moneyline = true;
      if (leg === 'POSITIVE_HANDICAP_GAMES') underdogPairs[snapshotKey].positiveHandicap = true;
    }
  });

  const pairValues = Object.keys(underdogPairs).map(key => underdogPairs[key]);
  const pairCompleteness = {
    underdog_selected_candidates: pairValues.length,
    complete_moneyline_positive_handicap_pairs: pairValues.filter(pair => pair.moneyline && pair.positiveHandicap).length,
    moneyline_only: pairValues.filter(pair => pair.moneyline && !pair.positiveHandicap).length,
    positive_handicap_only: pairValues.filter(pair => !pair.moneyline && pair.positiveHandicap).length,
    incomplete_or_unrecognized: pairValues.filter(pair => !pair.moneyline && !pair.positiveHandicap).length,
  };
  const selectedCandidates = Object.keys(selectedSnapshotKeys).length;
  const strategyAggregate = {
    summary: finishStats_(guerraStats),
    paper_entries: guerraStats.total_entries,
    selected_candidates: selectedCandidates,
    by_market: finishCollection_(guerraByMarket),
    by_side: finishCollection_(guerraBySide),
    moneyline_review_routes: guerraReviewRoutes,
    underdog_pair_completeness: pairCompleteness,
    linkage: linkage,
    eligible_green_strong: green.eligibleCount,
    selection_rate_pct: green.eligibleCount ? Math.round(10000 * selectedCandidates / green.eligibleCount) / 100 : null,
    status: tracking.complete && green.available ? 'AVAILABLE' : 'UNAVAILABLE',
  };
  const fingerprintRows = tracking.complete ? activeRows.map(row => row.filter((value, index) => index !== tracking.status)) : activeRows;
  const fingerprint = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    semanticFingerprintMaterial_(fingerprintRows, {
      summary: finishStats_(summary), by_market: finishCollection_(byMarket),
      by_side: finishCollection_(bySide), by_strategy: strategyAggregate,
    }),
  ).map(byte => ('0' + (byte & 0xff).toString(16)).slice(-2)).join('');
  return {
    schema_version: 2,
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
    by_strategy: {
      GUERRA_SELECTION_V1: strategyAggregate,
    },
  };
}

function trackingIndexes_(headers) {
  const indexes = {};
  PAPER_22BET_SYNC.trackingHeaders.forEach(header => indexes[header] = headers.indexOf(header));
  return {
    snapshot: indexes['Fenzobot Snapshot Key'], strategy: indexes['Selection Strategy'],
    selectedAt: indexes['Selected At UTC'], reviewOdd: indexes['22Bet Moneyline Review Odd'],
    handicapLine: indexes['22Bet Handicap Games Line'],
    status: indexes['Validation Status'],
    complete: PAPER_22BET_SYNC.trackingHeaders.every(header => indexes[header] >= 0),
  };
}

function manualLegType_(row, tracking) {
  const market = row[5] === 'Vencedor' ? 'moneyline' : String(row[5] || '').trim().toLowerCase();
  const odd = Number(row[9]);
  if (!Number.isFinite(odd) || odd <= 1) return 'UNAVAILABLE';
  if (market === 'moneyline') return 'MONEYLINE';
  const line = Number(row[tracking.handicapLine]);
  if (market.indexOf('handicap') >= 0 && market.indexOf('game') >= 0 && Number.isFinite(line) && line > 0) {
    return 'POSITIVE_HANDICAP_GAMES';
  }
  return 'UNAVAILABLE';
}

function semanticFingerprintMaterial_(rowsWithoutValidationStatus, publicAggregates) {
  return JSON.stringify({sheet_rows: rowsWithoutValidationStatus, aggregates: publicAggregates});
}

function trackingColumnMap_(sheet) {
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, 1, 1, width).getValues()[0];
  const result = {};
  headers.forEach((header, index) => result[String(header)] = index + 1);
  return result;
}

function validateGuerraSelection_(row, tracking, byKey, indexAvailable) {
  if (!tracking.complete) return 'UNAVAILABLE';
  if (indexAvailable === false) return 'UNAVAILABLE';
  const key = String(row[tracking.snapshot] || '').trim();
  if (!key || !Object.prototype.hasOwnProperty.call(byKey, key)) return 'SNAPSHOT_NOT_FOUND';
  const cohort = byKey[key];
  if (!cohort.eligible) return 'NOT_GREEN_STRONG';
  const selectedAt = new Date(row[tracking.selectedAt]);
  if (!row[tracking.selectedAt] || Number.isNaN(selectedAt.getTime())) return 'MISSING_SELECTION_TIMESTAMP';
  const start = new Date(cohort.commence_time_utc);
  if (Number.isNaN(start.getTime())) return 'UNAVAILABLE';
  return selectedAt.getTime() < start.getTime() ? 'LINKED_EX_ANTE' : 'SELECTION_AFTER_START';
}

function moneylineReviewRoute_(rawOdd) {
  const odd = Number(rawOdd);
  if (!Number.isFinite(odd) || odd <= 1) return 'UNAVAILABLE';
  return odd >= 1.75 ? 'MONEYLINE_MANUAL_REVIEW' : 'HANDICAP_MANUAL_REVIEW';
}

function fetchGreenStrongIndex_(token, repository, branch) {
  if (!token || !repository) return {byKey: {}, eligibleCount: null, available: false};
  const url = 'https://api.github.com/repos/' + repository + '/contents/' + PAPER_22BET_SYNC.validationPath + '?ref=' + encodeURIComponent(branch);
  const response = UrlFetchApp.fetch(url, {method: 'get', headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json'}, muteHttpExceptions: true});
  if (response.getResponseCode() !== 200) return {byKey: {}, eligibleCount: null, available: false};
  try {
    const body = JSON.parse(response.getContentText());
    const document = JSON.parse(Utilities.newBlob(Utilities.base64DecodeWebSafe(body.content || '')).getDataAsString());
    const rows = document.prospective_classifications || [];
    const byKey = {};
    rows.forEach(row => { if (row.snapshot_key) byKey[String(row.snapshot_key)] = row; });
    return {byKey: byKey, eligibleCount: rows.filter(row => row.eligible === true).length, available: true};
  } catch (error) {
    return {byKey: {}, eligibleCount: null, available: false};
  }
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
