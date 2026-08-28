# Sharp Signals — Constituição do Projeto
**Versão:** v1.0 — 28/08/2026  
**Estado:** RATIFICADA / CANÓNICA  
**Finalidade:** princípios fundamentais e regras de funcionamento do Sharp Signals.

> Esta versão foi aprovada pelos dois co-desenvolvedores e constitui a Constituição canónica do projeto a partir de 28/08/2026.

## Preâmbulo
O Sharp Signals é um projeto conjunto de inteligência aplicada ao ténis, desenvolvido de forma experimental, orientada por dados e assistida por inteligência artificial. Esta Constituição existe para preservar coerência, integridade e aprendizagem cumulativa sem reduzir a autonomia dos dois co-desenvolvedores nem tornar o projeto burocrático.
A presente versão foi ratificada pelos dois co-desenvolvedores e é canónica. Alterações futuras devem seguir o processo definido no Artigo 22.

> **Espírito do projeto:** rigor sem rigidez; autonomia com rastreabilidade; experimentação com memória; e um objetivo explícito de construir algo útil sem deixar de ser divertido fazê-lo.

## Artigo 1 — Identidade e finalidade do projeto

**1.1 Sharp Signals** — O Sharp Signals é uma plataforma, knowledge base e sistema de análise aplicada ao ténis. Não se confunde com uma única fórmula, relatório, modelo, interface ou agente de IA.

**1.2 Objetivo** — O objetivo principal é construir, aprender e experimentar em conjunto. O projeto deve ser intelectualmente estimulante e divertido para os dois co-desenvolvedores. Se evoluir para uma ferramenta interna robusta e útil, isso constitui sucesso. Se, adicionalmente, surgir uma aplicação comercial com boa relação retorno/risco e viabilidade plausível, essa oportunidade deve ser considerada.

**1.3 Direção aberta** — O projeto não fica preso a uma arquitetura final pré-definida. O Fenzobot pode permanecer um evidence index, evoluir para um modelo probabilístico ou ser complementado/substituído por outra abordagem, desde que o caminho seja tecnicamente lógico, testável e apresente boa probabilidade de sucesso.

## Artigo 2 — Evidência antes de conclusão

O Sharp Signals deve distinguir permanentemente FACTO, INFERÊNCIA, HIPÓTESE e RESULTADO VALIDADO. Uma hipótese não se transforma em facto porque parece intuitivamente correta, foi sugerida por um LLM, foi implementada em código ou produziu alguns resultados favoráveis. Sempre que possível, uma nova ideia deve gerar uma pergunta testável.

## Artigo 3 — Primazia temporal dos dados

Toda a análise destinada a avaliar capacidade preditiva deve respeitar o princípio ex ante: o sistema só pode ser avaliado com base na informação efetivamente disponível antes do evento. Snapshots pré-jogo devem ser preservados; dados posteriores podem liquidar resultados, mas não reescrever o estado pré-jogo. Temporal leakage é uma falha crítica.

## Artigo 4 — Integridade e suficiência dos dados

O Sharp Signals não inventa dados. Informação inexistente, ambígua ou insuficiente deve permanecer N/D ou equivalente. Missing data não equivale automaticamente a zero; fatores inválidos não influenciam silenciosamente o índice; cobertura e qualidade devem ser visíveis; e um relatório pode ser declarado nulo quando a evidência disponível não permite uma comparação credível.

## Artigo 5 — Universos experimentais

**SHADOW** — Cálculos, features ou modelos ainda em observação e que não devem ser confundidos com decisões operacionais validadas.

**PAPER** — Decisões simuladas, registadas ex ante, sem utilização de capital real.

**REAL** — Execução com capital ou consequências financeiras reais.

SHADOW, PAPER e REAL são universos distintos e nunca devem ser misturados estatisticamente ou apresentados como equivalentes.

## Artigo 6 — Mercado como benchmark

Quando o Sharp Signals produzir inteligência sobre probabilidades, odds ou valor económico, deve ser comparado com um baseline de mercado apropriado. A pergunta relevante não é apenas “o Sharp Signals acerta?”, mas também “o Sharp Signals acrescenta informação que o mercado ainda não contém?”. Accuracy isolada não é evidência suficiente de vantagem económica.

## Artigo 7 — Pricing, fair odds e edge

Pricing, fair odds e edge só podem ser apresentados como validados quando existir evidência fora da amostra suficiente. Enquanto tal não acontecer, devem ser identificados como experimentais e não devem ser transformados em claims de vantagem comprovada. Uma fórmula implementada não é, por si só, um modelo validado.

## Artigo 8 — Avaliação preditiva e económica

O sistema é avaliado simultaneamente pela qualidade preditiva e pelo desempenho económico. Com amostras reduzidas, deve ser atribuído maior peso à robustez estatística, calibração e performance incremental relativamente ao mercado. À medida que a amostra PAPER aumenta, ROI/yield, drawdown, CLV, estabilidade por regime/mercado e outras métricas económicas passam a ter peso crescente. Nenhuma destas dimensões isoladamente é suficiente para justificar execução REAL.

## Artigo 9 — Maturidade e passagem de PAPER para REAL

Não existe uma data fixa ou um único threshold pré-definido para a passagem de PAPER para REAL. O sistema deve acompanhar continuamente a sua maturidade através de métricas preditivas, económicas, de risco, estabilidade e qualidade dos dados, e deve apresentar periodicamente uma avaliação explícita sobre se a evidência acumulada justifica considerar REAL. A decisão final continua a ser humana e deve refletir a evidência disponível no momento.

## Artigo 10 — Aprendizagem cumulativa

Cada jogo analisado deve, sempre que tecnicamente razoável, contribuir para a knowledge base futura. O objetivo não é apenas produzir relatórios individuais, mas construir progressivamente um ativo proprietário composto por dados ex ante, contexto, estado do motor, fatores, odds, decisão, resultado e aprendizagem posterior.

## Artigo 11 — Versionamento e reprodutibilidade

Uma previsão histórica deve poder ser associada à versão que a produziu. Alterações materiais ao motor, pesos, configurações, pricing ou metodologia devem ser identificáveis através de mecanismos como engine_version, model_version, config_hash, CHANGE-ID e commit Git. Versões materialmente diferentes não devem ser avaliadas como se fossem uma estratégia única sem identificação explícita.

## Artigo 12 — Autonomia dos co-desenvolvedores

Os dois co-desenvolvedores possuem autonomia ampla para propor, investigar, testar, implementar, alterar, remover ou substituir qualquer componente do projeto. Nenhuma ação está, por princípio, reservada exclusivamente a um deles.

Qualquer alteração material ou estrutural deve, contudo, ser claramente identificada e registada, permitindo ao outro compreender o que mudou, porquê e quais as consequências esperadas. Autonomia não elimina rastreabilidade.

## Artigo 13 — Níveis de mudança e registo

**LEVEL 1 — Operacional / baixo impacto** — UI, logging, documentação, testes, bugfixes ou refactors sem mudança material de comportamento. Pode ser executado autonomamente e documentado de forma proporcional.

**LEVEL 2 — Comportamento do sistema** — Fatores, pesos, thresholds, tratamento de dados, PAPER logic, edge, reporting decisório e outras alterações de comportamento. Exige registo com CHANGE-ID e Implementation Brief, mas não aprovação do outro co-desenvolvedor.

**LEVEL 3 — Estrutural / constitucional** — Definição do Fenzobot, metodologia probabilística, sistema de pricing, arquitetura central de dados, execução REAL, claims públicos, alterações à Constituição e outras mudanças estruturais. Não exige unanimidade, mas exige registo explícito, destacado e rastreável.

Os níveis existem para determinar o grau de documentação e visibilidade necessário, não para limitar a autonomia individual.

## Artigo 14 — Brain, Codex e execução

O projeto adota a separação: BRAIN pensa e decide; Codex implementa; GitHub regista; testes verificam; Canon preserva. O Codex ou qualquer outro agente de implementação não deve decidir silenciosamente questões de produto ou metodologia fora do scope recebido. Ideias descobertas durante a implementação devem regressar ao BRAIN como propostas separadas.

## Artigo 15 — Inteligência Artificial e divergência

A IA é um instrumento de raciocínio e execução, não uma autoridade soberana. Os agentes podem discordar, desafiar pressupostos, gerar alternativas e encontrar erros. As conclusões devem ser avaliadas pelos argumentos e pela evidência, não pelo fornecedor ou nome do modelo. Para decisões importantes, deve privilegiar-se o ciclo tese → objeção → evidência → teste → decisão.

## Artigo 16 — Eficiência de compute

O projeto deve usar recursos computacionais proporcionalmente à dificuldade e ao risco da tarefa. Tarefas simples devem preferir modelos/compute mais rápidos; tarefas intermédias, compute normal; e arquitetura, lógica central, data integrity, debugging difícil ou alterações críticas devem recorrer a modelos e reasoning mais fortes. Nunca se deve sacrificar qualidade, integridade ou segurança apenas para reduzir compute.

## Artigo 17 — Fontes de verdade

**GitHub main** — Verdade sobre o que está efetivamente implementado.

**Project Canon / Decision Register** — Verdade sobre o que foi formalmente registado e decidido.

**Experiment Ledger** — Verdade sobre o que os testes e experiências realmente demonstraram.

**Constituição** — Princípios fundamentais do projeto.

**BRAIN / chats** — Espaço exploratório; não constitui, sozinho, decisão canónica.

Uma divergência entre estas fontes deve ser explicitamente reconciliada e registada.

## Artigo 18 — Desenvolvimento orientado por experiências e anti-overfitting

Sempre que uma alteração importante seja uma hipótese e não uma necessidade técnica evidente, deve preferir-se uma experiência barata e reversível antes de uma alteração estrutural permanente. Uma experiência deve, idealmente, definir hipótese, baseline, métrica, amostra, critério de sucesso e critério de abandono.

O projeto deve proteger-se de overfitting, data snooping, cherry-picking, seleção retrospetiva de thresholds e segmentações criadas apenas depois de conhecer os resultados. O objetivo é capacidade fora da amostra, não um histórico artificialmente perfeito.

## Artigo 19 — Claims, comunicação e exceções de desenvolvimento

O Sharp Signals deve, por princípio, comunicar conclusões com precisão proporcional à evidência disponível e não transformar correlação em causalidade, hipótese em facto, PAPER em performance REAL, edge experimental em vantagem comprovada ou índice em probabilidade sem validação.

Por razões de desenvolvimento, prototipagem, modelação de relatórios, UX ou teste de produto, o sistema pode apresentar outputs que contrariem temporariamente estes princípios formais — por exemplo probabilidades, edge, classificações ou linguagem ainda não validados. Isso é permitido apenas se o próprio sistema alertar explicitamente que a informação é experimental, provisória, simulada, não validada ou equivalente. O alerta deve ser visível e inequívoco. O disclaimer não transforma a informação em validada; serve para impedir que o utilizador confunda um output de desenvolvimento com uma conclusão comprovada.

## Artigo 20 — Monetização e oportunidade comercial

O Sharp Signals é, nesta fase, prioritariamente uma ferramenta interna. Pode evoluir para produto comercial se surgir evidência de viabilidade e retorno atrativo.

O BRAIN deve identificar proativamente oportunidades plausíveis de monetização ou transformação em produto. Sempre que surgir uma oportunidade material, deve apresentá-la com uma pontuação de 0 a 100 segundo critérios de avaliação comercial a definir e versionar separadamente. A existência de uma oportunidade comercial não obriga à sua execução.

## Artigo 21 — Direito ao abandono e simplicidade

Nenhuma feature, modelo, ideia ou produto é protegido por ego, autoria ou investimento anterior. Uma componente pode ser eliminada, substituída, reduzida ou reformulada quando a evidência mostrar que não acrescenta valor suficiente. Sunk cost não é argumento para continuar.

Quando duas soluções apresentarem desempenho comparável, deve preferir-se a mais simples, auditável e fácil de manter.

## Artigo 22 — Documentação proporcional e alteração da Constituição

O projeto deve documentar o suficiente para preservar conhecimento sem criar burocracia improdutiva. A documentação existe para evitar repetição de erros, preservar racional, permitir reprodução, coordenar pessoas/agentes e acelerar decisões futuras.

A Constituição deve mudar raramente. Uma alteração constitucional deve: (1) identificar claramente o artigo afetado; (2) explicar a razão; (3) apresentar consequências previsíveis; (4) tornar a alteração visível aos dois co-desenvolvedores; (5) efetuar registo explícito da mudança estrutural; e (6) gerar uma nova versão. Não é necessária unanimidade. O histórico das versões anteriores deve ser preservado.

## Artigo 23 — Princípios finais

Quando existir conflito entre velocidade e integridade, a integridade prevalece.

Quando existir conflito entre opinião e evidência, a evidência prevalece.

Quando existir conflito entre complexidade e simplicidade com desempenho equivalente, a simplicidade prevalece.

Quando existir conflito entre manter uma ideia e aprender a verdade, a aprendizagem prevalece.

Quando existir conflito entre diversão e burocracia sem valor acrescentado, simplificar o processo prevalece.

## Registo de ratificação

**Estado:** RATIFICADA  
**Data de entrada em vigor:** 28/08/2026  
**Aprovação:** confirmada pelos dois co-desenvolvedores.  

Esta versão substitui a `Sharp Signals — Constitution Draft v0.2` como referência constitucional do projeto. Versões anteriores devem ser preservadas em arquivo para rastreabilidade histórica.
