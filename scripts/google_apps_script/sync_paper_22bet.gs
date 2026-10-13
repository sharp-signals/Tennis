/**
 * CHANGE-2026-09-06-023
 * Publica apenas métricas agregadas da Sheet PAPER 22Bet no repositório.
 * Não publica a lista de apostas, notas ou dados pessoais.
 *
 * Antes de usar, definir nas Propriedades do script:
 * - GITHUB_TOKEN: fine-grained token com Contents: Read and write no Tennis
 * - GITHUB_REPOSITORY: sharp-signals/Tennis
 * - GOOGLE_SHEETS_SPREADSHEET_ID: ID da Sheet PAPER 22Bet (opcional;
 *   usa a Sheet oficial por omissão, para suportar projeto Apps Script autónomo)
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
  defaultSpreadsheetId: '1WY4D0yYxBUX5kOQHMoFnEHmDT1oXsGszyFoMUcXQ-8U',
  validationPath: 'data/validation/green-strong-v1.json',
  reportLinkagePath: 'data/validation/manual-paper-linkage-index-v1.json',
  factorIndexPath: 'data/validation/manual-paper-factor-index-v1.json',
  trackingHeaders: [
    'Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC',
    '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status',
    'Fenzobot Report Match Key', 'Fenzobot Report URL', 'Selection Time Precision',
    'Fenzobot Commence Time UTC',
  ],
  challengerTrackingHeaders: [
    'Challenger Índice Fenzobot', 'Challenger Cobertura %', 'Challenger Edge %',
  ],
  challengerEntrySheetName: 'Challenger · Entradas',
  challengerDashboardSheetName: 'Challenger · Gráficos',
  challengerLevelLabel: 'Challenger',
  challengerManualStrategy: 'CHALLENGER_125_EXPERIMENTAL_V1',
  challengerManualStakeUnits: 0.5,
  challengerManualMinimumEdgePct: 2.0,
  syncContractVersion: 5,
  // Índices legacy (A:O) usados exclusivamente como compatibilidade para
  // versões antigas da Sheet sem cabeçalhos reconhecíveis.
  legacyOperationalIndexes: {
    tour: 2, level: 3, surface: 4, market: 5, selection: 6,
    side: 7, odd: 9, stake: 10, result: 12, profit: 13,
  },
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Fenzobot')
    .addItem('Sincronizar métricas PAPER 22Bet', 'syncPaperTradingToGitHub')
    .addItem('Instalar colunas GREEN_STRONG_V1', 'installGreenStrongTrackingColumns')
    .addItem('Recuperar ligações Guerra aos relatórios', 'backfillGuerraReportLinks')
    .addItem('Preparar área Challenger · 0,5u', 'installChallengerPaperWorkspace')
    .addItem('Ativar sincronização automática', 'installPaperTradingSync')
    .addToUi();
}

function syncPaperTradingToGitHub() {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');

  const repository = properties.getProperty('GITHUB_REPOSITORY') || PAPER_22BET_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || PAPER_22BET_SYNC.defaultBranch;
  const spreadsheet = paperTradingSpreadsheet_();
  ensureGuerraTrackingColumns_(spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName));
  const reportIndex = fetchReportLinkageIndex_(token, repository, branch);
  const factorIndex = fetchManualFactorIndex_(token, repository, branch);
  recoverGuerraReportLinks_(spreadsheet, reportIndex);
  recoverChallengerReportLinks_(spreadsheet, reportIndex, factorIndex);
  const payload = buildPaperTradingPayload_(token, repository, branch);
  refreshChallengerPaperDashboard_(
    spreadsheet,
    ((payload.by_strategy || {}).CHALLENGER_125_EXPERIMENTAL_V1 || {}),
  );
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
    const decoded = Utilities.newBlob(
      Utilities.base64Decode(String(existing.content || '').replace(/\s/g, '')),
    ).getDataAsString();
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
    content: githubContentBase64_(JSON.stringify(payload, null, 2)),
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

/**
 * GitHub Contents exige Base64 de bytes. Codificar o Blob UTF-8 evita a
 * sobrecarga de texto do Apps Script, que em alguns projetos autónomos gera
 * uma sequência que a API rejeita como Base64 inválido.
 */
function githubContentBase64_(text) {
  const bytes = Utilities.newBlob(
    String(text), 'application/json', 'manual_paper_22bet.json',
  ).getBytes();
  return Utilities.base64Encode(bytes);
}

function installGreenStrongTrackingColumns() {
  const sheet = paperTradingSpreadsheet_().getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  ensureGuerraTrackingColumns_(sheet);
  return 'Colunas de ligação Fenzobot instaladas sem alterar as colunas operacionais existentes.';
}

function ensureGuerraTrackingColumns_(sheet) {
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
}

function backfillGuerraReportLinks() {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');
  const repository = properties.getProperty('GITHUB_REPOSITORY') || PAPER_22BET_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || PAPER_22BET_SYNC.defaultBranch;
  const spreadsheet = paperTradingSpreadsheet_();
  ensureGuerraTrackingColumns_(spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName));
  const result = recoverGuerraReportLinks_(
    spreadsheet,
    fetchReportLinkageIndex_(token, repository, branch),
  );
  return 'Ligações recuperadas: ' + result.linked + ' · por rever: ' + result.unmatched + '.';
}

function missingTrackingHeaders_(headers) {
  return PAPER_22BET_SYNC.trackingHeaders.filter(header => headers.indexOf(header) === -1);
}

function installChallenger125TrackingColumns() {
  const sheet = paperTradingSpreadsheet_().getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn, 1, width).getValues()[0];
  let next = headers.length;
  PAPER_22BET_SYNC.challengerTrackingHeaders.forEach(header => {
    if (headers.indexOf(header) === -1) {
      sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn + next).setValue(header);
      headers.push(header);
      next += 1;
    }
  });
  return 'Colunas Challenger 125 instaladas. São opcionais e não alteram linhas PAPER existentes.';
}

function installChallengerPaperWorkspace() {
  const spreadsheet = paperTradingSpreadsheet_();
  ensureChallengerPaperEntryOption_(spreadsheet);
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN') || '';
  const repository = properties.getProperty('GITHUB_REPOSITORY') || PAPER_22BET_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || PAPER_22BET_SYNC.defaultBranch;
  const payload = buildPaperTradingPayload_(token, repository, branch);
  refreshChallengerPaperDashboard_(
    spreadsheet,
    ((payload.by_strategy || {}).CHALLENGER_125_EXPERIMENTAL_V1 || {}),
  );
  return 'Área Challenger preparada: entradas e gráficos separados, stake fixa 0,5u.';
}

function ensureChallengerPaperEntryOption_(spreadsheet) {
  const name = PAPER_22BET_SYNC.challengerEntrySheetName;
  const sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);
  const headers = [
    'Data', 'Jogo', 'Tour', 'Nível', 'Piso', 'Tipo de mercado', 'Seleção',
    'Fav/Und', 'Pré/Live', 'Casa', 'Odd aposta', 'Stake (u)', 'EDGE',
    'Resultado', 'Lucro (u)', 'Notas', 'Fenzobot Snapshot Key',
    'Selected At UTC', 'Challenger Índice Fenzobot', 'Challenger Cobertura %',
    'Challenger Edge %', 'Validation Status',
  ];
  if (sheet.getMaxColumns() < headers.length) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(), headers.length - sheet.getMaxColumns());
  }
  sheet.getRange('A1:V2').breakApart();
  sheet.getRange('A1:V1').merge().setValue('CHALLENGER — ENTRADAS PAPER 0,5u');
  sheet.getRange('A2:V2').merge().setValue(
    'Registo experimental separado · edge mínimo 2% · não entra nos totais ATP/WTA principais',
  );
  sheet.getRange(PAPER_22BET_SYNC.headerRow, 1, 1, headers.length).setValues([headers]);
  sheet.getRange('A1:V1').setBackground('#162B52').setFontColor('#FFFFFF').setFontSize(16).setFontWeight('bold');
  sheet.getRange('A2:V2').setBackground('#EDE9FE').setFontColor('#4C1D95').setFontStyle('italic');
  sheet.getRange(PAPER_22BET_SYNC.headerRow, 1, 1, headers.length)
    .setBackground('#1E3A5F').setFontColor('#FFFFFF').setFontWeight('bold')
    .setHorizontalAlignment('center').setWrap(true);
  sheet.setFrozenRows(PAPER_22BET_SYNC.headerRow);
  sheet.setTabColor('#7C3AED');
  sheet.setColumnWidths(1, headers.length, 105);
  sheet.setColumnWidth(2, 220);
  sheet.setColumnWidth(7, 160);
  sheet.setColumnWidth(16, 220);

  const firstDataRow = PAPER_22BET_SYNC.headerRow + 1;
  const rows = Math.max(1, sheet.getMaxRows() - PAPER_22BET_SYNC.headerRow);
  sheet.getRange(firstDataRow, 3, rows, 1).setDataValidation(challengerListValidation_(['ATP'], 'Circuito Challenger ATP.'));
  sheet.getRange(firstDataRow, 4, rows, 1).setDataValidation(challengerListValidation_([PAPER_22BET_SYNC.challengerLevelLabel], 'Universo experimental separado.'));
  sheet.getRange(firstDataRow, 5, rows, 1).setDataValidation(challengerListValidation_(['Hard', 'Hard indoor', 'Clay', 'Grass'], 'Escolha o piso.'));
  sheet.getRange(firstDataRow, 6, rows, 1).setDataValidation(challengerListValidation_(['Vencedor', 'Handicap games', 'Handicap sets', 'Over/Under games', 'Outro'], 'Escolha o mercado.'));
  sheet.getRange(firstDataRow, 8, rows, 1).setDataValidation(challengerListValidation_(['Favorito', 'Underdog'], 'Perfil da seleção.'));
  sheet.getRange(firstDataRow, 9, rows, 1).setDataValidation(challengerListValidation_(['Pré-live'], 'Apenas entradas pré-live.'));
  sheet.getRange(firstDataRow, 10, rows, 1).setDataValidation(challengerListValidation_(['22Bet', 'Betfair'], 'Casa utilizada.'));
  sheet.getRange(firstDataRow, 14, rows, 1).setDataValidation(challengerListValidation_(['GANHOU', 'PERDEU', 'VOID'], 'Deixe vazio enquanto estiver pendente.'));
  const populatedRows = Math.max(0, sheet.getLastRow() - PAPER_22BET_SYNC.headerRow);
  if (populatedRows) {
    sheet.getRange(firstDataRow, 12, populatedRows, 1).setValue(PAPER_22BET_SYNC.challengerManualStakeUnits);
    const settlementInputs = sheet.getRange(firstDataRow, 10, populatedRows, 5).getValues();
    sheet.getRange(firstDataRow, 15, populatedRows, 1).setValues(
      settlementInputs.map(row => [challengerProfitValue_(row[0], row[1], row[2], row[4])]),
    );
  }
  sheet.getRange(firstDataRow, 1, rows, 14).setBackground('#FFF7D6');
  sheet.getRange(firstDataRow, 15, rows, 1).setBackground('#E6F4EA');
  sheet.getRange(firstDataRow, 16, rows, 7).setBackground('#F8FAFC');
}

function challengerListValidation_(values, helpText) {
  if (typeof SpreadsheetApp.newDataValidation !== 'function') return null;
  return SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(false)
    .setHelpText(helpText)
    .build();
}

function challengerProfitValue_(house, oddRaw, stakeRaw, resultRaw) {
  const result = String(resultRaw || '').trim().toUpperCase();
  const odd = Number(oddRaw);
  const stake = Number(stakeRaw);
  if (!result) return '';
  if (result === 'VOID') return 0;
  if (!Number.isFinite(stake) || stake <= 0) return '';
  if (result === 'PERDEU') return -stake;
  if (result !== 'GANHOU' || !Number.isFinite(odd) || odd <= 1) return '';
  const commissionFactor = normalisedHeader_(house) === 'betfair' ? 0.95 : 1;
  return Math.round(stake * (odd - 1) * commissionFactor * 10000) / 10000;
}

function normalisedTrackingColumn_(map, expected) {
  const wanted = normalisedHeader_(expected);
  const keys = Object.keys(map || {});
  for (let index = 0; index < keys.length; index += 1) {
    if (normalisedHeader_(keys[index]) === wanted) return map[keys[index]];
  }
  return null;
}

function paperDateIso_(value, timeZone) {
  if (Object.prototype.toString.call(value) === '[object Date]' && !Number.isNaN(value.getTime())) {
    return Utilities.formatDate(value, timeZone || 'Europe/Lisbon', 'yyyy-MM-dd');
  }
  const text = String(value || '').trim().toLowerCase();
  const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return iso[1] + '-' + iso[2] + '-' + iso[3];
  const months = {jan: '01', fev: '02', mar: '03', abr: '04', mai: '05', jun: '06', jul: '07', ago: '08', set: '09', out: '10', nov: '11', dez: '12'};
  const pt = text.match(/^(\d{1,2})-([a-zç]+)\.?-(\d{4})$/);
  if (!pt || !months[pt[2].slice(0, 3)]) return '';
  return pt[3] + '-' + months[pt[2].slice(0, 3)] + '-' + ('0' + pt[1]).slice(-2);
}

function paperName_(value) {
  return String(value || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function paperEditDistance_(a, b) {
  const previous = Array.from({length: b.length + 1}, (_, index) => index);
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    for (let j = 1; j <= b.length; j += 1) {
      current[j] = Math.min(
        current[j - 1] + 1,
        previous[j] + 1,
        previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
    for (let j = 0; j < current.length; j += 1) previous[j] = current[j];
  }
  return previous[b.length];
}

function paperPlayerMatches_(abbreviated, fullName) {
  const aliases = {saffiulin: 'safiullin'};
  const query = paperName_(abbreviated).split(' ').filter(Boolean).map(token => aliases[token] || token);
  const full = paperName_(fullName).split(' ').filter(Boolean);
  if (!query.length || !full.length) return false;
  const significant = query.filter(token => token.length >= 3);
  const tokens = significant.length ? significant : query;
  return tokens.every(token => full.some(candidate => (
    candidate === token ||
    (token.length >= 5 && candidate.length >= 5 && paperEditDistance_(token, candidate) <= 1)
  )));
}

function paperPairMatches_(game, record) {
  const players = String(game || '').split(/\s+x\s+/i);
  if (players.length !== 2) return false;
  return (
    paperPlayerMatches_(players[0], record.player_a) && paperPlayerMatches_(players[1], record.player_b)
  ) || (
    paperPlayerMatches_(players[0], record.player_b) && paperPlayerMatches_(players[1], record.player_a)
  );
}

function paperDayDifference_(leftIso, rightIso) {
  const left = new Date(String(leftIso) + 'T00:00:00Z');
  const right = new Date(String(rightIso) + 'T00:00:00Z');
  if (Number.isNaN(left.getTime()) || Number.isNaN(right.getTime())) return null;
  return Math.round((right.getTime() - left.getTime()) / 86400000);
}

function findPaperReportLink_(dateIso, game, records) {
  const candidates = (records || []).filter(record => {
    const reportDelta = paperDayDifference_(dateIso, record.report_date);
    const commenceDate = String(record.commence_time_utc || '').slice(0, 10);
    const commenceDelta = commenceDate ? paperDayDifference_(dateIso, commenceDate) : null;
    const dateMatches = (
      commenceDelta !== null && Math.abs(commenceDelta) <= 1
    ) || (
      reportDelta !== null && reportDelta >= -3 && reportDelta <= 3
    );
    return dateMatches && paperPairMatches_(game, record);
  }).map(record => Object.assign({}, record, {
    _delta: String(record.commence_time_utc || '').slice(0, 10)
      ? paperDayDifference_(dateIso, String(record.commence_time_utc).slice(0, 10))
      : paperDayDifference_(dateIso, record.report_date),
  }));
  if (!candidates.length) return null;
  // Uma versão repetida no dia da aposta pode ser apenas um relatório
  // self-described sem snapshot. Quando existe uma versão canónica da mesma
  // partida na janela segura, ela é a única capaz de sustentar o linkage.
  const canonical = candidates.filter(record => String(record.snapshot_key || '').trim());
  const preferred = canonical.length ? canonical : candidates;
  const distance = Math.min.apply(null, preferred.map(record => Math.abs(record._delta)));
  const nearest = preferred.filter(record => Math.abs(record._delta) === distance);
  nearest.sort((a, b) => {
    const canonicalA = a.snapshot_key ? 0 : 1;
    const canonicalB = b.snapshot_key ? 0 : 1;
    return canonicalA - canonicalB || String(a.report_match_key).localeCompare(String(b.report_match_key));
  });
  const identities = {};
  nearest.forEach(record => {
    identities[[paperName_(record.player_a), paperName_(record.player_b)].sort().join('|')] = true;
  });
  return Object.keys(identities).length === 1 ? nearest[0] : null;
}

function fetchReportLinkageIndex_(token, repository, branch) {
  if (!token || !repository) return {available: false, records: []};
  const url = 'https://api.github.com/repos/' + repository + '/contents/' + PAPER_22BET_SYNC.reportLinkagePath + '?ref=' + encodeURIComponent(branch);
  const response = UrlFetchApp.fetch(url, {method: 'get', headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json'}, muteHttpExceptions: true});
  if (response.getResponseCode() !== 200) return {available: false, records: []};
  try {
    const body = JSON.parse(response.getContentText());
    let document;
    if (body.content) {
      document = JSON.parse(Utilities.newBlob(
        Utilities.base64Decode(String(body.content).replace(/\s/g, '')),
      ).getDataAsString());
    } else if (body.download_url) {
      // GitHub deixa de devolver conteúdo inline quando o índice ultrapassa
      // 1 MB. O download_url mantém a recuperação funcional à medida que o
      // histórico cresce.
      const download = UrlFetchApp.fetch(body.download_url, {
        method: 'get', headers: {Authorization: 'Bearer ' + token}, muteHttpExceptions: true,
      });
      if (download.getResponseCode() !== 200) return {available: false, records: []};
      document = JSON.parse(download.getContentText());
    } else {
      return {available: false, records: []};
    }
    return {available: true, records: document.records || []};
  } catch (error) {
    return {available: false, records: []};
  }
}

function recoverGuerraReportLinks_(spreadsheet, reportIndex) {
  const sheet = spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet || !reportIndex || reportIndex.available !== true) return {linked: 0, unmatched: 0};
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, 1, 1, width).getValues()[0];
  const tracking = trackingIndexes_(headers);
  const map = trackingColumnMap_(sheet);
  const rowCount = Math.max(0, sheet.getLastRow() - PAPER_22BET_SYNC.headerRow);
  if (!rowCount) return {linked: 0, unmatched: 0};
  const rows = sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, 1, rowCount, width).getValues();
  const timeZone = spreadsheet.getSpreadsheetTimeZone ? spreadsheet.getSpreadsheetTimeZone() : 'Europe/Lisbon';
  let linked = 0;
  let unmatched = 0;
  rows.forEach(row => {
    if (!(row[0] && row[1] && row[tracking.market]) || isChallengerManualRow_(row, tracking)) return;
    row[tracking.strategy] = 'GUERRA_SELECTION_V1';
    let link = null;
    if (!String(row[tracking.reportMatchKey] || '').trim()) {
      link = findPaperReportLink_(paperDateIso_(row[0], timeZone), row[1], reportIndex.records);
      if (!link) {
        unmatched += 1;
        return;
      }
      row[tracking.snapshot] = link.snapshot_key || '';
      row[tracking.reportMatchKey] = link.report_match_key || '';
      row[tracking.reportUrl] = link.report_url || '';
      row[tracking.commenceTime] = link.commence_time_utc || '';
    }
    row[tracking.timePrecision] = row[tracking.selectedAt]
      ? 'EXACT_TIMESTAMP'
      : 'DATE_ONLY_RETROSPECTIVE';
    if (!row[tracking.handicapLine] && normalisedHeader_(marketName_(row, tracking)).indexOf('handicap') >= 0) {
      const line = String(row[6] || '').replace(',', '.').match(/([+-]\s*\d+(?:\.\d+)?)\s*$/);
      if (line) row[tracking.handicapLine] = Number(line[1].replace(/\s/g, ''));
    }
    linked += 1;
  });
  [
    tracking.snapshot, tracking.strategy, tracking.selectedAt, tracking.reviewOdd,
    tracking.handicapLine, tracking.status, tracking.reportMatchKey,
    tracking.reportUrl, tracking.timePrecision, tracking.commenceTime,
  ].filter(index => Number.isInteger(index) && index >= 0).forEach(index => {
    sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, index + 1, rowCount, 1)
      .setValues(rows.map(row => [row[index]]));
  });
  return {linked: linked, unmatched: unmatched};
}

function challengerEdgePct_(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric > 0 && numeric <= 1 ? numeric * 100 : numeric;
}

function enrichChallengerRow_(row, tracking, link, factorByKey) {
  if (!link || !String(link.snapshot_key || '').trim()) return false;
  if (tracking.snapshot >= 0) row[tracking.snapshot] = link.snapshot_key;
  if (tracking.strategy >= 0) row[tracking.strategy] = PAPER_22BET_SYNC.challengerManualStrategy;
  if (tracking.reportMatchKey >= 0 && link.report_match_key) row[tracking.reportMatchKey] = link.report_match_key;
  if (tracking.reportUrl >= 0 && link.report_url) row[tracking.reportUrl] = link.report_url;
  if (tracking.commenceTime >= 0 && link.commence_time_utc) row[tracking.commenceTime] = link.commence_time_utc;
  if (tracking.timePrecision >= 0) {
    row[tracking.timePrecision] = row[tracking.selectedAt]
      ? 'EXACT_TIMESTAMP'
      : 'DATE_ONLY_RETROSPECTIVE';
  }
  const snapshot = (factorByKey || {})[String(link.snapshot_key)] || null;
  const selectedSide = auditSelectionSide_(row, tracking, snapshot);
  const selectedIndex = snapshot && selectedSide
    ? Number(snapshot[selectedSide === 'a' ? 'ia' : 'ib'])
    : null;
  if (tracking.challengerIndex >= 0 && !String(row[tracking.challengerIndex] || '').trim() && Number.isFinite(selectedIndex)) {
    row[tracking.challengerIndex] = selectedIndex;
  }
  const sourceEdge = tracking.sourceEdge >= 0 ? challengerEdgePct_(row[tracking.sourceEdge]) : null;
  if (tracking.challengerEdge >= 0 && !String(row[tracking.challengerEdge] || '').trim() && sourceEdge !== null) {
    row[tracking.challengerEdge] = sourceEdge;
  }
  return true;
}

function recoverChallengerSheetLinks_(spreadsheet, sheet, reportIndex, factorIndex, mainSheet) {
  if (!sheet || !reportIndex || reportIndex.available !== true) return {linked: 0, unmatched: 0};
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, 1, 1, width).getValues()[0];
  const tracking = trackingIndexes_(headers);
  const rowCount = Math.max(0, sheet.getLastRow() - PAPER_22BET_SYNC.headerRow);
  if (!rowCount) return {linked: 0, unmatched: 0};
  const rows = sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, 1, rowCount, width).getValues();
  const timeZone = spreadsheet.getSpreadsheetTimeZone ? spreadsheet.getSpreadsheetTimeZone() : 'Europe/Lisbon';
  let linked = 0;
  let unmatched = 0;
  rows.forEach(row => {
    if (!(row[0] && row[1] && tracking.market >= 0 && row[tracking.market])) return;
    if (sheet === mainSheet && !isChallengerManualRow_(row, tracking)) return;
    let link = null;
    const existingKey = tracking.snapshot >= 0 ? String(row[tracking.snapshot] || '').trim() : '';
    if (existingKey) {
      link = {snapshot_key: existingKey};
    } else {
      link = findPaperReportLink_(paperDateIso_(row[0], timeZone), row[1], reportIndex.records);
    }
    if (!enrichChallengerRow_(row, tracking, link, (factorIndex || {}).byKey || {})) {
      unmatched += 1;
      return;
    }
    linked += 1;
  });
  const writable = [
    tracking.snapshot, tracking.strategy, tracking.reportMatchKey, tracking.reportUrl,
    tracking.timePrecision, tracking.commenceTime, tracking.challengerIndex,
    tracking.challengerEdge,
  ].filter((index, position, indexes) => Number.isInteger(index) && index >= 0 && indexes.indexOf(index) === position);
  writable.forEach(index => {
    sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, index + 1, rowCount, 1)
      .setValues(rows.map(row => [row[index]]));
  });
  return {linked: linked, unmatched: unmatched};
}

function recoverChallengerReportLinks_(spreadsheet, reportIndex, factorIndex) {
  const mainSheet = spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName);
  const dedicated = spreadsheet.getSheetByName(PAPER_22BET_SYNC.challengerEntrySheetName);
  const main = recoverChallengerSheetLinks_(spreadsheet, mainSheet, reportIndex, factorIndex, mainSheet);
  const separate = dedicated && dedicated !== mainSheet
    ? recoverChallengerSheetLinks_(spreadsheet, dedicated, reportIndex, factorIndex, mainSheet)
    : {linked: 0, unmatched: 0};
  return {
    linked: main.linked + separate.linked,
    unmatched: main.unmatched + separate.unmatched,
  };
}

function isChallengerLevel_(value) {
  return normalisedHeader_(value).indexOf('challenger') === 0;
}

function applyChallengerRowDefaults_(sheet, rowNumber, map, levelValue) {
  const strategyColumn = normalisedTrackingColumn_(map, 'Selection Strategy');
  const selectedAtColumn = normalisedTrackingColumn_(map, 'Selected At UTC');
  const stakeColumn = normalisedTrackingColumn_(map, 'Stake (u)');
  if (!strategyColumn) return;
  const strategyCell = sheet.getRange(rowNumber, strategyColumn);
  if (!isChallengerLevel_(levelValue)) {
    if (String(strategyCell.getValue() || '').trim() === PAPER_22BET_SYNC.challengerManualStrategy) {
      strategyCell.clearContent();
    }
    return;
  }
  strategyCell.setValue(PAPER_22BET_SYNC.challengerManualStrategy);
  if (stakeColumn) sheet.getRange(rowNumber, stakeColumn).setValue(PAPER_22BET_SYNC.challengerManualStakeUnits);
  if (selectedAtColumn) {
    const selectedAt = sheet.getRange(rowNumber, selectedAtColumn);
    if (!selectedAt.getValue()) selectedAt.setValue(new Date().toISOString());
  }
}

function onEdit(e) {
  if (!e || !e.range) return;
  const editedSheet = e.range.getSheet();
  const editedSheetName = editedSheet.getName();
  if (
    editedSheetName !== PAPER_22BET_SYNC.sheetName &&
    editedSheetName !== PAPER_22BET_SYNC.challengerEntrySheetName
  ) return;
  if (e.range.getRow() <= PAPER_22BET_SYNC.headerRow) return;
  const sheet = editedSheet;
  const map = trackingColumnMap_(sheet);
  if (editedSheetName === PAPER_22BET_SYNC.challengerEntrySheetName) {
    applyChallengerEntryDefaults_(sheet, e.range.getRow(), map);
    return;
  }
  const levelColumn = normalisedTrackingColumn_(map, 'Nível');
  if (levelColumn === e.range.getColumn()) {
    applyChallengerRowDefaults_(sheet, e.range.getRow(), map, e.value);
    return;
  }
  const resultColumn = normalisedTrackingColumn_(map, 'Resultado');
  const profitColumn = normalisedTrackingColumn_(map, 'Lucro (u)');
  const notesColumn = normalisedTrackingColumn_(map, 'Notas');
  if ([resultColumn, profitColumn, notesColumn].indexOf(e.range.getColumn()) >= 0) return;
  const strategyColumn = map['Selection Strategy'];
  const stampColumn = map['Selected At UTC'];
  const precisionColumn = map['Selection Time Precision'];
  if (!stampColumn || !strategyColumn) return;
  const rowValues = sheet.getRange(e.range.getRow(), 1, 1, Math.max(sheet.getLastColumn(), 16)).getValues()[0];
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, 1, 1, Math.max(sheet.getLastColumn(), 16)).getValues()[0];
  const tracking = trackingIndexes_(headers);
  if (!(rowValues[0] && rowValues[1] && rowValues[tracking.market])) return;
  sheet.getRange(e.range.getRow(), strategyColumn).setValue('GUERRA_SELECTION_V1');
  const stampCell = sheet.getRange(e.range.getRow(), stampColumn);
  if (!stampCell.getValue()) {
    stampCell.setValue(new Date().toISOString());
    if (precisionColumn) sheet.getRange(e.range.getRow(), precisionColumn).setValue('EXACT_TIMESTAMP');
  }
}

// O projeto oficial é autónomo (não bound à Sheet). Um simple trigger onEdit
// não recebe eventos nesse contexto, por isso o instalador cria este trigger
// explícito para carimbar o momento real das escolhas futuras.
function onPaperTradingEdit_(e) {
  onEdit(e);
}

function applyChallengerEntryDefaults_(sheet, rowNumber, map) {
  const tourColumn = normalisedTrackingColumn_(map, 'Tour');
  const levelColumn = normalisedTrackingColumn_(map, 'Nível');
  const stakeColumn = normalisedTrackingColumn_(map, 'Stake (u)');
  const selectedAtColumn = normalisedTrackingColumn_(map, 'Selected At UTC');
  const profitColumn = normalisedTrackingColumn_(map, 'Lucro (u)');
  if (tourColumn) sheet.getRange(rowNumber, tourColumn).setValue('ATP');
  if (levelColumn) sheet.getRange(rowNumber, levelColumn).setValue(PAPER_22BET_SYNC.challengerLevelLabel);
  if (stakeColumn) sheet.getRange(rowNumber, stakeColumn).setValue(PAPER_22BET_SYNC.challengerManualStakeUnits);
  if (profitColumn) {
    const houseColumn = normalisedTrackingColumn_(map, 'Casa');
    const oddColumn = normalisedTrackingColumn_(map, 'Odd aposta');
    const resultColumn = normalisedTrackingColumn_(map, 'Resultado');
    const stake = stakeColumn
      ? sheet.getRange(rowNumber, stakeColumn).getValue()
      : PAPER_22BET_SYNC.challengerManualStakeUnits;
    const profit = challengerProfitValue_(
      houseColumn ? sheet.getRange(rowNumber, houseColumn).getValue() : '',
      oddColumn ? sheet.getRange(rowNumber, oddColumn).getValue() : '',
      stake,
      resultColumn ? sheet.getRange(rowNumber, resultColumn).getValue() : '',
    );
    const profitCell = sheet.getRange(rowNumber, profitColumn);
    if (profit === '') profitCell.clearContent();
    else profitCell.setValue(profit);
  }
  if (selectedAtColumn) {
    const selectedAt = sheet.getRange(rowNumber, selectedAtColumn);
    if (!selectedAt.getValue()) selectedAt.setValue(new Date().toISOString());
  }
}

function installPaperTradingSync() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => [
      'syncPaperTradingToGitHub', 'onPaperTradingEdit_',
    ].indexOf(trigger.getHandlerFunction()) >= 0)
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('syncPaperTradingToGitHub').timeBased().everyMinutes(30).create();
  ScriptApp.newTrigger('onPaperTradingEdit_')
    .forSpreadsheet(paperTradingSpreadsheet_())
    .onEdit()
    .create();
  return 'Sincronização automática ativada: verifica a Sheet a cada 30 minutos e carimba novas escolhas no momento da edição.';
}

/**
 * Lê a área Challenger como uma fonte operacional independente. A comparação
 * de identidade evita que simuladores antigos, que devolvem sempre a folha
 * principal em getSheetByName(), dupliquem silenciosamente as entradas.
 */
function readChallengerEntrySource_(spreadsheet, mainSheet) {
  const sheet = spreadsheet.getSheetByName(PAPER_22BET_SYNC.challengerEntrySheetName);
  if (!sheet || sheet === mainSheet) {
    return {available: false, sheet: null, headers: [], tracking: trackingIndexes_([]), rows: []};
  }
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(
    PAPER_22BET_SYNC.headerRow,
    PAPER_22BET_SYNC.firstColumn,
    1,
    width,
  ).getValues()[0];
  const tracking = trackingIndexes_(headers);
  assertOperationalTracking_(tracking, headers);
  const rowCount = Math.max(0, sheet.getLastRow() - PAPER_22BET_SYNC.headerRow);
  const rows = rowCount
    ? sheet.getRange(
      PAPER_22BET_SYNC.headerRow + 1,
      PAPER_22BET_SYNC.firstColumn,
      rowCount,
      width,
    ).getValues().filter(row => row[0] && row[1] && row[tracking.market])
    : [];
  return {available: true, sheet: sheet, headers: headers, tracking: tracking, rows: rows};
}

function buildPaperTradingPayload_(token, repository, branch) {
  const spreadsheet = paperTradingSpreadsheet_();
  const sheet = spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const lastRow = sheet.getLastRow();
  const rowCount = Math.max(0, lastRow - PAPER_22BET_SYNC.headerRow);
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn, 1, width).getValues()[0];
  const tracking = trackingIndexes_(headers);
  assertOperationalTracking_(tracking, headers);
  const rows = rowCount ? sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, PAPER_22BET_SYNC.firstColumn, rowCount, width).getValues() : [];
  const activeRows = rows.filter(row => row[0] && row[1] && row[tracking.market]);
  const challengerSource = readChallengerEntrySource_(spreadsheet, sheet);
  // O agregado principal mantém-se exclusivamente PAPER normal. O Challenger
  // 125 manual tem universo e stake próprios, publicados abaixo por estratégia.
  const standardRows = activeRows.filter(row => !isChallengerManualRow_(row, tracking));
  const summary = newStats_();
  const byMarket = {};
  const bySide = {};
  standardRows.forEach(row => {
    const market = marketName_(row, tracking);
    const side = sideName_(row, tracking);
    if (!byMarket[market]) byMarket[market] = newStats_();
    if (!bySide[side]) bySide[side] = newStats_();
    addRowToStats_(summary, row, tracking);
    addRowToStats_(byMarket[market], row, tracking);
    addRowToStats_(bySide[side], row, tracking);
  });

  const green = tracking.complete ? fetchGreenStrongIndex_(token, repository, branch) : {byKey: {}, eligibleCount: null, available: false};
  const factorIndex = tracking.complete
    ? fetchManualFactorIndex_(token, repository, branch)
    : {byKey: {}, recordCount: null, available: false};
  const guerraStats = newStats_();
  const guerraByMarket = {};
  const guerraBySide = {};
  const guerraReviewRoutes = {};
  const flatStakeSimulation = newFlatStakeSimulation_();
  const selectedSnapshotKeys = {};
  const underdogPairs = {};
  const linkage = {
    LINKED_EX_ANTE: 0,
    LINKED_RETROSPECTIVE_CANONICAL: 0,
    LINKED_RETROSPECTIVE_LEGACY: 0,
    REPORT_LINK_NOT_FOUND: 0,
    SELECTION_AFTER_START: 0,
    MISSING_SELECTION_TIMESTAMP: 0,
    UNAVAILABLE: 0,
  };
  const selectedGreenSnapshotKeys = {};
  const guerraFactorGroups = {};
  const guerraSegmentGroups = {};
  const guerraAuditLegs = {};
  const guerraExecutedEdge = newExecutedEdgeAudit_();
  const guerraReferenceMovement = newReferenceMovementAudit_();
  const guerraAuditQuality = {
    linked_entries: 0,
    canonical_entries: 0,
    legacy_entries: 0,
    exact_timestamp_entries: 0,
    retrospective_entries: 0,
    factor_index_matches: 0,
    factor_audit_eligible_entries: 0,
    selected_side_unresolved: 0,
    factor_index_missing: 0,
    duplicate_exact_legs: 0,
  };
  const challengerStats = newStats_();
  const challengerByMarket = {};
  const challengerBySide = {};
  const challengerByIndexBand = {};
  const challengerByCoverageBand = {};
  const challengerByEdgeBand = {};
  const challengerValidation = {MANUAL_CHALLENGER_RECORDED: 0, MISSING_SNAPSHOT_KEY: 0, MISSING_SELECTION_TIMESTAMP: 0, INVALID_CHALLENGER_STAKE: 0, INVALID_CHALLENGER_EDGE: 0};
  const recordChallengerRow = (row, rowTracking, statusWriter) => {
    const challengerStatus = validateManualChallengerSelection_(row, rowTracking);
    challengerValidation[challengerStatus] = (challengerValidation[challengerStatus] || 0) + 1;
    statusWriter(challengerStatus);
    if (challengerStatus !== 'MANUAL_CHALLENGER_RECORDED') return;
    const market = marketName_(row, rowTracking);
    const side = sideName_(row, rowTracking);
    const indexBand = challengerIndexBand_(row, rowTracking);
    const coverageBand = challengerCoverageBand_(row, rowTracking);
    const edgeBand = challengerEdgeBand_(row, rowTracking);
    [[challengerByMarket, market], [challengerBySide, side], [challengerByIndexBand, indexBand], [challengerByCoverageBand, coverageBand], [challengerByEdgeBand, edgeBand]].forEach(pair => {
      if (!pair[0][pair[1]]) pair[0][pair[1]] = newStats_();
    });
    addRowToStats_(challengerStats, row, rowTracking);
    addRowToStats_(challengerByMarket[market], row, rowTracking);
    addRowToStats_(challengerBySide[side], row, rowTracking);
    addRowToStats_(challengerByIndexBand[indexBand], row, rowTracking);
    addRowToStats_(challengerByCoverageBand[coverageBand], row, rowTracking);
    addRowToStats_(challengerByEdgeBand[edgeBand], row, rowTracking);
  };
  rows.forEach((row, offset) => {
    if (isChallengerManualRow_(row, tracking)) {
      recordChallengerRow(row, tracking, status => {
        if (tracking.status >= 0) sheet.getRange(PAPER_22BET_SYNC.headerRow + 1 + offset, tracking.status + 1).setValue(status);
      });
      return;
    }
    if (!(row[0] && row[1] && row[tracking.market]) || !tracking.complete || String(row[tracking.strategy] || '').trim() !== 'GUERRA_SELECTION_V1') return;
    const status = validateGuerraSelection_(row, tracking, green.byKey, green.available);
    linkage[status] = (linkage[status] || 0) + 1;
    sheet.getRange(PAPER_22BET_SYNC.headerRow + 1 + offset, tracking.status + 1).setValue(status);
    if (!isLinkedGuerraStatus_(status)) return;
    const snapshotKey = String(row[tracking.snapshot]).trim();
    const cohort = green.byKey[snapshotKey] || {};
    const reportMatchKey = String(row[tracking.reportMatchKey] || '').trim();
    const candidateKey = snapshotKey || reportMatchKey;
    if (!candidateKey) return;
    selectedSnapshotKeys[candidateKey] = true;
    if (snapshotKey && cohort.eligible === true) selectedGreenSnapshotKeys[snapshotKey] = true;
    const market = marketName_(row, tracking);
    const side = sideName_(row, tracking);
    const route = moneylineReviewRoute_(row[tracking.reviewOdd]);
    if (!guerraByMarket[market]) guerraByMarket[market] = newStats_();
    if (!guerraBySide[side]) guerraBySide[side] = newStats_();
    addRowToStats_(guerraStats, row, tracking);
    addRowToFlatStakeSimulation_(flatStakeSimulation, row, tracking);
    addRowToStats_(guerraByMarket[market], row, tracking);
    addRowToStats_(guerraBySide[side], row, tracking);
    guerraReviewRoutes[route] = (guerraReviewRoutes[route] || 0) + 1;
    addGuerraAuditRow_(
      guerraFactorGroups,
      guerraSegmentGroups,
      guerraAuditQuality,
      guerraAuditLegs,
      row,
      tracking,
      status,
      factorIndex.byKey[snapshotKey] || null,
      candidateKey,
    );
    addGuerraExecutionAudit_(
      guerraExecutedEdge,
      guerraReferenceMovement,
      row,
      tracking,
      status,
      factorIndex.byKey[snapshotKey] || null,
    );
    if (normalisedHeader_(sideName_(row, tracking)) === 'underdog') {
      if (!underdogPairs[candidateKey]) underdogPairs[candidateKey] = {moneyline: false, positiveHandicap: false};
      const leg = manualLegType_(row, tracking);
      if (leg === 'MONEYLINE') underdogPairs[candidateKey].moneyline = true;
      if (leg === 'POSITIVE_HANDICAP_GAMES') underdogPairs[candidateKey].positiveHandicap = true;
    }
  });
  challengerSource.rows.forEach((row, offset) => {
    recordChallengerRow(row, challengerSource.tracking, status => {
      if (challengerSource.tracking.status >= 0) {
        challengerSource.sheet.getRange(
          PAPER_22BET_SYNC.headerRow + 1 + offset,
          challengerSource.tracking.status + 1,
        ).setValue(status);
      }
    });
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
    selected_green_strong_candidates: Object.keys(selectedGreenSnapshotKeys).length,
    selection_rate_pct: green.eligibleCount
      ? Math.round(10000 * Object.keys(selectedGreenSnapshotKeys).length / green.eligibleCount) / 100
      : null,
    temporal_claims: 'RETROSPECTIVE_DATE_ONLY_SEPARATED_FROM_EXACT_TIMESTAMP',
    status: tracking.complete ? 'AVAILABLE' : 'UNAVAILABLE',
    flat_stake_simulation: finishFlatStakeSimulation_(
      flatStakeSimulation,
      tracking.complete,
    ),
    audit_v1: {
      status: tracking.complete && factorIndex.available ? 'AVAILABLE' : 'DEGRADED',
      privacy_contract: 'AGGREGATES_ONLY_NO_INDIVIDUAL_SELECTIONS',
      factor_index_status: factorIndex.available ? 'AVAILABLE' : 'UNAVAILABLE',
      factor_index_records: factorIndex.recordCount,
      quality: guerraAuditQuality,
      factors: finishGuerraFactorAudit_(guerraFactorGroups),
      segments: finishGuerraSegmentAudit_(guerraSegmentGroups),
      executed_edge_v1: finishExecutedEdgeAudit_(guerraExecutedEdge),
      reference_market_movement_v1: finishReferenceMovementAudit_(
        guerraReferenceMovement,
      ),
      sample_policy: {
        informative_below: 20,
        directional_from: 20,
        weight_review_from: 40,
        maximum_weight_change_per_cycle: 0.5,
      },
      claims: 'DESCRIPTIVE_ONLY_NO_AUTOMATIC_WEIGHT_CHANGE',
    },
  };
  const challengerAggregate = {
    summary: finishStats_(challengerStats),
    paper_entries: challengerStats.total_entries,
    fixed_stake_units: PAPER_22BET_SYNC.challengerManualStakeUnits,
    by_market: finishCollection_(challengerByMarket),
    by_side: finishCollection_(challengerBySide),
    by_fenzobot_index_band: finishCollection_(challengerByIndexBand),
    by_coverage_band: finishCollection_(challengerByCoverageBand),
    by_edge_band: finishCollection_(challengerByEdgeBand),
    validation: challengerValidation,
    status: challengerStats.total_entries ? 'AVAILABLE' : 'UNAVAILABLE',
  };
  const fingerprintRows = {
    standard_and_legacy_challenger: tracking.complete
      ? activeRows.map(row => row.filter((value, index) => index !== tracking.status))
      : activeRows,
    dedicated_challenger: challengerSource.rows.map(row => row.filter(
      (value, index) => index !== challengerSource.tracking.status,
    )),
  };
  const fingerprint = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    semanticFingerprintMaterial_(fingerprintRows, {
      summary: finishStats_(summary), by_market: finishCollection_(byMarket),
      by_side: finishCollection_(bySide), by_strategy: strategyAggregate,
      challenger_manual: challengerAggregate,
    }),
  ).map(byte => ('0' + (byte & 0xff).toString(16)).slice(-2)).join('');
  return {
    schema_version: 2,
    source: {
      label: 'Track Record PAPER Trading — 22Bet',
      url: spreadsheet.getUrl(),
      reference_bookmaker: '22Bet',
      synced_at_utc: new Date().toISOString(),
      sync_contract_version: PAPER_22BET_SYNC.syncContractVersion,
      // Só publica a posição das colunas operacionais, nunca valores de
      // linhas individuais. Torna auditável a leitura depois de mudanças na
      // Sheet (por exemplo, a coluna Casa inserida antes da odd).
      operational_columns: publicOperationalColumnMap_(headers, tracking),
      challenger_entry_sheet: PAPER_22BET_SYNC.challengerEntrySheetName,
      challenger_operational_columns: challengerSource.available
        ? publicOperationalColumnMap_(challengerSource.headers, challengerSource.tracking)
        : null,
    },
    data_fingerprint: fingerprint,
    summary: finishStats_(summary),
    by_market: finishCollection_(byMarket),
    by_side: finishCollection_(bySide),
    by_strategy: {
      GUERRA_SELECTION_V1: strategyAggregate,
      CHALLENGER_125_EXPERIMENTAL_V1: challengerAggregate,
    },
  };
}

/**
 * Resolve a Sheet sem depender de um Apps Script associado ao ficheiro.
 * Isto permite criar o projeto diretamente em script.google.com quando o
 * projeto bound original deixou de estar acessível.
 */
function paperTradingSpreadsheet_() {
  const properties = typeof PropertiesService !== 'undefined'
    ? PropertiesService.getScriptProperties()
    : null;
  const configuredId = properties
    ? properties.getProperty('GOOGLE_SHEETS_SPREADSHEET_ID')
    : null;
  const spreadsheetId = configuredId || PAPER_22BET_SYNC.defaultSpreadsheetId;
  if (!spreadsheetId) {
    throw new Error('Falta GOOGLE_SHEETS_SPREADSHEET_ID nas Propriedades do script.');
  }
  let spreadsheet = null;
  if (typeof SpreadsheetApp.openById === 'function') {
    spreadsheet = SpreadsheetApp.openById(spreadsheetId);
    if (spreadsheet) return spreadsheet;
  }
  // Em alguns projetos autónomos a abertura por ID pode devolver nulo apesar
  // de a conta ter acesso; repetir pela URL canónica da mesma Sheet.
  if (typeof SpreadsheetApp.openByUrl === 'function') {
    spreadsheet = SpreadsheetApp.openByUrl(
      'https://docs.google.com/spreadsheets/d/' + spreadsheetId + '/edit',
    );
    if (spreadsheet) return spreadsheet;
  }
  // Compatibilidade com execução bound e com o simulador Node dos testes.
  if (typeof SpreadsheetApp.getActiveSpreadsheet === 'function') {
    const active = SpreadsheetApp.getActiveSpreadsheet();
    if (active) return active;
  }
  throw new Error('Não foi possível abrir a Sheet PAPER 22Bet. Confirme o ID e o acesso da conta fenzobot@gmail.com.');
}

function trackingIndexes_(headers) {
  const indexes = {};
  PAPER_22BET_SYNC.trackingHeaders.forEach(header => indexes[header] = headers.indexOf(header));
  return {
    snapshot: indexes['Fenzobot Snapshot Key'], strategy: indexes['Selection Strategy'],
    selectedAt: indexes['Selected At UTC'], reviewOdd: indexes['22Bet Moneyline Review Odd'],
    handicapLine: indexes['22Bet Handicap Games Line'],
    status: indexes['Validation Status'],
    reportMatchKey: indexes['Fenzobot Report Match Key'],
    reportUrl: indexes['Fenzobot Report URL'],
    timePrecision: indexes['Selection Time Precision'],
    commenceTime: indexes['Fenzobot Commence Time UTC'],
    challengerIndex: headerIndex_(headers, 'Challenger Índice Fenzobot'),
    challengerCoverage: headerIndex_(headers, 'Challenger Cobertura %'),
    challengerEdge: headerIndex_(headers, 'Challenger Edge %'),
    sourceEdge: headerIndex_(headers, 'EDGE'),
    tour: operationalIndex_(headers, 'Tour', 'tour'),
    level: operationalIndex_(headers, 'Nível', 'level'),
    surface: operationalIndex_(headers, 'Piso', 'surface'),
    house: operationalIndex_(headers, 'Casa', 'house'),
    market: operationalIndex_(headers, 'Tipo de mercado', 'market'),
    selection: operationalIndex_(headers, 'Seleção', 'selection'),
    side: operationalIndex_(headers, 'Fav/Und', 'side'),
    odd: operationalIndex_(headers, 'Odd aposta', 'odd'),
    stake: operationalIndex_(headers, 'Stake (u)', 'stake'),
    result: operationalIndex_(headers, 'Resultado', 'result'),
    profit: operationalIndex_(headers, 'Lucro (u)', 'profit'),
    complete: PAPER_22BET_SYNC.trackingHeaders.slice(0, 6).every(header => indexes[header] >= 0),
    reportComplete: PAPER_22BET_SYNC.trackingHeaders.every(header => indexes[header] >= 0),
  };
}

/**
 * Falhar antes de publicar é preferível a transformar, por engano, todas as
 * apostas em pendentes quando alguém insere, move ou renomeia uma coluna.
 * O dashboard conserva o último resumo validado até a Sheet ficar legível.
 */
function assertOperationalTracking_(tracking, headers) {
  const required = ['market', 'side', 'odd', 'stake', 'result', 'profit'];
  const missing = required.filter(field => !Number.isInteger(tracking[field]) || tracking[field] < 0 || tracking[field] >= headers.length);
  const duplicate = required.some((field, index) => required.slice(index + 1).some(other => tracking[field] === tracking[other]));
  if (missing.length || duplicate) {
    const visible = headers.map(value => String(value || '').trim()).filter(Boolean).join(' | ');
    throw new Error(
      'Contrato operacional da Sheet não reconhecido; não foi publicado nenhum resumo. ' +
      'Campos em falta: ' + (missing.length ? missing.join(', ') : 'nenhum') +
      (duplicate ? ' · colunas operacionais duplicadas' : '') +
      ' · Cabeçalhos lidos: ' + visible,
    );
  }
}

function operationalIndex_(headers, header, legacyKey) {
  const aliases = {
    tour: ['Tour', 'Circuito'],
    level: ['Nível', 'Nivel', 'Circuito'],
    surface: ['Piso', 'Superfície', 'Superficie'],
    house: ['Casa', 'Bookmaker'],
    market: ['Tipo de mercado', 'Mercado'],
    selection: ['Seleção', 'Selecao', 'Pick'],
    side: ['Fav/Und', 'Favorito/Underdog'],
    odd: ['Odd aposta', 'Odd 22Bet', 'Odd 22bet', 'Odd'],
    stake: ['Stake (u)', 'Stake', 'Unidades'],
    result: ['Resultado', 'Resultado final'],
    profit: ['Lucro (u)', 'Lucro', 'Profit (u)'],
  };
  const candidates = aliases[legacyKey] || [header];
  for (let index = 0; index < candidates.length; index += 1) {
    const resolved = headerIndex_(headers, candidates[index]);
    if (resolved >= 0) return resolved;
  }
  // A folha original tinha exatamente A:O. Só esta forma histórica pode usar
  // índices fixos; uma folha alargada tem de se identificar pelos cabeçalhos.
  return headers.length <= PAPER_22BET_SYNC.columnCount
    ? PAPER_22BET_SYNC.legacyOperationalIndexes[legacyKey]
    : -1;
}

function normalisedHeader_(value) {
  return String(value == null ? '' : value)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[\u00a0\s]+/g, ' ')
    .trim()
    .toLowerCase();
}

function headerIndex_(headers, expected) {
  const wanted = normalisedHeader_(expected);
  for (let index = 0; index < headers.length; index += 1) {
    if (normalisedHeader_(headers[index]) === wanted) return index;
  }
  return -1;
}

function publicOperationalColumnMap_(headers, tracking) {
  const fields = ['market', 'side', 'odd', 'stake', 'result', 'profit'];
  const mapped = {};
  fields.forEach(field => {
    const index = tracking[field];
    mapped[field] = index >= 0 && index < headers.length ? index + 1 : null;
  });
  return mapped;
}

function marketName_(row, tracking) {
  const market = row[tracking.market];
  return market === 'Vencedor' ? 'Moneyline' : String(market);
}

function sideName_(row, tracking) {
  return String(row[tracking.side] || 'Sem perfil');
}

function isChallengerManualRow_(row, tracking) {
  const explicit = tracking.strategy >= 0 && String(row[tracking.strategy] || '').trim() === PAPER_22BET_SYNC.challengerManualStrategy;
  const selectedLevel = tracking.level >= 0 && isChallengerLevel_(row[tracking.level]);
  return explicit || selectedLevel;
}

function validateManualChallengerSelection_(row, tracking) {
  if (!String(row[tracking.snapshot] || '').trim()) return 'MISSING_SNAPSHOT_KEY';
  const selectedAt = new Date(row[tracking.selectedAt]);
  if (!row[tracking.selectedAt] || Number.isNaN(selectedAt.getTime())) return 'MISSING_SELECTION_TIMESTAMP';
  if (Number(row[tracking.stake]) !== PAPER_22BET_SYNC.challengerManualStakeUnits) return 'INVALID_CHALLENGER_STAKE';
  const edge = Number(row[tracking.challengerEdge]);
  if (!Number.isFinite(edge) || edge < PAPER_22BET_SYNC.challengerManualMinimumEdgePct) return 'INVALID_CHALLENGER_EDGE';
  return 'MANUAL_CHALLENGER_RECORDED';
}

function challengerIndexBand_(row, tracking) {
  const index = Number(row[tracking.challengerIndex]);
  if (!Number.isFinite(index)) return 'N/D';
  if (index >= 90) return '90–100';
  if (index >= 80) return '80–89';
  if (index >= 70) return '70–79';
  return '<70';
}

function challengerCoverageBand_(row, tracking) {
  const raw = Number(row[tracking.challengerCoverage]);
  const coverage = raw > 1 ? raw / 100 : raw;
  if (!Number.isFinite(coverage)) return 'N/D';
  if (coverage >= 0.65) return '65%+';
  if (coverage >= 0.50) return '50–64,9%';
  return '<50%';
}

function challengerEdgeBand_(row, tracking) {
  const edge = Number(row[tracking.challengerEdge]);
  if (!Number.isFinite(edge)) return 'N/D';
  if (edge >= 5) return '5%+';
  if (edge >= 4) return '4–4,9%';
  if (edge >= 3) return '3–3,9%';
  if (edge >= 2) return '2–2,9%';
  return '<2%';
}

function manualLegType_(row, tracking) {
  const market = String(marketName_(row, tracking) || '').trim().toLowerCase();
  const odd = Number(row[tracking.odd]);
  if (!Number.isFinite(odd) || odd <= 1) return 'UNAVAILABLE';
  if (market === 'moneyline') return 'MONEYLINE';
  const line = Number(row[tracking.handicapLine]);
  if (market.indexOf('handicap') >= 0 && market.indexOf('game') >= 0 && Number.isFinite(line) && line > 0) {
    return 'POSITIVE_HANDICAP_GAMES';
  }
  return 'UNAVAILABLE';
}

function auditSelectionSide_(row, tracking, snapshot) {
  if (!snapshot) return null;
  const raw = tracking.selection >= 0 ? row[tracking.selection] : '';
  const selection = normalisedHeader_(raw)
    .replace(/[+\-−]\s*\d+(?:[.,]\d+)?/g, ' ')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const playerA = normalisedHeader_(snapshot.a).replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  const playerB = normalisedHeader_(snapshot.b).replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  const matchesA = auditPlayerNameMatches_(selection, playerA);
  const matchesB = auditPlayerNameMatches_(selection, playerB);
  if (matchesA === matchesB) return null;
  return matchesA ? 'a' : 'b';
}

/**
 * A folha manual usa frequentemente apenas o apelido ("Medvedev -4"), um
 * apelido composto ("De Minaur") ou inicial + apelido ("M. Damm"). O índice
 * factual conserva o nome completo. Aceitamos essas formas apenas quando o
 * resultado é inequívoco entre os dois jogadores; auditSelectionSide_ mantém
 * o fail-closed se ambos ou nenhum coincidirem.
 */
function auditPlayerNameMatches_(selection, player) {
  if (!selection || !player) return false;
  if (selection === player || selection.indexOf(player + ' ') === 0 || player.indexOf(selection + ' ') === 0) {
    return true;
  }
  const selectedTokens = selection.split(' ').filter(Boolean);
  const playerTokens = player.split(' ').filter(Boolean);
  if (!selectedTokens.length || !playerTokens.length || selectedTokens.length > playerTokens.length) return false;

  const suffix = playerTokens.slice(playerTokens.length - selectedTokens.length);
  if (selectedTokens.every((token, index) => token === suffix[index])) return true;

  if (selectedTokens.length >= 2 && selectedTokens[0].length === 1) {
    const surnameTokens = selectedTokens.slice(1);
    const playerSurname = playerTokens.slice(playerTokens.length - surnameTokens.length);
    return playerTokens[0].indexOf(selectedTokens[0]) === 0 &&
      surnameTokens.every((token, index) => token === playerSurname[index]);
  }
  return false;
}

function auditMarketType_(row, tracking) {
  const market = normalisedHeader_(marketName_(row, tracking));
  if (market === 'moneyline') return 'Moneyline';
  if (market.indexOf('handicap') < 0) return marketName_(row, tracking) || 'N/D';
  let line = Number(row[tracking.handicapLine]);
  if (!Number.isFinite(line) && tracking.selection >= 0) {
    const match = String(row[tracking.selection] || '').match(/([+\-−])\s*(\d+(?:[.,]\d+)?)/);
    if (match) line = Number(match[2].replace(',', '.')) * (match[1] === '+' ? 1 : -1);
  }
  if (!Number.isFinite(line)) return 'Handicap · linha N/D';
  if (line > 0) return 'Handicap positivo';
  if (line < 0) return 'Handicap negativo';
  return 'Handicap zero';
}

function auditOddsBand_(rawOdd) {
  const odd = Number(rawOdd);
  if (!Number.isFinite(odd) || odd <= 1) return 'N/D';
  if (odd < 1.70) return '<1,70';
  if (odd < 1.90) return '1,70–1,89';
  if (odd < 2.10) return '1,90–2,09';
  if (odd <= 2.30) return '2,10–2,30';
  if (odd <= 2.50) return '2,31–2,50';
  return '>2,50';
}

function auditIndexBand_(rawIndex) {
  const value = Number(rawIndex);
  if (!Number.isFinite(value)) return 'N/D';
  if (value >= 90) return '90–100';
  if (value >= 80) return '80–89';
  if (value >= 70) return '70–79';
  if (value >= 60) return '60–69';
  if (value >= 50) return '50–59';
  return '<50';
}

function addAuditStats_(collection, key, row, tracking) {
  const label = String(key || 'N/D');
  if (!collection[label]) collection[label] = newStats_();
  addRowToAuditStats_(collection[label], row, tracking);
}

function addRowToAuditStats_(stats, row, tracking) {
  addRowToStats_(stats, row, tracking);
  const result = String(row[tracking.result] || '').trim().toUpperCase();
  const odd = Number(row[tracking.odd]);
  if ((result === 'GANHOU' || result === 'PERDEU') && Number.isFinite(odd) && odd > 1) {
    if (!stats.resolvedOdds) stats.resolvedOdds = [];
    stats.resolvedOdds.push(odd);
  }
}

function finishAuditStats_(stats) {
  const result = finishStats_(stats);
  result.average_odd = stats.resolvedOdds && stats.resolvedOdds.length
    ? Math.round(1000 * stats.resolvedOdds.reduce((total, odd) => total + odd, 0) / stats.resolvedOdds.length) / 1000
    : null;
  return result;
}

function addGuerraAuditRow_(factorGroups, segmentGroups, quality, seenLegs, row, tracking, status, snapshot, candidateKey) {
  quality.linked_entries += 1;
  const canonical = !!String(row[tracking.snapshot] || '').trim();
  quality[canonical ? 'canonical_entries' : 'legacy_entries'] += 1;
  const retrospective = String(status).indexOf('RETROSPECTIVE') >= 0;
  quality[retrospective ? 'retrospective_entries' : 'exact_timestamp_entries'] += 1;

  const marketType = auditMarketType_(row, tracking);
  const legKey = [candidateKey, marketType, normalisedHeader_(row[tracking.selection]), row[tracking.handicapLine]].join('|');
  if (seenLegs[legKey]) quality.duplicate_exact_legs += 1;
  seenLegs[legKey] = true;

  const tour = snapshot && snapshot.t || (tracking.tour >= 0 ? row[tracking.tour] : '') || 'N/D';
  const surface = snapshot && snapshot.s || (tracking.surface >= 0 ? row[tracking.surface] : '') || 'N/D';
  const selectedSide = auditSelectionSide_(row, tracking, snapshot);
  const selectedIndex = snapshot && selectedSide ? snapshot[selectedSide === 'a' ? 'ia' : 'ib'] : null;
  const alignment = snapshot && selectedSide && snapshot.m
    ? (snapshot.m === selectedSide ? 'Alinhado com Fenzobot' : 'Divergente do Fenzobot')
    : 'N/D';
  const dimensions = {
    'Circuito': String(tour || 'N/D').toUpperCase(),
    'Mercado': marketType,
    'Perfil': sideName_(row, tracking),
    'Faixa de odd': auditOddsBand_(row[tracking.odd]),
    'Janela operacional': Number(row[tracking.odd]) >= 1.70 && Number(row[tracking.odd]) <= 2.50
      ? 'Dentro 1,70–2,50' : 'Fora 1,70–2,50',
    'Piso': surface,
    'Índice Fenzobot': auditIndexBand_(selectedIndex),
    'Alinhamento': alignment,
    'Tipo de ligação': retrospective ? 'Retrospetiva' : 'Ex ante',
  };
  Object.keys(dimensions).forEach(dimension => {
    if (!segmentGroups[dimension]) segmentGroups[dimension] = {};
    addAuditStats_(segmentGroups[dimension], dimensions[dimension], row, tracking);
  });

  if (!snapshot) {
    if (canonical) quality.factor_index_missing += 1;
    return;
  }
  quality.factor_index_matches += 1;
  if (!selectedSide) {
    quality.selected_side_unresolved += 1;
    return;
  }
  quality.factor_audit_eligible_entries += 1;
  (snapshot.f || []).forEach(factor => {
    const factorName = String(factor[0] || '').trim();
    const direction = String(factor[1] || '').trim().toLowerCase();
    const weight = Number(factor[2]);
    if (!factorName || ['a', 'b'].indexOf(direction) < 0 || !Number.isFinite(weight) || weight <= 0) return;
    const relation = direction === selectedSide ? 'Alinha com seleção' : 'Contraria seleção';
    ['GLOBAL', String(tour || 'N/D').toUpperCase()].forEach(scope => {
      const key = [scope, factorName, relation].join('|');
      if (!factorGroups[key]) {
        factorGroups[key] = {scope: scope, factor: factorName, relation: relation, stats: newStats_(), weightSum: 0};
      }
      addRowToAuditStats_(factorGroups[key].stats, row, tracking);
      factorGroups[key].weightSum += weight;
    });
  });
}

function auditSampleStatus_(settled) {
  if (settled >= 40) return 'Candidato a revisão de peso';
  if (settled >= 20) return 'Tendência';
  return 'Informativo';
}

function finishGuerraFactorAudit_(groups) {
  return Object.keys(groups).sort().map(key => {
    const item = groups[key];
    const stats = finishAuditStats_(item.stats);
    const breakEven = stats.average_odd ? Math.round(1000 / stats.average_odd) / 10 : null;
    return Object.assign({
      scope: item.scope,
      factor: item.factor,
      relation: item.relation,
      average_effective_weight: item.stats.total_entries
        ? Math.round(1000 * item.weightSum / item.stats.total_entries) / 1000 : null,
      break_even_pct: breakEven,
      hit_vs_break_even_pp: stats.win_rate_pct == null || breakEven == null
        ? null : Math.round(10 * (stats.win_rate_pct - breakEven)) / 10,
      sample_status: auditSampleStatus_(stats.settled),
    }, stats);
  });
}

function finishGuerraSegmentAudit_(dimensions) {
  const rows = [];
  Object.keys(dimensions).sort().forEach(dimension => {
    Object.keys(dimensions[dimension]).sort().forEach(group => {
      const stats = finishAuditStats_(dimensions[dimension][group]);
      const breakEven = stats.average_odd ? Math.round(1000 / stats.average_odd) / 10 : null;
      rows.push(Object.assign({
        dimension: dimension,
        group: group,
        break_even_pct: breakEven,
        hit_vs_break_even_pp: stats.win_rate_pct == null || breakEven == null
          ? null : Math.round(10 * (stats.win_rate_pct - breakEven)) / 10,
        sample_status: auditSampleStatus_(stats.settled),
      }, stats));
    });
  });
  return rows;
}

function auditBucket_() {
  return {values: []};
}

function auditDistribution_(bucket) {
  const values = (bucket && bucket.values || []).slice().sort((a, b) => a - b);
  const count = values.length;
  const median = count
    ? (count % 2 ? values[(count - 1) / 2] : (values[count / 2 - 1] + values[count / 2]) / 2)
    : null;
  const round = value => value == null ? null : Math.round(value * 10000) / 10000;
  return {
    sample_size: count,
    average_pct: count ? round(values.reduce((sum, value) => sum + value, 0) / count) : null,
    median_pct: round(median),
    positive_pct: count ? Math.round(10000 * values.filter(value => value > 0).length / count) / 100 : null,
    minimum_pct: count ? round(values[0]) : null,
    maximum_pct: count ? round(values[count - 1]) : null,
  };
}

function newExecutedEdgeAudit_() {
  return {
    all: auditBucket_(), exact: auditBucket_(), retrospective: auditBucket_(),
    byHouse: {}, unavailable: {
      NON_MONEYLINE_OR_LINE_INCOMPATIBLE: 0,
      SELECTION_SIDE_UNRESOLVED: 0,
      FROZEN_PROBABILITY_UNAVAILABLE: 0,
      EXECUTED_ODD_UNAVAILABLE: 0,
    },
  };
}

function newReferenceMovementAudit_() {
  return {
    all: auditBucket_(), exact: auditBucket_(), retrospective: auditBucket_(),
    unavailable: {
      SELECTION_SIDE_UNRESOLVED: 0,
      REFERENCE_ENTRY_OR_CLOSING_UNAVAILABLE: 0,
    },
  };
}

function effectiveExecutedOdd_(row, tracking) {
  const rawOdd = Number(row[tracking.odd]);
  if (!Number.isFinite(rawOdd) || rawOdd <= 1) return null;
  const house = tracking.house >= 0 ? String(row[tracking.house] || '').trim() : '';
  const effective = normalisedHeader_(house).indexOf('betfair') >= 0
    ? 1 + (rawOdd - 1) * 0.95
    : rawOdd;
  return {house: house || 'N/D', raw_odd: rawOdd, effective_odd: effective};
}

function snapshotProbabilityForSide_(snapshot, field, side) {
  const values = snapshot && snapshot[field];
  const index = side === 'a' ? 0 : side === 'b' ? 1 : -1;
  const probability = index >= 0 && Array.isArray(values) ? Number(values[index]) : NaN;
  return Number.isFinite(probability) && probability > 0 && probability < 1
    ? probability : null;
}

function addAuditValue_(audit, value, status) {
  audit.all.values.push(value);
  (status === 'LINKED_EX_ANTE' ? audit.exact : audit.retrospective).values.push(value);
}

function addGuerraExecutionAudit_(edgeAudit, movementAudit, row, tracking, status, snapshot) {
  const selectedSide = auditSelectionSide_(row, tracking, snapshot);
  if (!selectedSide) {
    edgeAudit.unavailable.SELECTION_SIDE_UNRESOLVED += 1;
    movementAudit.unavailable.SELECTION_SIDE_UNRESOLVED += 1;
    return;
  }

  if (auditMarketType_(row, tracking) !== 'Moneyline') {
    edgeAudit.unavailable.NON_MONEYLINE_OR_LINE_INCOMPATIBLE += 1;
  } else {
    const probability = snapshotProbabilityForSide_(snapshot, 'p', selectedSide);
    const executed = effectiveExecutedOdd_(row, tracking);
    if (probability == null) {
      edgeAudit.unavailable.FROZEN_PROBABILITY_UNAVAILABLE += 1;
    } else if (!executed) {
      edgeAudit.unavailable.EXECUTED_ODD_UNAVAILABLE += 1;
    } else {
      const edgePct = 100 * (probability * executed.effective_odd - 1);
      addAuditValue_(edgeAudit, edgePct, status);
      if (!edgeAudit.byHouse[executed.house]) edgeAudit.byHouse[executed.house] = auditBucket_();
      edgeAudit.byHouse[executed.house].values.push(edgePct);
    }
  }

  const entry = snapshotProbabilityForSide_(snapshot, 'me', selectedSide);
  const closing = snapshotProbabilityForSide_(snapshot, 'mc', selectedSide);
  if (entry == null || closing == null) {
    movementAudit.unavailable.REFERENCE_ENTRY_OR_CLOSING_UNAVAILABLE += 1;
    return;
  }
  addAuditValue_(movementAudit, 100 * (closing - entry), status);
}

function finishExecutedEdgeAudit_(audit) {
  const byHouse = {};
  Object.keys(audit.byHouse).sort().forEach(house => {
    byHouse[house] = auditDistribution_(audit.byHouse[house]);
  });
  return {
    status: audit.all.values.length ? 'AVAILABLE' : 'UNAVAILABLE',
    claims: 'DESCRIPTIVE_ONLY_FROZEN_FENZOBOT_PROBABILITY_X_EXECUTED_ODD',
    formula: '100 * (frozen_fenzobot_probability * effective_executed_odd - 1)',
    commission_policy: 'BETFAIR_5_PERCENT_ON_NET_WINNINGS_OTHER_BOOKMAKERS_RAW_ODD',
    market_scope: 'MONEYLINE_ONLY_HANDICAP_REQUIRES_EXACT_LINE_PROBABILITY',
    all_linked: auditDistribution_(audit.all),
    exact_timestamp: auditDistribution_(audit.exact),
    retrospective_date_only: auditDistribution_(audit.retrospective),
    by_house: byHouse,
    unavailable: audit.unavailable,
  };
}

function finishReferenceMovementAudit_(audit) {
  return {
    status: audit.all.values.length ? 'AVAILABLE' : 'UNAVAILABLE',
    label: 'MOVIMENTO_DO_MERCADO_DE_REFERENCIA_NAO_CLV_DA_APOSTA',
    comparison_contract: 'SAME_LEDGER_PROVIDER_ENDPOINT_BOOKMAKER_AND_EVENT_NOT_EXECUTION_BOOK',
    direction: 'POSITIVE_MEANS_SELECTED_SIDE_SHORTENED',
    all_linked: auditDistribution_(audit.all),
    exact_timestamp: auditDistribution_(audit.exact),
    retrospective_date_only: auditDistribution_(audit.retrospective),
    unavailable: audit.unavailable,
  };
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
  const key = String(row[tracking.snapshot] || '').trim();
  const supportsReportLinkage = Number.isInteger(tracking.reportMatchKey) && tracking.reportMatchKey >= 0;
  if (!supportsReportLinkage) {
    if (indexAvailable === false) return 'UNAVAILABLE';
    if (!key || !Object.prototype.hasOwnProperty.call(byKey, key)) return 'SNAPSHOT_NOT_FOUND';
    const legacyCohort = byKey[key];
    if (!legacyCohort.eligible) return 'NOT_GREEN_STRONG';
    const legacySelectedAt = new Date(row[tracking.selectedAt]);
    if (!row[tracking.selectedAt] || Number.isNaN(legacySelectedAt.getTime())) return 'MISSING_SELECTION_TIMESTAMP';
    const legacyStart = new Date(legacyCohort.commence_time_utc);
    if (Number.isNaN(legacyStart.getTime())) return 'UNAVAILABLE';
    return legacySelectedAt.getTime() < legacyStart.getTime() ? 'LINKED_EX_ANTE' : 'SELECTION_AFTER_START';
  }
  const reportMatchKey = String(row[tracking.reportMatchKey] || '').trim();
  if (!reportMatchKey) return 'REPORT_LINK_NOT_FOUND';
  const precision = String(row[tracking.timePrecision] || '').trim();
  if (precision === 'DATE_ONLY_RETROSPECTIVE') {
    return key ? 'LINKED_RETROSPECTIVE_CANONICAL' : 'LINKED_RETROSPECTIVE_LEGACY';
  }
  const selectedAt = new Date(row[tracking.selectedAt]);
  if (!row[tracking.selectedAt] || Number.isNaN(selectedAt.getTime())) return 'MISSING_SELECTION_TIMESTAMP';
  const cohort = (byKey || {})[key] || {};
  const linkedCommenceTime = Number.isInteger(tracking.commenceTime)
    ? row[tracking.commenceTime]
    : null;
  const start = new Date(linkedCommenceTime || cohort.commence_time_utc);
  if (Number.isNaN(start.getTime())) return 'UNAVAILABLE';
  return selectedAt.getTime() < start.getTime() ? 'LINKED_EX_ANTE' : 'SELECTION_AFTER_START';
}

function isLinkedGuerraStatus_(status) {
  return [
    'LINKED_EX_ANTE',
    'LINKED_RETROSPECTIVE_CANONICAL',
    'LINKED_RETROSPECTIVE_LEGACY',
  ].indexOf(status) >= 0;
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
    const document = JSON.parse(
      Utilities.newBlob(
        Utilities.base64Decode(String(body.content || '').replace(/\s/g, '')),
      ).getDataAsString(),
    );
    const rows = document.prospective_classifications || [];
    const byKey = {};
    rows.forEach(row => { if (row.snapshot_key) byKey[String(row.snapshot_key)] = row; });
    return {byKey: byKey, eligibleCount: rows.filter(row => row.eligible === true).length, available: true};
  } catch (error) {
    return {byKey: {}, eligibleCount: null, available: false};
  }
}

function fetchManualFactorIndex_(token, repository, branch) {
  if (!token || !repository || typeof UrlFetchApp === 'undefined') {
    return {byKey: {}, recordCount: null, available: false};
  }
  const url = 'https://api.github.com/repos/' + repository + '/contents/' + PAPER_22BET_SYNC.factorIndexPath + '?ref=' + encodeURIComponent(branch);
  const response = UrlFetchApp.fetch(url, {
    method: 'get',
    headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json'},
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) return {byKey: {}, recordCount: null, available: false};
  try {
    const body = JSON.parse(response.getContentText());
    const document = JSON.parse(
      Utilities.newBlob(
        Utilities.base64Decode(String(body.content || '').replace(/\s/g, '')),
      ).getDataAsString(),
    );
    return {
      byKey: document.records || {},
      recordCount: Number(document.record_count || 0),
      available: document.privacy_contract === 'PUBLIC_REPORT_FACTS_ONLY_NO_MANUAL_SELECTIONS',
    };
  } catch (error) {
    return {byKey: {}, recordCount: null, available: false};
  }
}

function newStats_() {
  return {total_entries: 0, settled: 0, pending: 0, wins: 0, losses: 0, pushes: 0, units: 0, stake: 0, pendingStake: 0, odds: []};
}

function addRowToStats_(stats, row, tracking) {
  const indexes = tracking || PAPER_22BET_SYNC.legacyOperationalIndexes;
  stats.total_entries += 1;
  const result = String(row[indexes.result] || '').trim().toUpperCase();
  const odd = Number(row[indexes.odd]);
  const stake = Number(row[indexes.stake]);
  const profit = Number(row[indexes.profit]);
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
    if (Number.isFinite(stake)) stats.pendingStake += stake;
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
    settled_stake_units: round(stats.stake),
    pending_stake_units: round(stats.pendingStake),
    roi_pct: stats.stake ? round(100 * stats.units / stats.stake) : null,
    average_odd: stats.odds.length ? round(stats.odds.reduce((total, odd) => total + odd, 0) / stats.odds.length) : null,
  };
}

function finishCollection_(collection) {
  const result = {};
  Object.keys(collection).forEach(key => result[key] = finishStats_(collection[key]));
  return result;
}

function newFlatStakeSimulation_() {
  return {
    includedResolvedEntries: 0,
    pendingEntries: 0,
    voidEntries: 0,
    excludedEntries: 0,
    netProfitEur: 0,
    exclusionReasons: {},
  };
}

function excludeFlatStakeEntry_(simulation, reason) {
  simulation.excludedEntries += 1;
  simulation.exclusionReasons[reason] = (simulation.exclusionReasons[reason] || 0) + 1;
}

function addRowToFlatStakeSimulation_(simulation, row, tracking) {
  const indexes = tracking || PAPER_22BET_SYNC.legacyOperationalIndexes;
  const stake = 10;
  const odd = Number(row[indexes.odd]);
  const result = String(row[indexes.result] || '').trim().toUpperCase();
  if (!Number.isFinite(odd) || odd <= 1) {
    excludeFlatStakeEntry_(simulation, 'INVALID_DECIMAL_ODD');
    return;
  }
  if (result === '' || result === 'PENDENTE' || result === 'PENDING') {
    simulation.pendingEntries += 1;
    return;
  }
  if (result !== 'GANHOU' && result !== 'PERDEU' && result !== 'VOID') {
    excludeFlatStakeEntry_(simulation, 'UNRECOGNIZED_RESULT');
    return;
  }
  simulation.includedResolvedEntries += 1;
  if (result === 'VOID') {
    simulation.voidEntries += 1;
    return;
  }
  simulation.netProfitEur += result === 'GANHOU' ? stake * (odd - 1) : -stake;
}

function finishFlatStakeSimulation_(simulation, sourceAvailable) {
  const round = value => Math.round(value * 100) / 100;
  const validEntries = simulation.includedResolvedEntries + simulation.pendingEntries;
  const observedEntries = validEntries + simulation.excludedEntries;
  const resolvedStake = 10 * simulation.includedResolvedEntries;
  let status = 'AVAILABLE';
  if (!sourceAvailable || observedEntries === 0) status = 'UNAVAILABLE';
  else if (simulation.excludedEntries > 0) status = 'DEGRADED';
  return {
    status: status,
    stake_per_entry_eur: 10.0,
    included_resolved_entries: simulation.includedResolvedEntries,
    pending_entries: simulation.pendingEntries,
    void_entries: simulation.voidEntries,
    excluded_entries: simulation.excludedEntries,
    resolved_stake_eur: resolvedStake,
    pending_exposure_eur: 10 * simulation.pendingEntries,
    net_profit_eur: simulation.includedResolvedEntries ? round(simulation.netProfitEur) : null,
    roi_pct: resolvedStake ? round(100 * simulation.netProfitEur / resolvedStake) : null,
    exclusion_reasons: simulation.exclusionReasons,
  };
}

function refreshChallengerPaperDashboard_(spreadsheet, aggregate) {
  if (!spreadsheet || typeof spreadsheet.insertSheet !== 'function') return;
  const name = PAPER_22BET_SYNC.challengerDashboardSheetName;
  const sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);
  if (sheet.getMaxRows() < 58) sheet.insertRowsAfter(sheet.getMaxRows(), 58 - sheet.getMaxRows());
  if (sheet.getMaxColumns() < 21) sheet.insertColumnsAfter(sheet.getMaxColumns(), 21 - sheet.getMaxColumns());
  sheet.getCharts().forEach(chart => sheet.removeChart(chart));
  sheet.getDataRange().breakApart();
  sheet.clear();
  sheet.showColumns(1, sheet.getMaxColumns());
  sheet.setConditionalFormatRules([]);
  sheet.setFrozenRows(3);
  sheet.setTabColor('#7C3AED');

  const summary = aggregate.summary || {};
  sheet.getRange('A1:L1').merge().setValue('CHALLENGER — PAPER EXPERIMENTAL 0,5u');
  sheet.getRange('A2:L2').merge().setValue(
    'Universo autónomo · edge mínimo 2% · não entra nos totais ATP/WTA principais',
  );
  sheet.getRange('A4:L6').setValues([
    ['Entradas', summary.total_entries || 0, 'Liquidadas', summary.settled || 0, 'Pendentes', summary.pending || 0, 'W–L', (summary.wins || 0) + '–' + (summary.losses || 0), 'Stake', '0,5u', 'Estado', aggregate.status || 'UNAVAILABLE'],
    ['Win rate', formatDashboardPct_(summary.win_rate_pct), 'ROI', formatDashboardPct_(summary.roi_pct), 'Resultado', formatDashboardUnits_(summary.units), 'Odd média', summary.average_odd == null ? 'N/D' : summary.average_odd, 'Exposição aberta', formatDashboardUnits_(summary.pending_stake_units), 'Mín. edge', '2,0%'],
    ['Regra', 'Índice ≥70', 'Forma', '10 jogos/jogador', 'Cobertura', '≥50%', 'Registo', 'Snapshot + UTC', 'Estratégia', PAPER_22BET_SYNC.challengerManualStrategy, 'Totais gerais', 'EXCLUÍDO'],
  ]);
  sheet.getRange('A1:L1').setBackground('#162B52').setFontColor('#FFFFFF').setFontSize(16).setFontWeight('bold').setHorizontalAlignment('left');
  sheet.getRange('A2:L2').setBackground('#EDE9FE').setFontColor('#4C1D95').setFontStyle('italic');
  sheet.getRange('A4:L6').setBackground('#F8FAFC').setBorder(true, true, true, true, true, true, '#CBD5E1', SpreadsheetApp.BorderStyle.SOLID);
  [1, 3, 5, 7, 9, 11].forEach(column => sheet.getRange(4, column, 3, 1).setFontWeight('bold').setFontColor('#475569'));
  [2, 4, 6, 8, 10, 12].forEach(column => sheet.getRange(4, column, 3, 1).setFontWeight('bold').setFontColor('#0F172A'));
  sheet.setColumnWidths(1, 12, 115);
  sheet.setRowHeight(1, 34);
  sheet.setRowHeight(2, 28);

  // Os gráficos não podem depender de colunas ocultas: o Google Sheets pode
  // ignorá-las apesar da estratégia SHOW_BOTH. Mantemos as tabelas-fonte numa
  // zona técnica visível, muito abaixo do painel, para os gráficos continuarem
  // preenchidos e atualizáveis em todas as execuções.
  let supportRow = 200;
  const charts = [
    {title: 'Performance por mercado', collection: aggregate.by_market || {}, row: 8, column: 1},
    {title: 'Performance por favorito / underdog', collection: aggregate.by_side || {}, row: 8, column: 7},
    {title: 'Performance por faixa de edge', collection: aggregate.by_edge_band || {}, row: 24, column: 1},
    {title: 'Performance por índice Fenzobot', collection: aggregate.by_fenzobot_index_band || {}, row: 24, column: 7},
    {title: 'Performance por cobertura factual', collection: aggregate.by_coverage_band || {}, row: 40, column: 1, width: 1100},
  ];
  charts.forEach(spec => {
    const table = challengerChartRows_(spec.collection);
    if (table.length <= 1) {
      sheet.getRange(spec.row, spec.column, 1, 5).merge().setValue(spec.title + ' · sem amostra liquidada')
        .setBackground('#F1F5F9').setFontColor('#64748B').setFontStyle('italic');
      return;
    }
    const range = sheet.getRange(supportRow, 1, table.length, 3);
    range.setValues(table);
    range.setFontSize(9).setFontColor('#64748B');
    range.offset(0, 0, 1, 3)
      .setBackground('#E2E8F0')
      .setFontColor('#0F172A')
      .setFontWeight('bold');
    addChallengerPerformanceChart_(sheet, range, spec.title, spec.row, spec.column, spec.width || 540);
    supportRow += table.length + 2;
  });
  sheet.getRange(198, 1, 1, 3).merge()
    .setValue('DADOS TÉCNICOS DOS GRÁFICOS · atualização automática')
    .setBackground('#0F172A')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold');
}

function formatDashboardPct_(value) {
  return value == null ? 'N/D' : Number(value).toFixed(1).replace('.', ',') + '%';
}

function formatDashboardUnits_(value) {
  return value == null ? 'N/D' : (Number(value) >= 0 ? '+' : '') + Number(value).toFixed(2).replace('.', ',') + 'u';
}

function challengerChartRows_(collection) {
  const rows = [['Segmento', 'Win rate %', 'ROI %']];
  Object.keys(collection || {}).sort().forEach(label => {
    const stats = collection[label] || {};
    if (!stats.settled) return;
    rows.push([
      label + ' · n=' + stats.settled,
      stats.win_rate_pct == null ? null : Number(stats.win_rate_pct),
      stats.roi_pct == null ? null : Number(stats.roi_pct),
    ]);
  });
  return rows;
}

function addChallengerPerformanceChart_(sheet, range, title, row, column, width) {
  const chart = sheet.newChart()
    .asComboChart()
    .addRange(range)
    .setNumHeaders(1)
    .setHiddenDimensionStrategy(Charts.ChartHiddenDimensionStrategy.SHOW_BOTH)
    .setPosition(row, column, 0, 0)
    .setOption('title', title)
    .setOption('titleTextStyle', {color: '#0F172A', fontSize: 16, bold: true})
    .setOption('fontName', 'Arial')
    .setOption('legend', {position: 'bottom', alignment: 'center', textStyle: {color: '#475569', fontSize: 11}})
    .setOption('seriesType', 'bars')
    .setOption('series', {
      0: {type: 'bars', targetAxisIndex: 0, color: '#2563EB', dataLabel: 'value'},
      1: {type: 'line', targetAxisIndex: 1, color: '#0F766E', lineWidth: 3, pointSize: 7, dataLabel: 'value'},
    })
    .setOption('backgroundColor', '#FFFFFF')
    .setOption('chartArea', {left: 72, top: 58, width: '72%', height: '58%'})
    .setOption('vAxes', {
      0: {title: 'Acerto (%)', format: '0.0', viewWindow: {min: 0, max: 100}, gridlines: {color: '#E2E8F0'}, textStyle: {color: '#475569'}},
      1: {title: 'ROI (%)', format: '0.0', gridlines: {color: 'transparent'}, textStyle: {color: '#0F766E'}},
    })
    .setOption('hAxis', {slantedText: true, slantedTextAngle: 25, textStyle: {fontSize: 10, color: '#334155'}})
    .setOption('bar', {groupWidth: '55%'})
    .setOption('width', width)
    .setOption('height', 310)
    .build();
  sheet.insertChart(chart);
}
