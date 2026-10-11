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
  trackingHeaders: [
    'Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC',
    '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status',
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
  syncContractVersion: 4,
  // Índices legacy (A:O) usados exclusivamente como compatibilidade para
  // versões antigas da Sheet sem cabeçalhos reconhecíveis.
  legacyOperationalIndexes: {
    market: 5, side: 7, odd: 9, stake: 10, result: 12, profit: 13,
  },
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Fenzobot')
    .addItem('Sincronizar métricas PAPER 22Bet', 'syncPaperTradingToGitHub')
    .addItem('Instalar colunas GREEN_STRONG_V1', 'installGreenStrongTrackingColumns')
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
    sheet.getRange(firstDataRow, 15, populatedRows, 1).setFormulaR1C1(challengerProfitFormulaR1C1_());
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

function challengerProfitFormulaR1C1_() {
  return '=IF(RC[-1]="GANHOU",RC[-3]*(RC[-4]-1)*IF(RC[-5]="Betfair",0.95,1),IF(RC[-1]="PERDEU",-RC[-3],IF(RC[-1]="VOID",0,"")))';
}

function normalisedTrackingColumn_(map, expected) {
  const wanted = normalisedHeader_(expected);
  const keys = Object.keys(map || {});
  for (let index = 0; index < keys.length; index += 1) {
    if (normalisedHeader_(keys[index]) === wanted) return map[keys[index]];
  }
  return null;
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
  if (e.range.getRow() <= PAPER_22BET_SYNC.headerRow || !e.value) return;
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
  if (map['Fenzobot Snapshot Key'] !== e.range.getColumn()) return;
  const stampColumn = map['Selected At UTC'];
  if (!stampColumn) return;
  const stampCell = sheet.getRange(e.range.getRow(), stampColumn);
  if (!stampCell.getValue()) stampCell.setValue(new Date().toISOString());
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
  if (profitColumn) sheet.getRange(rowNumber, profitColumn).setFormulaR1C1(challengerProfitFormulaR1C1_());
  if (selectedAtColumn) {
    const selectedAt = sheet.getRange(rowNumber, selectedAtColumn);
    if (!selectedAt.getValue()) selectedAt.setValue(new Date().toISOString());
  }
}

function installPaperTradingSync() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'syncPaperTradingToGitHub')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('syncPaperTradingToGitHub').timeBased().everyMinutes(30).create();
  return 'Sincronização automática ativada: verifica a Sheet a cada 30 minutos e só publica se houver alterações.';
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
  const guerraStats = newStats_();
  const guerraByMarket = {};
  const guerraBySide = {};
  const guerraReviewRoutes = {};
  const flatStakeSimulation = newFlatStakeSimulation_();
  const selectedSnapshotKeys = {};
  const underdogPairs = {};
  const linkage = {LINKED_EX_ANTE: 0, SNAPSHOT_NOT_FOUND: 0, NOT_GREEN_STRONG: 0, SELECTION_AFTER_START: 0, MISSING_SELECTION_TIMESTAMP: 0, UNAVAILABLE: 0};
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
    if (status !== 'LINKED_EX_ANTE') return;
    const snapshotKey = String(row[tracking.snapshot]).trim();
    const cohort = green.byKey[snapshotKey] || {};
    selectedSnapshotKeys[snapshotKey] = true;
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
    if (cohort.selected_side_market_position === 'UNDERDOG') {
      if (!underdogPairs[snapshotKey]) underdogPairs[snapshotKey] = {moneyline: false, positiveHandicap: false};
      const leg = manualLegType_(row, tracking);
      if (leg === 'MONEYLINE') underdogPairs[snapshotKey].moneyline = true;
      if (leg === 'POSITIVE_HANDICAP_GAMES') underdogPairs[snapshotKey].positiveHandicap = true;
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
    selection_rate_pct: green.eligibleCount ? Math.round(10000 * selectedCandidates / green.eligibleCount) / 100 : null,
    status: tracking.complete && green.available ? 'AVAILABLE' : 'UNAVAILABLE',
    flat_stake_simulation: finishFlatStakeSimulation_(
      flatStakeSimulation,
      tracking.complete && green.available,
    ),
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
    challengerIndex: headerIndex_(headers, 'Challenger Índice Fenzobot'),
    challengerCoverage: headerIndex_(headers, 'Challenger Cobertura %'),
    challengerEdge: headerIndex_(headers, 'Challenger Edge %'),
    level: operationalIndex_(headers, 'Nível', 'level'),
    market: operationalIndex_(headers, 'Tipo de mercado', 'market'),
    side: operationalIndex_(headers, 'Fav/Und', 'side'),
    odd: operationalIndex_(headers, 'Odd aposta', 'odd'),
    stake: operationalIndex_(headers, 'Stake (u)', 'stake'),
    result: operationalIndex_(headers, 'Resultado', 'result'),
    profit: operationalIndex_(headers, 'Lucro (u)', 'profit'),
    complete: PAPER_22BET_SYNC.trackingHeaders.every(header => indexes[header] >= 0),
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
    level: ['Nível', 'Nivel', 'Circuito'],
    market: ['Tipo de mercado', 'Mercado'],
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

  let supportRow = 1;
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
    const range = sheet.getRange(supportRow, 17, table.length, 3);
    range.setValues(table);
    addChallengerPerformanceChart_(sheet, range, spec.title, spec.row, spec.column, spec.width || 540);
    supportRow += table.length + 2;
  });
  sheet.hideColumns(17, 5);
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
    .asColumnChart()
    .addRange(range)
    .setNumHeaders(1)
    .setPosition(row, column, 0, 0)
    .setOption('title', title)
    .setOption('titleTextStyle', {color: '#0F172A', fontSize: 14, bold: true})
    .setOption('legend', {position: 'bottom', textStyle: {color: '#475569'}})
    .setOption('series', {0: {color: '#2563EB'}, 1: {color: '#7C3AED'}})
    .setOption('backgroundColor', '#FFFFFF')
    .setOption('chartArea', {left: 65, top: 50, width: '76%', height: '62%'})
    .setOption('vAxis', {title: 'Percentagem', format: '0.0', gridlines: {color: '#E2E8F0'}})
    .setOption('hAxis', {slantedText: true, slantedTextAngle: 25, textStyle: {fontSize: 10}})
    .setOption('width', width)
    .setOption('height', 285)
    .build();
  sheet.insertChart(chart);
}
